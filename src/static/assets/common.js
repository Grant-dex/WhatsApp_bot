

let _editModalCallback = null;

function showEditModal(title, currentValue, callback) {
  document.getElementById('edit-modal-title').textContent = title;
  document.getElementById('edit-modal-input').value = currentValue || '';
  document.getElementById('edit-modal-overlay').classList.add('show');
  document.getElementById('edit-modal-input').focus();
  document.getElementById('edit-modal-input').select();
  _editModalCallback = callback;
  document.getElementById('edit-modal-ok').onclick = function() {
    const val = document.getElementById('edit-modal-input').value.trim();
    const callback = _editModalCallback;
    closeEditModal();
    if (callback) callback(val);
  };
}

function closeEditModal() {
  document.getElementById('edit-modal-overlay').classList.remove('show');
  _editModalCallback = null;
}

// Click overlay background to close
document.addEventListener('click', function(e) {
  if (e.target.id === 'edit-modal-overlay') closeEditModal();
});


function copyToClipboard(text, label) {
  navigator.clipboard.writeText(text).then(() => showToast(label || '已复制')).catch(() => showToast('复制失败'));
}
function showToast(msg) {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('show'), 1800);
}

/* ── Visual helpers ─────────────────────────────────────────── */
function toggleNav() {
  document.body.classList.toggle('nav-collapsed');
  try { localStorage.setItem('navCollapsed', document.body.classList.contains('nav-collapsed') ? '1' : '0'); } catch (e) {}
}

/* ── Unified dialogs ─────────────────────────────────────────── */
let _dialogResolve = null;
function _closeDialog(result) {
  const overlay = document.getElementById('ui-dialog-overlay');
  const resolve = _dialogResolve;
  _dialogResolve = null;
  if (overlay) overlay.classList.remove('show');
  if (resolve) resolve(result);
}
function uiDialog(options) {
  options = options || {};
  if (_dialogResolve) _closeDialog(false);
  const overlay = document.getElementById('ui-dialog-overlay');
  const title = document.getElementById('ui-dialog-title');
  const message = document.getElementById('ui-dialog-message');
  const input = document.getElementById('ui-dialog-input');
  const ok = document.getElementById('ui-dialog-ok');
  const cancel = document.getElementById('ui-dialog-cancel');
  if (!overlay) return Promise.resolve(false);
  title.textContent = options.title || '提示';
  message.textContent = options.message || '';
  input.style.display = options.input ? '' : 'none';
  input.value = options.defaultValue || '';
  input.placeholder = options.placeholder || '';
  cancel.style.display = options.showCancel === false ? 'none' : '';
  cancel.textContent = options.cancelText || '取消';
  ok.textContent = options.confirmText || '确定';
  ok.className = 'btn btn-sm ' + (options.danger ? 'btn-danger' : 'btn-primary');
  overlay.classList.add('show');
  return new Promise(resolve => {
    _dialogResolve = resolve;
    const finish = (result) => _closeDialog(result);
    ok.onclick = () => finish(options.input ? input.value : true);
    cancel.onclick = () => finish(options.input ? null : false);
    overlay.onclick = (e) => { if (e.target === overlay) finish(options.input ? null : false); };
    input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(input.value); } };
    setTimeout(() => { (options.input ? input : ok).focus(); }, 20);
  });
}
function uiConfirm(message, options) {
  return uiDialog({ ...(options || {}), title: (options && options.title) || '确认操作', message, showCancel: true });
}
function uiAlert(message, options) {
  return uiDialog({ ...(options || {}), title: (options && options.title) || '提示', message, showCancel: false, confirmText: (options && options.confirmText) || '知道了' });
}
function uiPrompt(message, defaultValue, options) {
  return uiDialog({ ...(options || {}), title: (options && options.title) || '请输入', message, input: true, defaultValue: defaultValue || '', confirmText: (options && options.confirmText) || '确定' })
    .then(value => value === false ? null : value);
}
document.addEventListener('keydown', (e) => {
  const overlay = document.getElementById('ui-dialog-overlay');
  if (!overlay || !overlay.classList.contains('show')) return;
  if (e.key === 'Escape') { e.preventDefault(); _closeDialog(false); }
});

