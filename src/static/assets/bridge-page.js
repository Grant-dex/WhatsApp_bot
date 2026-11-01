async function loadBridge(el) {
  if (qrPollTimer) { clearInterval(qrPollTimer); qrPollTimer = null; }
  const d = await get('/bridge');
  const online = !!d.online;
  const auth = online && !!d.authenticated;
  updateBridgeIndicator({online, authenticated: auth, known: true, phone: d.phone});

  const processLabel = online ? '运行中' : '已停止';
  const processClass = online ? 'green' : 'red';
  const authLabel = auth ? '已认证' : (online ? '未认证' : '未知');
  const authClass = auth ? 'green' : (online ? 'orange' : 'red');
  const phoneLabel = d.phone ? formatPhone(d.phone) : '—';

  const eventsHtml = (d.recent_events || []).map(e => {
    const error = e.includes('DISCONNECTED') || e.includes('exit') || e.includes('[ERROR]');
    return `<div class="timeline-item ${error ? 'error' : ''}">
      <div class="tl-time">${escapeHtml(String(e).substring(0,19))}</div>
      <div class="tl-text">${escapeHtml(String(e).substring(20,180))}</div>
    </div>`;
  }).join('');

  const qrAction = (!auth && online)
    ? `<button class="btn btn-outline btn-sm" onclick="restartBridge()">${uiIcon('refresh')} 重启连接</button>
       <button class="btn btn-outline btn-sm" id="qr-toggle-btn" onclick="toggleQr()">${uiIcon('qr')} 显示二维码</button>`
    : '';
  const qrBody = auth
    ? `<div class="qr-panel-body"><span class="stat-icon green" style="width:54px;height:54px;border-radius:15px">${uiIcon('whatsapp')}</span><div style="font-size:14px;font-weight:600">当前账号已连接</div><div class="text-muted text-sm">${escapeHtml(phoneLabel)}</div><div class="text-muted text-xs">如需更换账号，请先退出登录后重启桥接进程。</div></div>`
    : online
      ? `<div class="qr-panel-body" id="qr-area" style="display:none"><div class="qr-container"><div class="qr-hint">正在加载二维码...</div></div></div><div id="qr-success" class="qr-success" style="display:none">二维码已扫码，等待连接...</div><div class="qr-panel-body" id="qr-placeholder"><span class="stat-icon orange" style="width:54px;height:54px;border-radius:15px">${uiIcon('qr')}</span><div class="text-muted text-sm">点击「显示二维码」后用手机 WhatsApp 扫描</div><div class="text-muted text-xs" style="margin-top:6px">二维码每 20 秒刷新一次，扫的时候别停顿</div></div>`
      : `<div class="qr-panel-body"><span class="stat-icon red" style="width:54px;height:54px;border-radius:15px">${uiIcon('bridge')}</span><div style="font-size:13px;font-weight:600">桥接未运行</div><div class="text-muted text-xs">为当前账号启动一个独立的 WhatsApp 连接</div><button class="btn btn-primary btn-sm" style="margin-top:14px" onclick="startBridge()">启动连接</button><div class="text-muted text-xs" id="bridge-start-hint" style="margin-top:8px"></div></div>`;

  el.innerHTML = `
    ${pageHeader('桥接状态', 'WhatsApp 连接监控', `<button class="btn btn-outline btn-sm" onclick="loadPage('bridge')">${uiIcon('refresh')} 刷新状态</button>`)}
    <div class="stats" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="stat-card bridge-status-card">
        <div class="stat-top"><span class="stat-icon ${processClass}">${uiIcon('bridge')}</span><span class="stat-label">桥接进程</span></div>
        <div class="stat-val" style="color:${online?'var(--green)':'var(--red)'}">${processLabel}</div>
        <div class="stat-sub">${online ? '<span class="text-ok">进程状态正常</span>' : '未检测到桥接进程'}</div>
        ${!online && d.error ? `<div class="bridge-error">${escapeHtml(String(d.error).substring(0,120))}</div>` : ''}
      </div>
      <div class="stat-card bridge-status-card">
        <div class="stat-top"><span class="stat-icon ${authClass}">${uiIcon('whatsapp')}</span><span class="stat-label">WhatsApp 认证</span></div>
        <div class="stat-val" style="color:${auth?'var(--green)':online?'var(--orange)':'var(--red)'}">${authLabel}</div>
        <div class="stat-sub">${auth ? '<span class="text-ok">认证状态正常</span>' : online ? '等待扫码认证' : '无法获取认证状态'}</div>
      </div>
      <div class="stat-card bridge-status-card">
        <div class="stat-top"><span class="stat-icon">${uiIcon('phone')}</span><span class="stat-label">手机号码</span></div>
        <div class="stat-val compact">${escapeHtml(phoneLabel)}</div>
        <div class="stat-sub">${auth ? '已连接' : '未连接'}</div>
      </div>
    </div>

    <div class="bridge-grid">
      <div class="panel">
        <div class="panel-header"><h3>网络代理</h3><span class="panel-meta">用于连接 WhatsApp</span></div>
        <div class="panel-body">
          <label class="f-label">代理地址</label>
          <div style="display:flex;gap:8px;align-items:center">
            <input class="input" id="proxy-input" aria-label="WhatsApp 网络代理地址" placeholder="例: http://127.0.0.1:7890" style="flex:1">
            <button class="btn btn-primary" id="save-proxy-btn" onclick="saveProxy(this)">保存代理</button>
          </div>
          <div class="proxy-note">保存后需重启 Bridge 才会生效。代理用于 WhatsApp 连接，不影响机器人暂停状态。</div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><h3>扫码登录</h3>${qrAction}</div>
        ${qrBody}
      </div>
    </div>

    <div class="panel">
      <div class="panel-header"><h3>最近桥接事件</h3><span class="panel-meta">来自桥接进程日志</span></div>
      <div class="panel-body bridge-events">
        <div class="timeline">${eventsHtml || '<div class="empty-state"><p>暂无桥接事件</p></div>'}</div>
      </div>
    </div>`;

  try {
    const pr = await get('/proxy');
    const proxyInput = document.getElementById('proxy-input');
    if (proxyInput && pr.proxy) proxyInput.value = pr.proxy;
  } catch (e) {
    const input = document.getElementById('proxy-input');
    if (input) { input.disabled = true; input.placeholder = '读取代理配置失败'; }
    const button = document.getElementById('save-proxy-btn');
    if (button) button.disabled = true;
    const note = el.querySelector('.proxy-note');
    if (note) { note.textContent = '代理配置读取失败：' + e.message + '。请点击刷新状态后再编辑。'; note.classList.add('text-danger'); }
  }
}

function updateNavDot(online, authenticated) {
  updateBridgeIndicator({online: !!online, authenticated: authenticated === undefined ? !!online : !!authenticated, known: true});
}

async function saveProxy(btn) {
  const inp = document.getElementById('proxy-input');
  const proxy = inp.value.trim();
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '保存中...';
  try {
    const r = await post('/proxy', {proxy});
    if (!r.ok) throw new Error(r.error || '后端未确认保存');
    uiAlert(r.note || '代理已保存');
  } catch(e) {
    uiAlert('保存失败: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}



async function startBridge() {
  const hint = document.getElementById('bridge-start-hint');
  if (hint) hint.textContent = '正在启动…';
  try {
    const r = await post('/bridge/start', {});
    if (!r || r.ok === false) {
      if (hint) hint.textContent = (r && r.error) || '启动失败';
      return;
    }
    await loadPage('bridge');
  } catch (e) {
    if (hint) hint.textContent = '启动失败：' + (e && e.message ? e.message : e);
  }
}
