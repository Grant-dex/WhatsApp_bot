const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
let bridgeProcess = null;
let backendRestarts = 0;

const isDev = !app.isPackaged;
const APP_NAME = 'WhatsApp-机器人';

function getResourcePath(relativePath) {
  if (isDev) {
    return path.join(__dirname, '..', relativePath);
  }
  return path.join(process.resourcesPath, relativePath);
}

function getUserDataPath() {
  return app.getPath('userData');
}

function ensureUserData() {
  const userDataPath = getUserDataPath();
  const dirs = ['data', 'logs'];
  dirs.forEach(dir => {
    const p = path.join(userDataPath, dir);
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  });

  // Copy default config if not exists
  const configPath = path.join(userDataPath, 'config.yaml');
  if (!fs.existsSync(configPath)) {
    const defaultConfig = getResourcePath('config.yaml');
    if (fs.existsSync(defaultConfig)) {
      fs.copyFileSync(defaultConfig, configPath);
    }
  }

  // Copy product_specs if not exists
  const specsPath = path.join(userDataPath, 'product_specs.txt');
  if (!fs.existsSync(specsPath)) {
    const defaultSpecs = getResourcePath('product_specs.txt');
    if (fs.existsSync(defaultSpecs)) {
      fs.copyFileSync(defaultSpecs, specsPath);
    }
  }

  return userDataPath;
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(port, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const ok = await new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        let body = '';
        res.on('data', d => body += d);
        res.on('end', () => {
          try { resolve(JSON.parse(body).status === 'ok'); }
          catch { resolve(false); }
        });
      });
      req.on('error', () => resolve(false));
      req.setTimeout(2000, () => { req.destroy(); resolve(false); });
    });
    if (ok) return true;
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
}

