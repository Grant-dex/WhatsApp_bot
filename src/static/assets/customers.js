/* ── Customers ─────────────────────────────────────────────── */
let customerPage = 1, customerSearch = '', customerStatus = '', customerDebounceTimer = null;
let customerRequestSequence = 0;
	let customerLayoutInitialized = false;

	function debounceLoadCustomers(el) {
	  clearTimeout(customerDebounceTimer);
	  customerDebounceTimer = setTimeout(() => loadCustomers(el), 300);
	}

	function updateCustomerSearch(val) {
	  customerSearch = val;
	  customerPage = 1;
	  debounceLoadCustomers(document.getElementById('page-customers'));
	}

	function updateCustomerStatus(val) {
	  customerStatus = val;
	  customerPage = 1;
	  loadCustomers(document.getElementById('page-customers'));
	}

	function goCustomerPage(p) {
	  customerPage = p;
	  loadCustomers(document.getElementById('page-customers'));
	}

async function loadCustomers(el) {
  const request = ++customerRequestSequence;
  if (!el) return;
  el.setAttribute('aria-busy', 'true');
  try {
    await renderCustomers(el, request);
  } catch (error) {
    if (request !== customerRequestSequence) return;
    const body = document.getElementById('cust-table-body');
    const message = `<div class="empty-state request-error" role="alert"><p>客户列表读取失败</p><small>${escapeHtml(error.message || String(error))}</small><button class="btn btn-outline btn-sm" onclick="loadCustomers(document.getElementById('page-customers'))">重新加载</button></div>`;
    if (body) body.innerHTML = `<tr><td colspan="8">${message}</td></tr>`;
    else el.innerHTML = pageHeader('客户管理', '客户信息与跟进状态') + message;
  } finally { if (request === customerRequestSequence) el.removeAttribute('aria-busy'); }
}

async function renderCustomers(el, request) {
  const params = new URLSearchParams({page:customerPage,per_page:30,search:customerSearch,status:customerStatus});
  const d = await get('/customers?' + params);
  if (request !== customerRequestSequence) return;
  const rows = d.items.map(r => `
    <tr>
      <td>
        <div class="person">
          ${avatarHtml(r.name, r.phone)}
          <div class="person-main">
            <a class="person-name" href="#" onclick="viewCustomer(${r.id});return false">${escapeHtml((r.name||'').substring(0,30))}</a>
          </div>
        </div>
      </td>
      <td class="mono">${escapeHtml(formatPhone(r.phone))}<button class="copy-btn" data-phone="${escapeHtml(formatPhone(r.phone))}" onclick="event.stopPropagation();copyToClipboard(this.dataset.phone,'号码已复制')" title="复制号码">复制</button></td>
      <td>${escapeHtml((r.company||'—').substring(0,25))}</td>
      <td>${badgeStatus(r.status)}</td>
      <td class="num text-muted">${r.conv_count||0}</td>
      <td class="text-muted">${timeAgo(r.last_msg)}</td>
      <td class="text-muted">${r.next_fu ? friendlyDate(r.next_fu) + ' ' + timeOnly(r.next_fu) : '—'}</td>
      <td class="actions">
        <div class="table-actions">
          <button class="btn btn-outline btn-xs" onclick="event.stopPropagation();viewCustomer(${r.id})">查看</button>
          <button class="btn btn-outline btn-xs" onclick="event.stopPropagation();viewCustomer(${r.id},true)">编辑</button>
          <button class="btn btn-danger btn-xs" data-name="${escapeHtml(r.name||'')}" onclick="event.stopPropagation();deleteCustomer(${Number(r.id)},this.dataset.name)" title="删除客户" aria-label="删除客户">${uiIcon('trash')}</button>
        </div>
      </td>
    </tr>`).join('');

  const pages = Math.ceil(d.total / d.per_page) || 1;

  if (!customerLayoutInitialized || !document.getElementById('cust-header-info')) {
    customerLayoutInitialized = true;
    el.innerHTML = `
      ${pageHeader('客户管理', '客户信息与跟进状态')}
      <div class="panel">
        <div class="toolbar">
          <div class="search-field">
            ${uiIcon('search')}
            <input class="input" id="cust-search-input" placeholder="搜索姓名、电话、公司...">
          </div>
          <select class="input" id="cust-status-select" style="width:150px">
            <option value="">全部状态</option><option value="active">活跃</option><option value="inactive">非活跃</option><option value="blocked">已屏蔽</option><option value="opted_out">已退订</option>
          </select>
          <span class="flex-1"></span>
          
          <button class="btn btn-primary" onclick="importCustomers()">${uiIcon('upload')} 导入 Excel</button>
        </div>
        <div class="table-wrap">
          <table class="table-wide">
            <thead><tr><th>姓名</th><th>电话</th><th>公司</th><th>状态</th><th>消息数</th><th>最近联系</th><th>下次跟进</th><th class="actions">操作</th></tr></thead>
            <tbody id="cust-table-body"></tbody>
          </table>
        </div>
        <div class="pagination">
          <span class="page-info" id="cust-header-info"></span><span class="page-info" id="cust-page-info"></span>
          <div class="page-buttons">
            <button class="btn btn-outline btn-sm" id="cust-prev-btn" onclick="goCustomerPage(customerPage-1)">${uiIcon('chevronLeft')} 上一页</button>
            <button class="btn btn-outline btn-sm" id="cust-next-btn" onclick="goCustomerPage(customerPage+1)">下一页 ${uiIcon('chevronRight')}</button>
          </div>
        </div>
      </div>`;

    document.getElementById('cust-search-input').addEventListener('input', function(e) {
      updateCustomerSearch(e.target.value);
    });
    document.getElementById('cust-status-select').addEventListener('change', function(e) {
      updateCustomerStatus(e.target.value);
    });
  }

  document.getElementById('cust-header-info').textContent = `共 ${d.total} 个客户`;
  document.getElementById('cust-table-body').innerHTML = rows || '<tr><td colspan="8" class="table-empty"><div class="empty-state"><p>没有找到匹配的客户</p></div></td></tr>';
  document.getElementById('cust-page-info').textContent = `第 ${d.page}/${pages} 页`;
  document.getElementById('cust-prev-btn').disabled = customerPage <= 1;
  document.getElementById('cust-next-btn').disabled = customerPage >= pages;
  document.getElementById('cust-search-input').value = customerSearch;
  document.getElementById('cust-status-select').value = customerStatus;
}

