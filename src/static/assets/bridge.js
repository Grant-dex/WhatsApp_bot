/* ── Bridge ────────────────────────────────────────────────── */

let qrcodeLoaded = false;
let qrWaitStarted = 0;

function loadQrCodeLib() {
  // qrcodejs is bundled above; no runtime CDN request is needed.
  qrcodeLoaded = !!window.QRCode;
  if (!qrcodeLoaded) console.error('QR library missing');
  return Promise.resolve(qrcodeLoaded);
}

async function startQrPolling() {
  if (qrPollTimer) return;
  await loadQrCodeLib();
  qrWaitStarted = Date.now();
  qrPollTimer = setInterval(async () => {
    try {
      const r = await get('/qr');
      const qrDiv = document.getElementById('qr-area');
      if (!qrDiv) { clearInterval(qrPollTimer); qrPollTimer = null; return; }
      if (r.status === 'pending' && r.qr_text) {
        qrDiv.innerHTML = '<div class="qr-container"><div id="qr-code"></div>'
          + '<div class="qr-hint">用手机 WhatsApp 扫描</div>'
          + '<div class="qr-tip">二维码每 20 秒刷新一次，扫的时候别停顿；过期了点「刷新状态」拿新的</div>'
          + '</div>';
        const el = document.getElementById('qr-code');
        if (el && !el.hasChildNodes() && window.QRCode) {
          new QRCode(el, { text: r.qr_text, width: 220, height: 220, colorDark: '#0F766E', colorLight: '#FFFFFF' });
        }
        const successDiv = document.getElementById('qr-success');
        if (successDiv) successDiv.style.display = 'none';
      } else if (r.status === 'none') {
        const qrEl = document.getElementById('qr-code');
        if (!qrEl || !qrEl.hasChildNodes()) {
          // 还没拿到二维码：按等待时长给不同提示，避免一直停在“正在加载”
          const waited = Math.round((Date.now() - qrWaitStarted) / 1000);
          const hint = qrDiv.querySelector('.qr-hint');
          if (hint) {
            if (waited > 40) {
              hint.innerHTML = '已经等了 ' + waited + ' 秒还没收到二维码。<br>桥接可能在反复重连 —— 点右上角「重启连接」，或查看 logs/bridge.log。';
            } else if (waited > 10) {
              hint.textContent = '正在等待二维码…（桥接正在连接 WhatsApp，通常几秒内出现）';
            }
          }
        } else if (qrEl && qrEl.hasChildNodes()) {
          const successDiv = document.getElementById('qr-success');
          if (successDiv) successDiv.style.display = 'block';
          qrDiv.innerHTML = '<div class="qr-container"><div class="qr-success" style="display:block">二维码已失效或已处理，请刷新连接状态</div></div>';
          const btn = document.getElementById('qr-toggle-btn');
          if (btn) { btn.textContent = '刷新状态'; btn.disabled = true; }
          clearInterval(qrPollTimer); qrPollTimer = null;
          setTimeout(() => loadBridge(document.getElementById('page-bridge')), 2000);
        }
      }
    } catch(e) {
      const qrDiv = document.getElementById('qr-area');
      if (qrDiv) qrDiv.textContent = '读取二维码失败，请隐藏后重新打开：' + e.message;
      clearInterval(qrPollTimer); qrPollTimer = null;
    }
  }, 3000);
}

async function restartBridge() {
  const hint = document.getElementById('bridge-start-hint');
  try {
    await post('/bridge/stop', {});
    await new Promise(r => setTimeout(r, 900));
    const r = await post('/bridge/start', {});
    if (r && r.ok === false) {
      alert('重启失败：' + (r.error || '未知错误'));
      return;
    }
    await loadPage('bridge');
  } catch (e) {
    if (hint) hint.textContent = '重启失败：' + (e && e.message ? e.message : e);
  }
}

function toggleQr() {
  const qrArea = document.getElementById('qr-area');
  const btn = document.getElementById('qr-toggle-btn');
  const placeholder = document.getElementById('qr-placeholder');
  if (!qrArea || !btn) return;
  if (qrPollTimer) {
    clearInterval(qrPollTimer); qrPollTimer = null;
    qrArea.style.display = 'none';
    if (placeholder) placeholder.style.display = '';
    btn.textContent = '显示二维码';
  } else {
    qrArea.style.display = '';
    if (placeholder) placeholder.style.display = 'none';
    const successDiv = document.getElementById('qr-success');
    if (successDiv) successDiv.style.display = 'none';
    qrArea.innerHTML = '<div class="qr-container"><div class="qr-hint">正在加载二维码...</div></div>';
    btn.textContent = '隐藏二维码';
    startQrPolling();
  }
}

let productDocsCache = [];

