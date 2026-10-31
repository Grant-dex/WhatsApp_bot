/* ── Conversations ─────────────────────────────────────────── */
let convList = null;

async function editCustomerName(id, currentName) {
  const defaultVal = currentName || formatPhone(convList?.find(c => c.id === id)?.phone || '');
  showEditModal('修改客户名称', defaultVal, async function(newName) {
    if (!newName || newName === defaultVal) return;
    try {
      const r = await post(`/customers/${id}/status`, {name: newName});
      if (!r.ok) { uiAlert('修改名称失败：' + (r.error || '未知错误')); return; }
      if (currentPage === 'conversations') loadPage('conversations');
    } catch (error) { uiAlert('修改名称失败：' + (error.message || String(error))); }
  });
}

async function deleteCustomer(id, name) {
  try { await deleteCustomerAction(id, name); }
  catch (error) { uiAlert('删除客户失败：' + (error.message || String(error))); }
}

async function deleteCustomerAction(id, name) {
  const label = name || ('#' + id);
  if (!(await uiConfirm(`确定删除客户「${label}」吗？\n\n此操作将同时删除：\n- 客户基本信息\n- 所有对话记录\n- 跟进计划\n- 已发送的跟进消息\n\n此操作不可恢复！`))) return;
  const r = await del(`/customers/${id}`);
  if (r.ok) {
    if (selectedCustomerId === id) { selectedCustomerId = null; closeSidebar(); }
    loadCustomers(document.getElementById('page-customers'));
    uiAlert(`客户「${label}」已删除`);
  } else {
    uiAlert('删除失败: ' + (r.error || '未知错误'));
  }
}

async function deleteCustomerConversations(id, name) {
  try { await deleteCustomerConversationsAction(id, name); }
  catch (error) { uiAlert('删除对话失败：' + (error.message || String(error))); }
}

async function deleteCustomerConversationsAction(id, name) {
  const label = name || formatPhone(convList?.find(c => c.id === id)?.phone || '');
  if (!(await uiConfirm(`确定删除 ${label} 的全部对话记录吗？此操作不可恢复。`))) return;
  const r = await del(`/customers/${id}/conversations`);
  if (r.ok) {
    if (selectedCustomerId === id) {
      selectedCustomerId = null;
      document.getElementById('chat-area').innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text3)">选择一个对话查看</div>';
    }
    loadPage('conversations');
  }
}

let conversationFilter = 'all', conversationSearch = '';
let activeConversationCustomer = null;
const replyDraftMemory = new Map();
const pendingManualSends = new Set();
const replyTemplates = [
  {label:'确认需求', text:'Thank you for your inquiry. Could you share the required power output, voltage, frequency, fuel type, and installation location? This will help us recommend a suitable generator set.'},
  {label:'补充现场条件', text:'To prepare a suitable solution, could you confirm the site altitude, ambient temperature, and gas composition? Please also let us know your target delivery date.'},
  {label:'礼貌跟进', text:'Hello, I wanted to follow up on your generator project. Is there any additional technical information you need from us? I would be happy to help with the next step.'}
];

