/* ── Bridge ────────────────────────────────────────────────── */

let qrcodeLoaded = false;

function loadQrCodeLib() {
  // qrcodejs is bundled above; no runtime CDN request is needed.
  qrcodeLoaded = !!window.QRCode;
  if (!qrcodeLoaded) console.error('QR library missing');
  return Promise.resolve(qrcodeLoaded);
}

async function startQrPolling() {
  if (qrPollTimer) return;
  await loadQrCodeLib();
  qrPollTimer = setInterval(async () => {
    try {
      const r = await get('/qr');
      const qrDiv = document.getElementById('qr-area');
      if (!qrDiv) { clearInterval(qrPollTimer); qrPollTimer = null; return; }
      if (r.status === 'pending' && r.qr_text) {
        qrDiv.innerHTML = '<div class="qr-container"><div id="qr-code"></div><div class="qr-hint">请用手机 WhatsApp 扫描二维码登录</div></div>';
        const el = document.getElementById('qr-code');
        if (el && !el.hasChildNodes() && window.QRCode) {
          new QRCode(el, { text: r.qr_text, width: 220, height: 220, colorDark: '#0F766E', colorLight: '#FFFFFF' });
        }
        const successDiv = document.getElementById('qr-success');
        if (successDiv) successDiv.style.display = 'none';
      } else if (r.status === 'none') {
        const qrEl = document.getElementById('qr-code');
        if (qrEl && qrEl.hasChildNodes()) {
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