function uiIcon(name, cls) {
  const paths = {
    users: '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
    calendar: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/>',
    message: '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>',
    send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    whatsapp: '<path d="M21 11.5a8.5 8.5 0 01-12.6 7.4L3 21l2.1-5.4A8.5 8.5 0 1121 11.5z"/><path d="M8.5 8.7c.2-.4.4-.4.7-.4h.5c.2 0 .4 0 .5.4l.7 1.6c.1.2 0 .4-.1.5l-.5.6c-.1.1-.2.3-.1.5.4.8 1.6 2 2.4 2.4.2.1.4 0 .5-.1l.6-.5c.1-.1.3-.2.5-.1l1.6.7c.3.1.4.3.4.5v.5c0 .3 0 .5-.4.7-.4.3-1.1.5-1.7.4-2.9-.6-5.4-3.1-6-6-.1-.6.1-1.3.4-1.7z"/>',
    layers: '<path d="M12 2l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    alert: '<path d="M10.3 3.6L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.6a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    upload: '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    doc: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h6"/>',
    bridge: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    log: '<path d="M4 19V5a2 2 0 012-2h9l5 5v11a2 2 0 01-2 2H6a2 2 0 01-2-2z"/><path d="M14 3v5h5"/><path d="M8 13h8M8 17h5"/>',
    phone: '<path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.4 1.8.7 2.6a2 2 0 01-.5 2.1L8 9.8a16 16 0 006 6l1.4-1.3a2 2 0 012.1-.5c.8.3 1.7.6 2.6.7a2 2 0 011.9 2.2z"/>',
    box: '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
    refresh: '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/>',
    trash: '<path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/>',
    chevronLeft: '<path d="M15 18l-6-6 6-6"/>',
    chevronRight: '<path d="M9 18l6-6-6-6"/>',
    qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM19 19h2v2M14 21h2M21 14v2"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    pause: '<rect x="8" y="5" width="3" height="14" rx="1"/><rect x="13" y="5" width="3" height="14" rx="1"/>'
  };
  return `<svg class="${cls||''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||''}</svg>`;
}