function openConversation(id) {
  selectedCustomerId = Number(id);
  conversationFilter = 'all'; conversationSearch = '';
  navigate('conversations');
}
function openInbox(filter = 'all') {
  conversationFilter = filter; conversationSearch = ''; selectedCustomerId = null;
  navigate('conversations');
}
function replyDraftKey(customer) {
  return `wa-sales:draft:v1:${customer.id}:${customer.phone}`;
}
function readReplyDraft(customer) {
  const key = replyDraftKey(customer);
  try { return localStorage.getItem(key) ?? replyDraftMemory.get(key) ?? ''; }
  catch (_) { return replyDraftMemory.get(key) || ''; }
}
function storeReplyDraft(customer, value) {
  const key = replyDraftKey(customer);
  replyDraftMemory.set(key, value);
  try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); return true; }
  catch (_) { return false; }
}
function onReplyInput(id) {
  const customer = activeConversationCustomer;
  if (!customer || customer.id !== id) return;
  const input = document.getElementById('manual-msg');
  if (!input) return;
  const stored = storeReplyDraft(customer, input.value);
  const status = document.getElementById('draft-status');
  if (status) status.textContent = input.value ? (stored ? '草稿已保存在此浏览器' : '草稿暂存于本页，刷新后可能丢失') : 'Ctrl / ⌘ + Enter 发送';
  const button = document.getElementById('manual-send-btn');
  if (button) button.disabled = !input.value.trim() || pendingManualSends.has(replyDraftKey(customer));
}
function insertReplyTemplate(index) {
  const input = document.getElementById('manual-msg');
  const template = replyTemplates[index];
  if (!input || !template || !activeConversationCustomer) return;
  const start = input.selectionStart ?? input.value.length, end = input.selectionEnd ?? start;
  input.setRangeText(template.text, start, end, 'end');
  onReplyInput(activeConversationCustomer.id);
  document.getElementById('reply-template-panel').hidden = true;
  document.getElementById('reply-template-toggle').setAttribute('aria-expanded', 'false');
  input.focus();
}
function toggleReplyTemplates() {
  const panel = document.getElementById('reply-template-panel');
  if (!panel) return;
  panel.hidden = !panel.hidden;
  document.getElementById('reply-template-toggle').setAttribute('aria-expanded', String(!panel.hidden));
}
function toggleCustomerContext() {
  const layout = document.getElementById('conv-layout');
  if (!layout) return;
  const open = !layout.classList.contains('context-open');
  layout.classList.toggle('context-open', open);
  layout.classList.toggle('context-closed', !open);
  document.getElementById('context-toggle')?.setAttribute('aria-expanded', String(open));
}
function selectConversationFilter(filter) {
  conversationFilter = filter;
  document.querySelectorAll('.inbox-tab').forEach(b => {
    const active = b.dataset.filter === filter;
    b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active));
  });
  renderConversationList();
}
function renderConversationList() {
  const target = document.querySelector('.chat-items');
  if (!target || !convList) return;
  const q = conversationSearch.trim().toLowerCase();
  const list = convList.filter(c => (conversationFilter !== 'reply' || c.needs_reply) &&
    (!q || `${c.name} ${c.phone} ${c.company || ''} ${c.last_content || ''}`.toLowerCase().includes(q)));
  target.innerHTML = list.map(c => `<button class="chat-item ${selectedCustomerId === c.id ? 'active' : ''}" data-cid="${Number(c.id)}" onclick="selectCustomer(${Number(c.id)})" aria-label="打开 ${escapeHtml(c.name || formatPhone(c.phone))} 的对话" aria-current="${selectedCustomerId === c.id ? 'true' : 'false'}">
    ${avatarHtml(c.name, c.phone)}<span class="chat-item-main"><span class="chat-item-top"><span class="chat-name">${escapeHtml(c.name || formatPhone(c.phone))}</span><span class="chat-time">${timeAgo(c.last_msg)}</span></span>
    <span class="chat-item-bottom"><span class="chat-preview">${readReplyDraft(c) ? '<em>草稿 · </em>' : c.last_direction === 'outbound' ? '你：' : ''}${escapeHtml(readReplyDraft(c) || c.last_content || '暂无消息内容')}</span>${c.needs_reply ? '<span class="needs-reply-dot" title="待回复"></span>' : ''}</span>
    <span class="chat-item-meta">${escapeHtml(c.company || formatPhone(c.phone))}${c.needs_reply ? '<span>待回复</span>' : ''}</span></span></button>`).join('') || `<div class="workspace-empty">${uiIcon(conversationFilter === 'reply' ? 'check' : 'search')}<strong>${q ? '没有找到匹配的客户' : '当前没有待回复客户'}</strong><p>${q ? '试试客户姓名、公司或消息关键词。' : '可切换到全部对话继续查看。'}</p></div>`;
  const count = document.getElementById('reply-filter-count');
  if (count) count.textContent = convList.filter(c => c.needs_reply).length;
}
async function loadConversations(el) {
  const generation = convPollGeneration;
  const data = await get('/customers-with-conversations');
  if (generation !== convPollGeneration || currentPage !== 'conversations') return;
  if (!Array.isArray(data)) throw new Error('对话列表返回格式错误');
  convList = data;
  el.innerHTML = `${pageHeader('客户收件箱', '对话、客户背景和下一步，在同一个工作区。')}
    <div class="panel inbox-panel"><div class="conv-layout" id="conv-layout">
      <section class="chat-list" id="conv-list" aria-label="客户对话列表"><div class="chat-list-header"><div class="chat-list-title">对话<span>最近 ${convList.length} 位</span></div>
        <div class="chat-list-search">${uiIcon('search')}<input id="conv-search" aria-label="搜索客户与消息" placeholder="搜索客户、公司或最新消息" oninput="filterConversationList(this.value)" value="${escapeHtml(conversationSearch)}"></div>
        <div class="inbox-tabs"><button class="inbox-tab ${conversationFilter === 'all' ? 'active' : ''}" data-filter="all" aria-pressed="${conversationFilter === 'all'}" onclick="selectConversationFilter('all')">全部</button><button class="inbox-tab ${conversationFilter === 'reply' ? 'active' : ''}" data-filter="reply" aria-pressed="${conversationFilter === 'reply'}" onclick="selectConversationFilter('reply')">待回复 <span id="reply-filter-count">0</span></button></div></div>
        <div class="chat-items"></div><div class="inbox-list-note">待回复按有效消息判断，不代表未读。</div></section>
      <section class="chat-area" id="chat-area" aria-label="对话工作区"><div class="chat-empty">${uiIcon('message')}<strong>每一次对话，都有下一步</strong><p>选择一位客户，查看消息与客户背景。</p></div></section>
      <aside class="customer-context" id="customer-context" aria-label="当前客户概览"><div class="workspace-empty"><p>选择客户后查看概览</p></div></aside>
    </div></div>`;
  renderConversationList();
  const first = convList.find(c => conversationFilter !== 'reply' || c.needs_reply);
  if (selectedCustomerId) await selectCustomer(selectedCustomerId);
  else if (first && window.innerWidth > 960) await selectCustomer(first.id);
}
function filterConversationList(value) { conversationSearch = String(value || ''); renderConversationList(); }
function showConvList() { document.getElementById('conv-layout')?.classList.remove('chat-open', 'context-open'); }
function renderChatMessages(conversations, customer) {
  if (!conversations.length) return `<div class="chat-empty">${uiIcon('message')}<strong>还没有对话记录</strong><p>可以在下方撰写第一条消息。</p></div>`;
  let lastDay = null;
  return conversations.map(m => {
    const day = String(m.sent_at || '').slice(0, 10);
    let html = '';
    if (day && day !== lastDay) { html = `<div class="date-divider"><span>${friendlyDate(day)}</span></div>`; lastDay = day; }
    const status = m.direction === 'outbound' ? deliveryStatusText(m.status) : '';
    const cls = m.status === 'failed' ? 'text-danger' : ['unknown','pending'].includes(m.status) ? 'text-warn' : '';
    return html + `<div class="chat-msg-wrap ${m.direction === 'inbound' ? 'inbound' : 'outbound'}">${m.direction === 'inbound' ? avatarHtml(customer.name, customer.phone, 'sm') : ''}<div class="chat-msg ${m.direction === 'inbound' ? 'inbound' : 'outbound'}"><div class="msg-body">${escapeHtml(m.content)}</div><div class="msg-time"><span>${timeOnly(m.sent_at)}</span>${m.ai_generated ? '<span class="msg-badge">AI</span>' : ''}${status ? `<span class="${cls}">${status}</span>` : ''}</div></div></div>`;
  }).join('');
}
async function selectCustomer(id) {
  if (convPollTimer) { clearInterval(convPollTimer); convPollTimer = null; }
  selectedCustomerId = Number(id);
  const gen = ++convPollGeneration;
  renderConversationList();
  const layout = document.getElementById('conv-layout');
  layout?.classList.add('chat-open');
  const area = document.getElementById('chat-area');
  const context = document.getElementById('customer-context');
  if (!area) return;
  area.innerHTML = `<div class="chat-empty">${insightSkeleton()}<p>正在读取对话…</p></div>`;
  if (context) context.innerHTML = insightSkeleton();
  let d;
  try { d = await get('/customers/' + Number(id)); if (!d.customer) throw new Error('客户不存在'); }
  catch (error) {
    if (gen !== convPollGeneration) return;
    area.innerHTML = `<div class="chat-empty request-error"><strong>对话读取失败</strong><p>${escapeHtml(error.message)}</p><button class="btn btn-outline" onclick="selectCustomer(${Number(id)})">重新加载</button><button class="btn btn-ghost chat-back" onclick="showConvList()">返回客户列表</button></div>`;
    if (context) context.innerHTML = '';
    return;
  }
  if (gen !== convPollGeneration || currentPage !== 'conversations') return;
  const c = d.customer, fs = d.followup_schedule;
  activeConversationCustomer = c;
  area.innerHTML = `<div class="chat-header"><div class="chat-contact"><button class="btn btn-ghost btn-icon chat-back" onclick="showConvList()" aria-label="返回客户列表">${uiIcon('chevronLeft')}</button>${avatarHtml(c.name, c.phone, 'lg')}<div><div class="chat-contact-name">${escapeHtml(c.name || formatPhone(c.phone))} ${badgeStatus(c.status)}</div><div class="chat-contact-meta">${escapeHtml(c.company || '未填写公司')} · ${escapeHtml(formatPhone(c.phone))}</div></div></div>
      <div class="chat-header-actions"><button class="btn btn-outline btn-sm" id="context-toggle" aria-expanded="false" onclick="toggleCustomerContext()">${uiIcon('users')} 客户概览</button></div></div>
    ${fs ? `<div class="conversation-reminder">${uiIcon('calendar')}<span>下次跟进 <strong>${friendlyDate(fs.next_followup_at)} ${timeOnly(fs.next_followup_at)}</strong></span><button onclick="navigate('followups')">查看计划 ${uiIcon('chevronRight')}</button></div>` : ''}
    <div class="chat-sync-state" id="chat-sync-state" role="status"></div>
    <div class="chat-messages" aria-label="最近 50 条对话记录">${renderChatMessages(d.conversations, c)}</div>
    <div class="chat-input-area"><div class="composer-toolbar"><button class="btn btn-ghost btn-sm" id="reply-template-toggle" aria-expanded="false" onclick="toggleReplyTemplates()">${uiIcon('doc')} 快捷话术</button><span>最近 50 条记录</span></div>
      <div id="reply-template-panel" class="reply-template-panel" hidden><div class="template-heading">插入英文草稿，发送前可修改</div>${replyTemplates.map((t, i) => `<button onclick="insertReplyTemplate(${i})"><strong>${t.label}</strong><span>${escapeHtml(t.text)}</span>${uiIcon('plus')}</button>`).join('')}</div>
      <textarea id="manual-msg" aria-label="撰写 WhatsApp 消息" placeholder="输入消息，或从快捷话术开始…" rows="3" oninput="onReplyInput(${Number(id)})" onkeydown="if((event.metaKey||event.ctrlKey)&&event.key==='Enter'){event.preventDefault();sendManual(${Number(id)})}"></textarea>
      <div class="composer-footer"><span id="draft-status" role="status">Ctrl / ⌘ + Enter 发送</span><button class="btn btn-primary" id="manual-send-btn" onclick="sendManual(${Number(id)})">${uiIcon('send')} 发送消息</button></div></div>`;
  document.getElementById('manual-msg').value = readReplyDraft(c);
  onReplyInput(Number(id));
  const messages = area.querySelector('.chat-messages');
  messages.scrollTop = messages.scrollHeight;
  if (context) {
    const tags = parseCustomerTags(c.tags);
    context.innerHTML = `<div class="context-heading"><h3>客户概览</h3><button class="btn btn-ghost btn-icon" onclick="toggleCustomerContext()" aria-label="收起客户概览">${uiIcon('x')}</button></div><div class="context-scroll"><div class="context-profile">${avatarHtml(c.name, c.phone, 'lg')}<strong>${escapeHtml(c.name || formatPhone(c.phone))}</strong><span>${escapeHtml(c.company || '未填写公司')}</span>${tags.length ? `<div class="insight-tags">${tags.map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>` : ''}<button class="btn btn-outline btn-sm" onclick="viewCustomer(${Number(id)},true)">${uiIcon('edit')} 编辑客户资料</button></div><div id="conversation-insights">${insightSkeleton()}</div><section class="insight-section"><h4>客户备注</h4><p class="context-notes">${escapeHtml(c.notes || '还没有备注，可记录产品需求与沟通重点。')}</p></section><div id="context-orders">${insightSkeleton()}</div><button class="btn btn-outline w-full context-create-order" onclick="openOrderForm(null,${Number(id)})">${uiIcon('plus')} 创建关联订单</button></div>`;
    const insightTarget = context.querySelector('#conversation-insights');
    fillCustomerInsights(insightTarget, id, () => gen === convPollGeneration);
    const orderTarget = context.querySelector('#context-orders');
    get(`/customers/${Number(id)}/orders`).then(orders => {
      if (orderTarget.isConnected && gen === convPollGeneration) orderTarget.innerHTML = renderContextOrders(orders);
    }).catch(() => { if (orderTarget.isConnected && gen === convPollGeneration) orderTarget.innerHTML = '<p class="insight-error">关联订单暂时无法读取</p>'; });
  }
  let refreshing = false, ticks = 0;
  convPollTimer = setInterval(async () => {
    if (gen !== convPollGeneration || currentPage !== 'conversations') return;
    if (refreshing) return;
    refreshing = true;
    try {
      await refreshConversationMessages(id, gen);
      if (++ticks % 3 === 0) {
        const list = await get('/customers-with-conversations');
        if (gen === convPollGeneration && Array.isArray(list)) { convList = list; renderConversationList(); }
      }
    } catch (_) {
      const sync = document.getElementById('chat-sync-state');
      if (sync && gen === convPollGeneration) sync.textContent = '刷新暂时失败，保留上次记录与当前草稿。';
    } finally { refreshing = false; }
  }, 5000);
}
async function refreshConversationMessages(id, gen) {
  const latest = await get('/customers/' + Number(id));
  if (gen !== convPollGeneration || currentPage !== 'conversations') return;
  const area = document.querySelector('.chat-messages');
  if (!area) return;
  const atBottom = area.scrollTop + area.clientHeight >= area.scrollHeight - 36;
  const scroll = area.scrollTop;
  area.innerHTML = renderChatMessages(latest.conversations, latest.customer);
  area.scrollTop = atBottom ? area.scrollHeight : scroll;
  document.getElementById('chat-sync-state').textContent = '';
}
async function sendManual(cid) {
  const ta = document.getElementById('manual-msg'), customer = activeConversationCustomer;
  if (!ta || !customer || customer.id !== cid) return;
  const msg = ta.value.trim(), key = replyDraftKey(customer);
  if (!msg || pendingManualSends.has(key)) return;
  pendingManualSends.add(key);
  onReplyInput(cid);
  const gen = convPollGeneration;
  try {
    const r = await post('/send-manual', {phone: customer.phone, message: msg, customer_id: cid});
    if (r.ok || r.status === 'unknown') {
      // Keep any edits made while sending, including after switching customers.
      if (readReplyDraft(customer).trim() === msg) storeReplyDraft(customer, '');
      if (gen === convPollGeneration && ta.isConnected && ta.value.trim() === msg) ta.value = '';
      showToast(r.status === 'unknown' ? '结果待确认，请勿重复发送' : '消息已发送');
      const list = await get('/customers-with-conversations');
      if (gen === convPollGeneration && currentPage === 'conversations') {
        if (Array.isArray(list)) { convList = list; renderConversationList(); }
        await refreshConversationMessages(cid, gen);
      }
    } else { await uiAlert('发送失败：' + (r.error || r.reason || '请检查连接后重试')); }
  } catch (e) {
    // A network failure does not establish whether the platform accepted a send.
    await uiAlert('发送结果无法确认：' + (e.message || '网络错误') + '\n草稿已保留，请先核对对话记录，避免重复发送。');
  } finally {
    pendingManualSends.delete(key);
    if (activeConversationCustomer?.id === cid && currentPage === 'conversations') onReplyInput(cid);
  }
}
