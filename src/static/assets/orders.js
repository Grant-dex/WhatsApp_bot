/* ── Orders ─────────────────────────────────────────────────── */

let ordersPage = 1, ordersSearch = '', ordersStatusFilter = '';

function statusLabel(s) {
  const labels = {pending:'待确认',confirmed:'已确认',processing:'生产中',shipped:'已发货',delivered:'已交付',cancelled:'已取消'};
  const classes = {pending:'badge-orange',confirmed:'badge-blue',processing:'badge-teal',shipped:'badge-blue',delivered:'badge-green',cancelled:'badge-red'};
  return `<span class="badge ${classes[s]||'badge-gray'}">${labels[s]||escapeHtml(s||'—')}</span>`;
}

async function loadOrders(el) {
  const r = await get(`/orders?page=${ordersPage}&search=${encodeURIComponent(ordersSearch)}&status=${ordersStatusFilter}`);
  // The unfiltered count is informational; failure must not hide the order list.
  let totalOrders = r.total;
  if (ordersSearch || ordersStatusFilter) {
    try { totalOrders = (await get('/orders?per_page=1')).total; } catch (_) { totalOrders = null; }
  }
  const pages = Math.ceil(r.total / r.per_page) || 1;
  const rows = r.items.map(o => `
    <tr style="cursor:pointer" onclick="openOrderForm(${o.id})">
      <td><span class="mono" style="font-weight:600;color:var(--teal)">${escapeHtml(ov(o.order_no,'—'))}</span></td>
      <td>
        <div class="person">
          ${avatarHtml(o.customer_name, o.customer_phone, 'sm')}
          <div class="person-main">
            <div class="person-name">${escapeHtml(ov(o.customer_name)||formatPhone(o.customer_phone)||'—')}</div>
            <div class="person-sub">${escapeHtml(o.customer_company||'')}</div>
          </div>
        </div>
      </td>
      <td>${escapeHtml(o.product||'—')}</td>
      <td class="num">${ov(o.quantity,1)}</td>
      <td class="num">${o.total_amount != null ? escapeHtml(ov(o.currency,'USD'))+' '+Number(o.total_amount).toLocaleString() : '—'}</td>
      <td>${statusLabel(o.status)}</td>
      <td class="text-muted">${escapeHtml(o.order_date||'—')}</td>
      <td class="actions">
        <div class="table-actions">
          <button class="btn btn-outline btn-xs order-edit" aria-label="编辑订单" title="编辑订单" onclick="event.stopPropagation();openOrderForm(${o.id})">${uiIcon('edit')}</button>
          <button class="btn btn-danger btn-xs order-delete" aria-label="删除订单" title="删除订单" onclick="event.stopPropagation();deleteOrder(${o.id})">${uiIcon('trash')}</button>
        </div>
      </td>
    </tr>`).join('');

  el.innerHTML = `
    ${pageHeader('订单管理', totalOrders === null ? '全部订单数读取失败 · 当前列表仍可操作' : `全部订单（${totalOrders}）`)}
    <div class="toolbar orders-toolbar">
        <div class="search-field">
          ${uiIcon('search')}
          <input class="input" placeholder="搜索订单号 / 产品 / 客户..." value="${escapeHtml(ordersSearch)}" onchange="ordersSearch=this.value;ordersPage=1;loadPage('orders')">
        </div>
        <select class="input" style="width:150px" onchange="ordersStatusFilter=this.value;ordersPage=1;loadPage('orders')">
          <option value="">全部状态</option>
          <option value="pending" ${ordersStatusFilter==='pending'?'selected':''}>待确认</option>
          <option value="confirmed" ${ordersStatusFilter==='confirmed'?'selected':''}>已确认</option>
          <option value="processing" ${ordersStatusFilter==='processing'?'selected':''}>生产中</option>
          <option value="shipped" ${ordersStatusFilter==='shipped'?'selected':''}>已发货</option>
          <option value="delivered" ${ordersStatusFilter==='delivered'?'selected':''}>已交付</option>
          <option value="cancelled" ${ordersStatusFilter==='cancelled'?'selected':''}>已取消</option>
        </select>
        <button class="btn btn-primary" onclick="openOrderForm()">${uiIcon('plus')} 新建订单</button>
      </div>
    <div class="panel orders-panel">
      <div class="table-wrap">
        <table class="table-wide">
          <thead><tr><th>订单号</th><th>客户</th><th>产品</th><th>数量</th><th>金额</th><th>状态</th><th>下单日期</th><th class="actions">操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="8" class="table-empty"><div class="empty-state"><p>暂无订单</p></div></td></tr>'}</tbody>
        </table>
      </div>
      <div class="pagination">
        <span class="page-info">第 ${r.page} / ${pages} 页 · 共 ${r.total} 条</span>
        <div class="page-buttons">
          <button class="btn btn-outline btn-sm" onclick="ordersPage--;loadPage('orders')" ${ordersPage<=1?'disabled':''}>${uiIcon('chevronLeft')} 上一页</button>
          <button class="btn btn-outline btn-sm" onclick="ordersPage++;loadPage('orders')" ${ordersPage>=pages?'disabled':''}>下一页 ${uiIcon('chevronRight')}</button>
        </div>
      </div>
    </div>`;
}