function initials(name, phone) {
  const raw = (name || '').trim();
  if (raw && raw !== (phone || '')) {
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    if (/[\u4e00-\u9fff]/.test(raw)) return raw.length > 1 ? raw.slice(-2) : raw;
    return raw.slice(0, 2).toUpperCase();
  }
  const digits = String(phone || '').replace(/\D/g, '');
  return digits ? digits.slice(-2) : '?';
}
function avatarClass(name) {
  let hash = 0; const raw = String(name || '');
  for (let i = 0; i < raw.length; i++) hash = ((hash << 5) - hash) + raw.charCodeAt(i);
  return 'av-' + (Math.abs(hash) % 6 + 1);
}
function avatarHtml(name, phone, cls) {
  return `<span class="avatar ${avatarClass(name)} ${cls||''}">${escapeHtml(initials(name, phone))}</span>`;
}
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function friendlyDate(value) {
  if (!value) return '—';
  const day = String(value).slice(0, 10);
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  const tomorrow = new Date(now.getTime() + 86400000);
  const tmr = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth()+1).padStart(2,'0')}-${String(tomorrow.getDate()).padStart(2,'0')}`;
  if (day === today) return '今天';
  if (day === tmr) return '明天';
  const d = new Date(day + 'T00:00:00');
  if (isNaN(d.getTime())) return day;
  return `${d.getMonth()+1}月${d.getDate()}日`;
}
function timeOnly(value) {
  if (!value) return '';
  const s = String(value);
  return s.length >= 16 ? s.slice(11, 16) : s;
}
function timeAgo(value) {
  if (!value) return '—';
  const d = new Date(String(value).replace(' ', 'T'));
  if (isNaN(d.getTime())) return timeShort(value);
  const diff = Math.max(0, Date.now() - d.getTime());
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return `${d.getMonth()+1}-${String(d.getDate()).padStart(2,'0')}`;
}
function pageHeader(title, subtitle, actions) {
  return `<div class="page-header">
    <div class="page-header-left"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle || '')}</p></div>
    <div class="page-header-right">
      ${actions ? `<div class="page-actions">${actions}</div>` : ''}
      ${setupConfigured === false ? '<button class="btn btn-outline btn-sm" onclick="navigate(\'setup\')">配置 AI</button>' : ''}
      <span class="date-chip">${todayStr()}</span>
    </div>
  </div>`;
}
function updateBridgeIndicator(info) {
  info = info || {};
  const known = info.known !== false;
  const online = !!info.online;
  const auth = !!info.authenticated;
  const dot = document.getElementById('bridge-footer-dot');
  const text = document.getElementById('bridge-footer-text');
  const navDot = document.getElementById('nav-dot');
  const stateClass = !known ? '' : online ? (auth ? 'online' : 'warn') : 'offline';
  if (navDot) navDot.className = 'bridge-dot ' + stateClass;
  if (dot) dot.className = 'status-dot ' + stateClass;
  if (text) {
    text.textContent = !known ? 'WhatsApp 状态未知'
      : online ? (auth ? 'WhatsApp 已连接' : 'WhatsApp 未认证')
      : 'WhatsApp 未连接';
  }
}

/* ── SPA Router ─────────────────────────────────────────────── */
const API = '/admin/api';
let currentPage = 'dashboard';
let selectedCustomerId = null;
let qrPollTimer = null;
let convPollTimer = null;
let convPollGeneration = 0;
let expectedHashChange = null; // prevents navigate() + hashchange from loading twice

document.querySelectorAll('nav a[data-page]').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    navigate(a.dataset.page);
  });
});

window.addEventListener('hashchange', () => {
  const page = location.hash.replace('#','') || 'dashboard';
  // navigate() updates the hash itself; ignore that one self-triggered event.
  if (expectedHashChange === location.hash) {
    expectedHashChange = null;
    return;
  }
  expectedHashChange = null;
  navigate(page);
});

function navigate(page) {
  convPollGeneration++;
  if (qrPollTimer) { clearInterval(qrPollTimer); qrPollTimer = null; }
  if (convPollTimer) { clearInterval(convPollTimer); convPollTimer = null; }
  if (!document.getElementById('page-' + page)) page = 'dashboard';
  currentPage = page;
  document.querySelectorAll('nav a').forEach(a => { a.classList.toggle('active', a.dataset.page === page); if (a.dataset.page === page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const el = document.getElementById('page-' + page);
  if (el) el.classList.add('active');
  closeSidebar();
  if (location.hash !== '#' + page) {
    expectedHashChange = '#' + page;
    location.hash = page;
  } else {
    expectedHashChange = null;
  }
  loadPage(page);
}

function closeSidebar() { document.getElementById('detail-sidebar').classList.remove('open'); }
function openSidebar(html) {
  const s = document.getElementById('detail-sidebar');
  s.innerHTML = html; s.classList.add('open');
}

/* ── API helpers ─────────────────────────────────────────────── */
async function apiFetch(url, options = {}, timeoutMs = 0) {
  const controller = new AbortController();
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } finally {
    if (timer) clearTimeout(timer);
  }
}
async function readJson(r) {
  const text = await r.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (e) {
    const ct = r.headers.get('content-type') || 'unknown';
    // Do not silently turn an HTML error page/proxy response into {}; that
    // hides the real failure and produces confusing render errors later.
    throw new Error(`Invalid JSON response (HTTP ${r.status}, ${ct})`);
  }
}
async function get(url) {
  const r = await apiFetch(API + url, {}, 30000);
  const data = await readJson(r);
  if (!r.ok) throw new Error(data.error || data.detail || ('HTTP ' + r.status));
  return data;
}
async function post(url, data) {
  const r = await apiFetch(API + url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const body = await readJson(r);
  if (!r.ok) throw new Error(body.error || body.detail || ('HTTP ' + r.status));
  return body;
}
function importCustomers() {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.xlsx,.csv';
  inp.onchange = async () => {
    const file = inp.files[0]; if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    try {
    const r = await fetch(API + '/customers/import', {method:'POST', body:fd});
    const d = await readJson(r);
    if (!r.ok) throw new Error(d.error || d.detail || ('HTTP ' + r.status));
    if (d.error) { uiAlert('导入失败：' + d.error); return; }
    let msg = `导入完成！成功 ${d.imported} 条`;
    if (d.skipped && d.skipped.length > 0) {
      msg += `，跳过 ${d.skipped.length} 条`;
      const details = d.skipped.slice(0, 10).map(s => `第${s.row}行: ${s.reason}`).join('\n');
      msg += '\n\n跳过详情（最多显示10条）：\n' + details;
    }
    uiAlert(msg);
    await loadPage('customers');
    } catch (e) { await uiAlert('导入失败：' + e.message); }
  };
  inp.click();
}
async function del(url) {
  const r = await apiFetch(API + url, {method:'DELETE'}, 15000);
  const data = await readJson(r);
  if (!r.ok) throw new Error(data.error || data.detail || ('HTTP ' + r.status));
  return data;
}
async function put(url, data) {
  const r = await apiFetch(API + url, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}, 15000);
  const body = await readJson(r);
  if (!r.ok) throw new Error(body.error || body.detail || ('HTTP ' + r.status));
  return body;
}

function formatPhone(p) { if (!p) return ''; return p.replace('@lid','').replace('@c.us',''); }
function timeShort(t) { if (!t) return ''; return t.replace('T',' ').substring(0,16); }
function ov(v, fb) { return (v === undefined || v === null) ? (fb||'—') : v; }
function badgeStatus(s) {
  const map = {active:'badge-active',inactive:'badge-inactive',blocked:'badge-blocked',opted_out:'badge-opted_out'};
  const labels = {active:'活跃',inactive:'非活跃',blocked:'已屏蔽',opted_out:'已退订'};
  return `<span class="badge ${map[s]||'badge-inactive'}">${escapeHtml(labels[s]||s||'未知')}</span>`;
}
function badgeSent(s) {
  return s === 'sent' ? '<span class="badge badge-green">已发送</span>'
    : s === 'failed' ? '<span class="badge badge-red">失败</span>'
    : s === 'unknown' ? '<span class="badge badge-orange">结果待确认</span>'
    : s === 'pending' ? '<span class="badge badge-blue">发送中</span>'
    : s === 'received' ? '<span class="badge badge-blue">已接收</span>'
    : '<span class="badge badge-orange">待处理</span>';
}

// Delivery state is shown separately from "sent". A sent message is not
// necessarily read; unknown means the platform result could not be confirmed.
function deliveryStatusText(status) {
  return ({sent:'已发送', pending:'发送中', unknown:'结果待确认', failed:'发送失败', received:'已接收'})[status] || '';
}
function msgDeliveryBadge(m) {
  if (!m || m.direction !== 'outbound') return '';
  const label = deliveryStatusText(m.status);
  return label ? ` · <span>${label}</span>` : '';
}

function escapeHtml(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escapeJs(s) { return String(s ?? '').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/\n/g,'\\n').replace(/\r/g,'\\r').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ── Page Loaders ────────────────────────────────────────────── */
let pageLoadSequence = 0;
async function loadPage(page) {
  const el = document.getElementById('page-' + page);
  if (!el) return;
  const seq = ++pageLoadSequence;
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  try {
    switch(page) {
      case 'dashboard': await loadDashboard(el); break;
      case 'customers': await loadCustomers(el); break;
      case 'conversations': await loadConversations(el); break;
      case 'followups': await loadFollowups(el); break;
      case 'orders': await loadOrders(el); break;
      case 'product-docs': await loadProductDocs(el); break;
      case 'bridge': await loadBridge(el); break;
      case 'activity': await loadActivity(el); break;
      case 'setup': await loadSetup(el); break;
    }
  } catch (e) {
    if (seq !== pageLoadSequence) return;
    console.error('[loadPage] ' + page + ' failed:', e);
    el.innerHTML = `
      <div class="page-header"><h1>页面加载失败</h1><p>${escapeHtml(page)}</p></div>
      <div class="panel"><div class="panel-body" style="text-align:center;padding:36px 24px">
        <div style="font-size:15px;font-weight:600;color:var(--red);margin-bottom:8px">无法从后端读取数据</div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:10px;word-break:break-all">${escapeHtml(e && e.message ? e.message : String(e))}</div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:16px;word-break:break-all">页面来源：${escapeHtml(location.origin || 'unknown')} · 接口前缀：${escapeHtml(API)}</div>
        <div style="font-size:12px;color:var(--text3);margin-bottom:18px">请检查 Web 服务是否正在运行，然后手动重试。</div>
        <button class="btn btn-primary" onclick="loadPage('${page}')">重试</button>
      </div></div>`;
  }
}

/* ── Bot Pause ─────────────────────────────────────────────── */
let lastPauseState = null;

function applyPauseState(paused) {
  const sw = document.getElementById('pause-switch');
  if (sw) sw.checked = !!paused;
  const label = document.getElementById('pause-label');
  if (label) {
    label.textContent = paused ? '已暂停' : '未暂停';
    label.className = 'pause-status' + (paused ? ' paused' : '');
    label.style.color = '';
  }
  const banner = document.getElementById('banner-paused');
  if (banner) banner.classList.toggle('show', !!paused);
  const area = document.querySelector('.pause-toggle-area');
  if (area) area.title = paused ? '暂停机器人：已暂停' : '暂停机器人：未暂停';
}

function applyPauseUnknown() {
  const label = document.getElementById('pause-label');
  if (label) {
    label.textContent = '状态未知';
    label.className = 'pause-status';
    label.style.color = '#F3A5A5';
  }
  const sw = document.getElementById('pause-switch');
  if (sw) sw.disabled = true;
  const stats = document.getElementById('pause-stats');
  if (stats) stats.textContent = '后端不可达，暂停状态未知';
  const area = document.querySelector('.pause-toggle-area');
  if (area) area.title = '暂停机器人：状态未知';
}

async function checkBotState() {
  let stateOk = false;
  try {
    const s = await get('/bot-state');
    if (typeof s.paused !== 'boolean') throw new Error('暂停状态返回格式错误');
    stateOk = true;
    lastPauseState = s.paused;
    applyPauseState(s.paused);
    const sw = document.getElementById('pause-switch');
    if (sw) sw.disabled = false;
    const stats = document.getElementById('pause-stats');
    if (stats) stats.textContent = `今日 AI 回复 ${s.today_ai_replies} · 跟进 ${s.today_followups}`;
  } catch(e) {
    // A stale "运行中" was how a dead backend got mistaken for a healthy one.
    applyPauseUnknown();
  }
  // Keep "bot paused" and "WhatsApp connected" as separate facts.
  try {
    const b = await get('/bridge');
    updateBridgeIndicator({online: b.online, authenticated: b.authenticated, known: true, phone: b.phone});
  } catch(e) {
    updateBridgeIndicator({known: false});
  }
}

async function toggleBotPause() {
  const sw = document.getElementById('pause-switch');
  const previous = lastPauseState;
  if (sw) sw.disabled = true;
  try {
    const r = await post('/bot-state/toggle', {});
    if (typeof r.paused !== 'boolean') throw new Error('暂停状态返回格式错误');
    lastPauseState = r.paused;
    applyPauseState(r.paused);
    showToast(r.paused ? '已暂停机器人' : '已恢复机器人');
  } catch(e) {
    // Revert to the last server-confirmed state; never leave a toggle that
    // claims a state the backend did not confirm.
    if (previous === null) {
      applyPauseUnknown();
    } else {
      applyPauseState(previous);
      if (sw) sw.disabled = false;
    }
    uiAlert('暂停状态保存失败，已恢复原状态');
  } finally {
    if (sw && lastPauseState !== null) sw.disabled = false;
  }
}

/* ── Dashboard ─────────────────────────────────────────────── */
async function showFollowupDate(date) {
  const d = await get('/followups/by-date?date=' + date);
  let items = d.items.map(f => `
    <tr>
      <td style="font-weight:600">${escapeHtml(f.name||formatPhone(f.phone))}</td>
      <td class="mono">${escapeHtml(formatPhone(f.phone))}</td>
      <td>${escapeHtml(f.company||'—')}</td>
    </tr>`).join('');
  openSidebar(`
    <div class="sidebar-header">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <h4>${date} 跟进计划</h4>
        <button onclick="closeSidebar()" style="background:none;border:none;color:var(--text3);font-size:18px;cursor:pointer">×</button>
      </div>
      <div style="font-size:12px;color:var(--text3);margin-top:4px">共 ${d.items.length} 个客户待跟进</div>
    </div>
    <div class="sidebar-body">
    <div class="mt-md"><table>${items||'<tr><td colspan=3 class="text-muted" style="text-align:center;padding:20px">无</td></tr>'}</table></div>
    <div class="detail-actions">
      ${d.items.map(f => `
          <button class="btn btn-outline btn-sm w-full" onclick="openConversation(${Number(f.customer_id)})">${escapeHtml(f.name||formatPhone(f.phone))}</button>
      `).join('')}
    </div>
    </div>`);
}

