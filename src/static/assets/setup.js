/* ── Activity ──────────────────────────────────────────────── */
/* ── Setup Wizard ──────────────────────────────────────────── */
let setupConfigured = true;

async function checkSetupStatus() {
  try {
    const r = await get('/setup-status');
    setupConfigured = r.configured;
    return r.configured;
  } catch(e) {
    // Backend unreachable: the setup state is unknown. Return null instead of
    // claiming "configured" (which hid the failure) and instead of forcing the
    // setup wizard (which would be a lie in the other direction). Callers only
    // redirect on an explicit false.
    return null;
  }
}

async function loadSetup(el) {
  el.innerHTML = `
    <div class="setup-shell">
      <div class="setup-brand">
        <div class="logo-icon">${uiIcon('send')}</div>
        <h1>欢迎使用 WhatsApp-bot</h1>
        <p>首次使用请配置 AI 服务。配置完成后，管理控制台即可读取本地数据。</p>
      </div>
      <div class="panel setup-card" style="text-align:left">
        <div class="panel-body">
          <div class="detail-field">
            <label>LLM API Key</label>
            <input class="input" id="setup-apikey" type="password" placeholder="请输入你的 API Key（如 DeepSeek Key）" style="width:100%;height:42px">
            <div class="proxy-note">需要 DeepSeek API Key？<a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">点击获取</a></div>
          </div>
          <div class="detail-field" style="margin-top:18px">
            <label>HTTPS 代理（选填，国内网络通常需要）</label>
            <input class="input" id="setup-proxy" placeholder="例: http://127.0.0.1:7890" style="width:100%;height:42px">
            <div class="proxy-note">WhatsApp 在国内需通过代理连接。常用端口：Clash 7890、V2Ray 10809。</div>
          </div>
          <div style="margin-top:22px">
            <button class="btn btn-primary btn-block" onclick="saveSetup()" style="height:42px">保存并开始使用</button>
          </div>
          <div id="setup-error" class="text-danger" style="display:none;font-size:12px;margin-top:10px;text-align:center"></div>
        </div>
      </div>
      <div class="setup-note">
        <p>API Key 保存在本地数据目录，不会上传到本项目的服务器。</p>
        <p style="margin-top:6px">配置完成后，在<a href="#" onclick="navigate('bridge');return false">桥接状态</a>页面扫码登录 WhatsApp。</p>
      </div>
    </div>`;
  get('/proxy').then(r => {
    const inp = document.getElementById('setup-proxy');
    if (inp && r.proxy) inp.value = r.proxy;
  }).catch(() => {});
}

async function saveSetup() {
  const key = document.getElementById('setup-apikey').value.trim();
  const proxyInput = document.getElementById('setup-proxy');
  const proxy = proxyInput ? proxyInput.value.trim() : '';
  const errEl = document.getElementById('setup-error');
  if (!key) {
    errEl.textContent = '请输入 API Key';
    errEl.style.display = 'block';
    return;
  }
  const btn = document.querySelector('#page-setup .btn-primary');
  btn.disabled = true;
  btn.textContent = '保存中…';
  try {
    const r = await post('/setup', {api_key: key});
    if (!r.ok) {
      errEl.textContent = r.error || '保存失败';
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = '保存并开始使用';
      return;
    }
    // Also save proxy if provided
    if (proxy) {
      await post('/proxy', {proxy});
    }
    setupConfigured = true;
    // Go to bridge page for QR scan
    navigate('bridge');
  } catch(e) {
    errEl.textContent = '网络错误，请重试';
    errEl.style.display = 'block';
  }
  btn.disabled = false;
  btn.textContent = '保存并开始使用';
}

/* ── Activity ──────────────────────────────────────────────── */