async function viewCustomer(id, focusEdit) {
  try { await renderCustomerDetails(id, focusEdit); }
  catch (error) { uiAlert('客户详情读取失败：' + (error.message || String(error))); }
}

async function renderCustomerDetails(id, focusEdit) {
  selectedCustomerId = id;
  const d = await get('/customers/' + id);
  if (selectedCustomerId !== id) return;
  const c = d.customer;
  const fs = d.followup_schedule;
  openSidebar(`
    <div class="sidebar-header">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <h4>${escapeHtml(c.name||formatPhone(c.phone))}</h4>
        <button onclick="closeSidebar()" style="background:none;border:none;color:var(--text3);font-size:20px;cursor:pointer;line-height:1">×</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        ${badgeStatus(c.status)}
        <span style="font-size:12px;color:var(--text3)">${escapeHtml(c.company||'')}</span>
      </div>
    </div>
    <div class="sidebar-body">
    <div class="detail-field"><label>姓名</label><input class="input" id="edit-name" value="${escapeHtml(c.name||'')}" style="width:100%"></div>
    <div class="detail-field"><label>电话 <button class="copy-btn" onclick="copyToClipboard(document.getElementById('edit-phone').value,'号码已复制')" style="opacity:1;font-size:10px">复制</button></label><input class="input" id="edit-phone" value="${escapeHtml(formatPhone(c.phone))}" style="width:100%;padding:6px 10px"></div>
    <div class="detail-field"><label>公司</label><input class="input" id="edit-company" value="${escapeHtml(c.company||'')}" style="width:100%;padding:6px 10px"></div>
    <div class="detail-field"><label>备注</label><textarea class="input" id="edit-notes" style="width:100%;padding:6px 10px;min-height:50px;resize:vertical" rows="2">${escapeHtml(c.notes||'')}</textarea></div>
    <div class="detail-field"><label>标签</label><input class="input" id="edit-tags" value="${escapeHtml((c.tags||'').replace(/^\[\]$/,''))}" style="width:100%;padding:6px 10px"></div>
    <div class="detail-field"><label>创建时间</label><span>${timeShort(c.created_at)}</span></div>
    ${fs ? `<div style="background:var(--teal-bg);border:1px solid var(--teal-light);border-radius:8px;padding:12px;margin-bottom:14px">
      <div style="font-size:10px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">跟进计划</div>
      <div style="display:flex;gap:20px">
        <div><div style="font-size:10px;color:var(--text3);margin-bottom:2px">下次跟进</div><div style="font-size:13px;font-weight:600;color:var(--teal)">${timeShort(fs.next_followup_at)}</div></div>
        <div><div style="font-size:10px;color:var(--text3);margin-bottom:2px">频率</div><div style="font-size:13px;font-weight:600;color:var(--teal)">每 ${fs.frequency_days} 天</div></div>
      </div>
    </div>` : ''}
    <div class="detail-actions">
      <button class="btn btn-primary btn-sm w-full" onclick="saveCustomerEdits(${id})">保存修改</button>
      <button class="btn btn-outline btn-sm w-full" onclick="closeSidebar()">取消</button>
      <button class="btn btn-outline btn-sm w-full" onclick="navigate('conversations');setTimeout(()=>selectCustomer(${id}),200)">查看对话</button>
      <button class="btn btn-danger btn-sm w-full" onclick="toggleCustomerStatus(${id},'${c.status==='active'?'inactive':'active'}',${fs?fs.id:0})">${c.status==='active'?'暂停跟进':'恢复跟进'}</button>
    </div>
    </div>`);

  if (d.conversations.length) {
    const msgs = d.conversations.slice(-5).map(m => `
      <div style="margin-bottom:10px;padding:8px 10px;background:${m.direction==='inbound'?'var(--gray-bg)':'var(--teal-bg)'};border-radius:8px;border-left:3px solid ${m.direction==='inbound'?'var(--border)':'var(--teal)'}">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px">
          <span style="font-size:10px;font-weight:600;color:${m.direction==='inbound'?'var(--text2)':'var(--teal)'}">${m.direction==='inbound'?'客户':'发出'}</span>
          <span style="font-size:10px;color:var(--text3)">${timeShort(m.sent_at)}</span>
        </div>
        <div style="font-size:12px;color:var(--text);line-height:1.4">${escapeHtml((m.content||'').substring(0,80))}${(m.content||'').length>80?'…':''}</div>
      </div>`).join('');
    document.querySelector('.detail-actions').insertAdjacentHTML('beforebegin',
      `<div class="detail-field mt-md"><label>最近消息</label><div style="margin-top:6px">${msgs}</div></div>`);
  }

  // Load customer orders
  try {
    const orders = await get(`/customers/${id}/orders`);
    if (selectedCustomerId !== id || !document.querySelector('.detail-actions')) return;
    if (orders.length) {
      const ordersHtml = orders.map(o => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border-light);font-size:12px">
          <div>
            <span style="font-family:'JetBrains Mono',monospace;font-weight:600;font-size:11px">${escapeHtml(ov(o.order_no,'—'))}</span>
            <span style="margin-left:8px">${escapeHtml(ov(o.product,'—'))}</span>
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            ${statusLabel(o.status)}
            <span style="color:var(--text3);font-size:11px">${o.total_amount?escapeHtml(ov(o.currency,'USD'))+' '+Number(o.total_amount).toLocaleString():''}</span>
          </div>
        </div>`).join('');
      const ordersSection = `<div style="margin-top:12px"><div style="font-size:10px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">关联订单 (${orders.length})</div>${ordersHtml}</div>`;
      document.querySelector('.detail-actions').insertAdjacentHTML('beforebegin', ordersSection);
    }
  } catch(e) {
    document.querySelector('.detail-actions')?.insertAdjacentHTML('beforebegin', '<div class="detail-field request-error" role="alert">关联订单暂时无法读取</div>');
  }

  // Add create order button
  const createOrderBtn = `<button class="btn btn-outline btn-sm w-full" onclick="closeSidebar();navigate('orders');setTimeout(()=>openOrderForm(null,${id}),300)" style="margin-top:6px">+ 创建订单</button>`;
  document.querySelector('.detail-actions').insertAdjacentHTML('beforeend', createOrderBtn);
  if (focusEdit) setTimeout(() => { const input = document.getElementById('edit-company'); if (input) input.focus(); }, 60);
}

async function toggleCustomerStatus(id, newStatus, scheduleId) {
  try { await applyCustomerStatus(id, newStatus, scheduleId); }
  catch (error) { uiAlert('更新客户状态失败：' + (error.message || String(error))); }
}

async function applyCustomerStatus(id, newStatus, scheduleId) {
	  await post(`/customers/${id}/status`, {status: newStatus});
	  // Also toggle follow-up schedule so the scheduler respects this change
	  if (scheduleId) {
	    await post(`/followups/${scheduleId}/toggle`, {});
	  }
	  closeSidebar();
	  if (currentPage === 'customers') loadPage('customers');
	  else if (currentPage === 'conversations') loadPage('conversations');
	}

async function saveCustomerEdits(id) {
  const name = document.getElementById('edit-name')?.value?.trim() || '';
  const phone = document.getElementById('edit-phone')?.value?.trim() || '';
  const company = document.getElementById('edit-company')?.value?.trim() || '';
  const notes = document.getElementById('edit-notes')?.value?.trim() || '';
  const tags = document.getElementById('edit-tags')?.value?.trim() || '';
  try {
    const r = await post(`/customers/${id}/status`, {name, phone, company, notes, tags});
    if (r.ok) {
      closeSidebar();
      if (currentPage === 'customers') loadPage('customers');
      else if (currentPage === 'conversations') loadPage('conversations');
    } else {
      uiAlert('保存失败：' + (r.error || '未知错误'));
    }
  } catch(e) {
    uiAlert('保存失败: ' + (e.message || '网络错误，请检查后端是否正常运行'));
  }
}