function startPythonBackend(userDataPath, apiPort, bridgePort) {
  let backendExe;
  if (isDev) {
    backendExe = path.join(__dirname, '..', 'dist', 'whatsapp-bot-backend', 'whatsapp-bot-backend');
  } else {
    backendExe = path.join(process.resourcesPath, 'backend', 'whatsapp-bot-backend');
  }

  const env = {
    ...process.env,
    NO_PROXY: '127.0.0.1,localhost',
    no_proxy: '127.0.0.1,localhost',
    WHATSAPP_BOT_DATA_DIR: userDataPath,
    API_PORT: String(apiPort),
    BRIDGE_HOST: '127.0.0.1',
    BRIDGE_PORT: String(bridgePort),
  };

  console.log(`[main] Starting backend: ${backendExe} (port ${apiPort})`);
  console.log(`[main] Data dir: ${userDataPath}`);

  const proc = spawn(backendExe, [], {
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  proc.stdout.on('data', (data) => {
    console.log(`[python] ${data.toString().trim()}`);
  });

  proc.stderr.on('data', (data) => {
    console.log(`[python:err] ${data.toString().trim()}`);
  });

  proc.on('error', (err) => {
    console.error('[main] Backend failed to start:', err.message);
    dialog.showErrorBox('启动失败', `无法启动后端服务：${err.message}`);
  });

  proc.on('exit', (code) => {
    console.log(`[main] Backend exited with code ${code}`);
    pythonProcess = null;
    if (code !== 0 && mainWindow && !mainWindow.isDestroyed() && backendRestarts < 1) {
      backendRestarts++;
      console.log('[main] Backend crashed, restarting...');
      pythonProcess = startPythonBackend(userDataPath, apiPort, bridgePort);
    } else if (code !== 0) {
      dialog.showErrorBox('后端异常', '后端服务多次崩溃，请检查日志后重启应用。');
    }
  });

  return proc;
}

function startBridge(userDataPath, apiPort, bridgePort) {
  const bridgeDir = getResourcePath('bridge');
  const indexPath = path.join(bridgeDir, 'index.js');

  if (!fs.existsSync(indexPath)) {
    console.error('[main] Bridge index.js not found at', indexPath);
    dialog.showErrorBox('启动失败', 'Bridge 组件缺失，请重新安装应用。');
    app.quit();
    return null;
  }

  const proxyUrl = readProxyFromConfig(userDataPath);
  const env = {
    ...process.env,
    ELECTRON_RUN_AS_NODE: '1',
    BRIDGE_PORT: String(bridgePort),
    BRIDGE_HOST: '127.0.0.1',
    PYTHON_API: `http://127.0.0.1:${apiPort}`,
    NO_PROXY: '127.0.0.1,localhost',
    no_proxy: '127.0.0.1,localhost',
    WHATSAPP_BOT_DATA_DIR: userDataPath,
  };
  if (proxyUrl) {
    env.HTTPS_PROXY = proxyUrl;
    env.https_proxy = proxyUrl;
    console.log(`[main] Bridge proxy: ${proxyUrl}`);
  }

  console.log(`[main] Starting Bridge on port ${bridgePort}`);

  const proc = spawn(process.execPath, [indexPath], {
    cwd: bridgeDir,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  proc.stdout.on('data', (data) => {
    const line = data.toString().trim();
    if (line) console.log(`[bridge] ${line}`);
  });

  proc.stderr.on('data', (data) => {
    console.log(`[bridge:err] ${data.toString().trim()}`);
  });

  proc.on('error', (err) => {
    console.error('[main] Bridge failed to start:', err.message);
    dialog.showErrorBox('启动失败', `Bridge 启动失败：${err.message}`);
    app.quit();
  });

  proc.on('exit', (code) => {
    console.log(`[main] Bridge exited with code ${code}`);
    bridgeProcess = null;
    if (code !== 0 && mainWindow && !mainWindow.isDestroyed() && bridgeRestarts < 3) {
      bridgeRestarts++;
      console.log(`[main] Bridge crashed, restarting (attempt ${bridgeRestarts}/3)...`);
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          bridgeProcess = startBridge(userDataPath, apiPort, bridgePort);
        }
      }, 3000);
    } else if (code !== 0 && bridgeRestarts >= 3) {
      console.log('[main] Bridge restart limit reached');
    }
  });

  return proc;
}

let bridgeRestarts = 0;

function readProxyFromConfig(userDataPath) {
  const configPath = path.join(userDataPath, 'config.yaml');
  try {
    if (fs.existsSync(configPath)) {
      const content = fs.readFileSync(configPath, 'utf8');
      const match = content.match(/^proxy:\s*["']?(.+?)["']?\s*$/m);
      if (match) return match[1].trim();
    }
  } catch (_) { /* ignore */ }
  return '';
}

async function createWindow() {
  backendRestarts = 0;
  bridgeRestarts = 0;
  const userDataPath = ensureUserData();

  // Find free ports
  const apiPort = await findFreePort();
  const bridgePort = await findFreePort();
  console.log(`[main] Allocated ports — API: ${apiPort}, Bridge: ${bridgePort}`);

  // Start Python backend
  pythonProcess = startPythonBackend(userDataPath, apiPort, bridgePort);
  console.log(`[main] Waiting for API health on port ${apiPort}...`);
  const apiReady = await waitForHealth(apiPort, 30000);
  if (!apiReady) {
    dialog.showErrorBox('启动超时', '后端服务未能启动，请重试或联系支持。');
    app.quit();
    return;
  }
  console.log('[main] API server healthy');

  // Start Bridge
  bridgeProcess = startBridge(userDataPath, apiPort, bridgePort);
  // Give the bridge a moment to fail fast
  await new Promise(r => setTimeout(r, 1500));
  if (bridgeProcess && bridgeProcess.exitCode !== null && bridgeProcess.exitCode !== 0) {
    console.log('[main] Bridge failed to start, retrying once...');
    bridgeProcess = startBridge(userDataPath, apiPort, bridgePort);
    await new Promise(r => setTimeout(r, 1500));
  }
  console.log(`[main] Waiting for bridge health on port ${bridgePort}...`);
  const bridgeReady = await waitForHealth(bridgePort, 15000);
  if (!bridgeReady) {
    console.log('[main] Bridge not ready yet, continuing anyway (may need QR scan)');
  } else {
    console.log('[main] Bridge healthy');
  }

  // Create window
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: APP_NAME,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    show: false,
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(`http://127.0.0.1:${apiPort}`);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  console.log('[main] Shutting down...');
  if (bridgeProcess) {
    bridgeProcess.kill('SIGTERM');
    bridgeProcess = null;
  }
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
    pythonProcess = null;
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