async function openOrderForm(orderId, presetCustomerId) {
  try { await renderOrderForm(orderId, presetCustomerId); }
  catch (e) { await uiAlert('无法读取订单表单：' + e.message); }
}

async function renderOrderForm(orderId, presetCustomerId) {
  const customers = await get('/customers-with-conversations');
  let order = null;
  if (orderId) {
    const r = await get(`/orders/${orderId}`);
    if (!r.order) throw new Error(r.error || '订单不存在');
    order = r.order;
  }
  const sidebar = document.getElementById('detail-sidebar');
  sidebar.innerHTML = `
    <div class="sidebar-header">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <h4>${order ? '编辑订单' : '新建订单'}</h4>
        <button onclick="closeSidebar()" style="background:none;border:none;color:var(--text3);font-size:20px;cursor:pointer;line-height:1">×</button>
      </div>
      ${order ? `<div class="detail-field"><label>订单号</label><input class="input" id="ord-no" value="${escapeHtml(order.order_no)}" style="width:100%;padding:6px 10px;font-family:'JetBrains Mono',monospace"></div>` : ''}
    </div>
    <div class="sidebar-body">
      <div class="detail-field"><label>客户 *</label>
        <select class="input" id="ord-customer" style="width:100%;padding:6px 10px">
          <option value="">选择客户</option>
          ${customers.map(c => `<option value="${c.id}" ${(order&&order.customer_id===c.id)||(!order&&presetCustomerId===c.id)?'selected':''}>${escapeHtml(c.name||formatPhone(c.phone))}</option>`).join('')}
        </select>
      </div>
      <div class="detail-field"><label>产品/型号</label><input class="input" id="ord-product" value="${escapeHtml(order&&order.product||'')}" style="width:100%;padding:6px 10px"></div>
      <div class="detail-field" style="display:flex;gap:8px">
        <div style="flex:1"><label>数量</label><input class="input" id="ord-qty" type="number" min="1" value="${order&&order.quantity||1}" style="width:100%;padding:6px 10px" oninput="calcTotal()"></div>
        <div style="flex:1"><label>单价</label><input class="input" id="ord-price" type="number" step="0.01" value="${escapeHtml(order?.unit_price ?? '')}" style="width:100%;padding:6px 10px" oninput="calcTotal()"></div>
      </div>
      <div class="detail-field" style="display:flex;gap:8px">
        <div style="flex:2"><label>总金额</label><input class="input" id="ord-total" type="number" step="0.01" value="${escapeHtml(order?.total_amount ?? '')}" style="width:100%;padding:6px 10px"></div>
        <div style="flex:1"><label>币种</label>
          <select class="input" id="ord-currency" style="width:100%;padding:6px 10px">
            ${['USD','EUR','CNY','GBP','JPY','AUD','CAD','CHF','HKD','SGD'].map(c => `<option value="${c}" ${(order&&order.currency===c)||(!order&&c==='USD')?'selected':''}>${c}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="detail-field"><label>状态</label>
        <select class="input" id="ord-status" style="width:100%;padding:6px 10px">
          ${['pending','confirmed','processing','shipped','delivered','cancelled'].map(s => {
            const labels = {pending:'待确认',confirmed:'已确认',processing:'生产中',shipped:'已发货',delivered:'已交付',cancelled:'已取消'};
            return `<option value="${s}" ${order&&order.status===s?'selected':''}>${labels[s]}</option>`;
          }).join('')}
        </select>
      </div>
      <div class="detail-field"><label>下单日期</label><input class="input" id="ord-date" type="date" value="${escapeHtml(order&&order.order_date||todayStr())}" style="width:100%;padding:6px 10px" onchange="checkDeliveryDate()"></div>
      <div class="detail-field"><label>预计交付</label><input class="input" id="ord-delivery" type="date" value="${escapeHtml(order&&order.delivery_date||'')}" style="width:100%;padding:6px 10px" onchange="checkDeliveryDate()"><span id="delivery-hint" style="display:none;font-size:11px;color:var(--red);margin-top:2px">交付日期早于下单日期</span></div>
      <div class="detail-field"><label>备注</label><textarea class="input" id="ord-notes" style="width:100%;padding:6px 10px;min-height:50px;resize:vertical" rows="2">${escapeHtml(order&&order.notes||'')}</textarea></div>
      <div class="detail-actions">
        <button class="btn btn-primary btn-sm w-full" onclick="saveOrder(${order?order.id:'null'},${presetCustomerId||'null'})">${order?'保存修改':'创建订单'}</button>
        <button class="btn btn-outline btn-sm w-full" onclick="closeSidebar()">取消</button>
        ${order ? `<button class="btn btn-danger btn-sm w-full" onclick="deleteOrder(${order.id})">删除订单</button>` : ''}
      </div>
    </div>`;
  sidebar.classList.add('open');
}

async function saveOrder(id, fallbackCid) {
  const button = document.querySelector('.detail-actions .btn-primary');
  if (button && button.disabled) return;
  if (button) button.disabled = true;
  try { await persistOrder(id, fallbackCid); }
  catch (e) { await uiAlert('保存失败：' + e.message); }
  finally { if (button) button.disabled = false; }
}

async function persistOrder(id, fallbackCid) {
  const orderNoEl = document.getElementById('ord-no');
  const data = {
    customer_id: parseInt(document.getElementById('ord-customer').value)||fallbackCid||null,
    product: document.getElementById('ord-product').value.trim(),
    quantity: parseInt(document.getElementById('ord-qty').value)||1,
    unit_price: document.getElementById('ord-price').value === '' ? null : Number(document.getElementById('ord-price').value),
    total_amount: document.getElementById('ord-total').value === '' ? null : Number(document.getElementById('ord-total').value),
    currency: document.getElementById('ord-currency').value,
    status: document.getElementById('ord-status').value,
    order_date: document.getElementById('ord-date').value,
    delivery_date: document.getElementById('ord-delivery').value,
    notes: document.getElementById('ord-notes').value.trim(),
  };
  if (orderNoEl) data.order_no = orderNoEl.value.trim();
  if (!data.customer_id) { uiAlert('请选择客户'); return; }
  const qtyInput = document.getElementById('ord-qty');
  if (!qtyInput.value || !Number.isInteger(Number(qtyInput.value)) || Number(qtyInput.value) < 1) { uiAlert('数量必须是大于零的整数'); return; }
  if (data.unit_price != null && data.unit_price < 0 || data.total_amount != null && data.total_amount < 0) { uiAlert('金额不能为负数'); return; }
  checkDeliveryDate();
  if (data.order_date && data.delivery_date && data.order_date > data.delivery_date) {
    uiAlert('下单日期不能晚于交付日期'); return;
  }
  const url = id ? `/orders/${id}` : '/orders';
  const method = id ? 'put' : 'post';
  const r = await (method==='put' ? put(url, data) : post(url, data));
  if (r.ok) { closeSidebar(); loadPage('orders'); }
  else { uiAlert('保存失败: ' + (r.error||'未知错误')); }
}

function checkDeliveryDate() {
  const orderDate = document.getElementById('ord-date').value;
  const deliveryDate = document.getElementById('ord-delivery').value;
  const hint = document.getElementById('delivery-hint');
  const input = document.getElementById('ord-delivery');
  if (orderDate && deliveryDate && deliveryDate < orderDate) {
    hint.style.display = 'block';
    input.style.borderColor = 'var(--red)';
  } else {
    hint.style.display = 'none';
    input.style.borderColor = '';
  }
}

function calcTotal() {
  const qty = parseFloat(document.getElementById('ord-qty').value) || 0;
  const price = parseFloat(document.getElementById('ord-price').value) || 0;
  const totalEl = document.getElementById('ord-total');
  if (document.getElementById('ord-qty').value && document.getElementById('ord-price').value) totalEl.value = (qty * price).toFixed(2);
}

async function deleteOrder(id) {
  if (!(await uiConfirm('确定删除此订单？'))) return;
  try {
    const r = await del(`/orders/${id}`);
    if (r.ok) { closeSidebar(); loadPage('orders'); }
    else { uiAlert('删除失败：' + (r.error || '未知错误')); }
  } catch (e) { await uiAlert('删除失败：' + e.message); }
}

