/* ── Follow-ups ────────────────────────────────────────────── */

/* ── Batch Push State ───────────────────────────────────── */
let batchPushState = {
  running: false,
  queue: [],
  currentIndex: -1,
  intervalMinutes: 3,
  timer: null,
  results: [],
  startedAt: null,
  selectedIds: null, // null = all selected, Set = specific selected
  overrides: []      // explicit overrides confirmed by the user
};

function resetBatchState() {
  if (batchPushState.timer) { clearTimeout(batchPushState.timer); batchPushState.timer = null; }
  batchPushState = {
    running: false,
    queue: [],
    currentIndex: -1,
    intervalMinutes: batchPushState.intervalMinutes,
    timer: null,
    results: [],
    startedAt: null,
    selectedIds: null,
    overrides: []
  };
}

function getBatchSelectedIds() {
  const all = document.querySelectorAll('.batch-cust-check');
  if (all.length === 0) return null;
  // Zero selected is an explicit empty selection, not "all".
  return new Set(Array.from(document.querySelectorAll('.batch-cust-check:checked')).map(c => parseInt(c.dataset.sid)));
}

function toggleSelectAllBatch(checked) {
  document.querySelectorAll('.batch-cust-check').forEach(c => { c.checked = checked; });
}

async function startBatchPush() {
  if (batchPushState.running) return;

  // Get the latest due followups
  let dueRes;
  try {
    dueRes = await get('/followups?filter_type=due');
  } catch(e) {
    uiAlert('读取待跟进客户失败：' + (e.message || '网络错误'));
    return;
  }
  if (!dueRes.items || !dueRes.items.length) {
    uiAlert('没有待跟进的客户');
    return;
  }

  const selectedIds = getBatchSelectedIds();
  const queue = selectedIds
    ? dueRes.items.filter(f => selectedIds.has(f.id))
    : dueRes.items;

  if (queue.length === 0) {
    uiAlert('请至少选择一个客户');
    return;
  }

  if (!(await uiConfirm(`确定要开始批量推送吗？\n\n将依次向 ${queue.length} 个客户发送跟进消息，每条间隔 ${batchPushState.intervalMinutes} 分钟。\n\n期间请勿关闭此页面。`))) return;

  // The server marks "manual batch started today" only after confirmation,
  // a non-empty eligible queue and all non-overridable checks have passed.
  // Cancelling above never calls this endpoint.
  let start;
  try {
    start = await post('/followups/batch/start', {
      confirmed: true,
      schedule_ids: queue.map(f => f.id),
      overrides: []
    });
    if (!start.ok && start.overridable_reasons && start.overridable_reasons.length) {
      const labels = start.overridable_reasons.map(autoBatchReasonLabel).join('、');
      if (!(await uiConfirm(`以下限制会阻止自动跟进：${labels}\n\n是否以人工批量方式显式绕过这些限制继续发送？\n（每日配额、暂停状态、客户联系状态不能被绕过）`))) return;
      start = await post('/followups/batch/start', {
        confirmed: true,
        schedule_ids: queue.map(f => f.id),
        overrides: start.overridable_reasons
      });
    }
  } catch(e) {
    uiAlert('无法开始批量推送: ' + (e.message || '网络错误'));
    return;
  }
  if (!start.ok) {
    uiAlert('无法开始批量推送: ' + (start.error || start.reason || '未知错误'));
    return;
  }

  batchPushState.running = true;
  const panel = document.getElementById('batch-push-panel');
  if (panel) panel.style.display = 'block';
  batchPushState.queue = queue;
  batchPushState.currentIndex = -1;
  batchPushState.results = [];
  batchPushState.startedAt = Date.now();
  batchPushState.selectedIds = selectedIds;
  batchPushState.overrides = start.overrides_applied || [];

  updateBatchPushUI();
  processNextBatchItem();
}

async function stopBatchPush() {
  if (!batchPushState.running) return;
  if (!(await uiConfirm('确定要停止批量推送吗？已发送的消息不受影响，剩余未发的客户将保持待跟进状态。'))) return;

  if (batchPushState.timer) { clearTimeout(batchPushState.timer); batchPushState.timer = null; }
  const remaining = batchPushState.queue.length - batchPushState.currentIndex - 1;
  batchPushState.running = false;
  updateBatchPushUI();
  uiAlert(`批量推送已停止。\n已完成: ${batchPushState.currentIndex + 1} 个\n剩余未发: ${Math.max(0, remaining)} 个`);
  loadPage('followups');
}

async function processNextBatchItem() {
  if (!batchPushState.running) return;

  batchPushState.currentIndex++;

  if (batchPushState.currentIndex >= batchPushState.queue.length) {
    // All done!
    batchPushState.running = false;
    if (batchPushState.timer) { clearTimeout(batchPushState.timer); batchPushState.timer = null; }
    updateBatchPushUI();
    const success = batchPushState.results.filter(r => r.status === 'sent').length;
    const failed = batchPushState.results.filter(r => r.status === 'failed').length;
    const unknown = batchPushState.results.filter(r => r.status === 'unknown').length;
    const blocked = batchPushState.results.filter(r => r.status === 'blocked').length;
    const totalTime = Math.round((Date.now() - batchPushState.startedAt) / 60000);
    uiAlert(`批量推送完成！\n\n总耗时: ${totalTime} 分钟\n成功: ${success} 个\n结果待确认: ${unknown} 个\n失败: ${failed} 个\n被规则阻止: ${blocked} 个`);
    loadPage('followups');
    return;
  }

  const item = batchPushState.queue[batchPushState.currentIndex];
  updateBatchPushUI();

  try {
    const r = await post(`/followups/${item.id}/send-now`, {
      overrides: batchPushState.overrides || []
    });
    const status = r.status === 'sent' ? 'sent'
      : r.status === 'unknown' ? 'unknown'
      : r.status === 'blocked' ? 'blocked' : 'failed';
    batchPushState.results.push({
      id: item.id,
      name: item.name || '',
      phone: item.phone || '',
      status,
      reason: r.reason || '',
      error: r.error || ''
    });
    // Pause/quota/switch changes stop the rest of the batch; the next item must
    // not be sent. Backend send-now rechecks each item anyway.
    if (status === 'blocked' && ['bot_paused','proactive_disabled','quota_exceeded','quiet_hours'].includes(r.reason)) {
      batchPushState.running = false;
      if (batchPushState.timer) { clearTimeout(batchPushState.timer); batchPushState.timer = null; }
      updateBatchPushUI();
      uiAlert(`批量推送已停止：${autoBatchReasonLabel(r.reason)}\n\n已处理 ${batchPushState.results.length} 个，剩余 ${Math.max(0, batchPushState.queue.length - batchPushState.currentIndex - 1)} 个未发送。`);
      loadPage('followups');
      return;
    }
  } catch (e) {
    batchPushState.results.push({
      id: item.id,
      name: item.name || '',
      phone: item.phone || '',
      status: 'failed',
      error: e.message || '网络错误'
    });
  }

  updateBatchPushUI();

  // Schedule next send
  if (batchPushState.running && batchPushState.currentIndex < batchPushState.queue.length - 1) {
    const delayMs = batchPushState.intervalMinutes * 60 * 1000;
    batchPushState.timer = setTimeout(() => processNextBatchItem(), delayMs);
  } else if (batchPushState.currentIndex >= batchPushState.queue.length - 1) {
    // Last item just completed, process next tick to finish
    batchPushState.timer = setTimeout(() => processNextBatchItem(), 500);
  }
}

function updateBatchPushUI() {
  const panel = document.getElementById('batch-push-panel');
  if (!panel) return;

  const q = batchPushState.queue;
  const idx = batchPushState.currentIndex;
  const running = batchPushState.running;

  panel.className = 'batch-push-panel' + (running ? ' running' : '');

  // Update button states
  const startBtn = document.getElementById('batch-start-btn');
  const stopBtn = document.getElementById('batch-stop-btn');
  if (startBtn) {
    startBtn.disabled = running;
    startBtn.innerHTML = running ? '推送中...' : '批量推送';
  }
  if (stopBtn) {
    stopBtn.disabled = !running;
    stopBtn.style.display = running ? '' : 'none';
  }

  // Update interval select
  const intervalSel = document.getElementById('batch-interval');
  if (intervalSel) intervalSel.disabled = running;

  // Update customer checkboxes
  if (running) {
    document.querySelectorAll('.batch-cust-check').forEach(c => { c.disabled = true; });
  }

  // Mark sent/sending/failed items
  const resultsMap = {};
  batchPushState.results.forEach(r => { resultsMap[r.id] = r; });

  document.querySelectorAll('.batch-customer-item').forEach(el => {
    const sid = parseInt(el.dataset.sid);
    el.classList.remove('sent', 'sending', 'failed', 'unknown', 'blocked');
    if (resultsMap[sid]) {
      const st = resultsMap[sid].status;
      el.classList.add(st === 'sent' ? 'sent' : st === 'unknown' ? 'unknown'
        : st === 'blocked' ? 'blocked' : 'failed');
      const statusEl = el.querySelector('.cust-status');
      if (statusEl) {
        const labels = {sent:'已发送', unknown:'结果待确认', blocked:'被规则阻止', failed:'失败'};
        const colors = {sent:'var(--green)', unknown:'var(--orange)', blocked:'var(--text3)', failed:'var(--red)'};
        statusEl.textContent = labels[st] || '失败';
        statusEl.style.color = colors[st] || 'var(--red)';
      }
    } else if (running && idx >= 0 && q[idx] && q[idx].id === sid) {
      el.classList.add('sending');
      const statusEl = el.querySelector('.cust-status');
      if (statusEl) { statusEl.textContent = '发送中...'; statusEl.style.color = 'var(--teal)'; }
    }
  });

  // Update progress bar
  const progressBar = document.getElementById('batch-progress-bar');
  const progressFill = document.getElementById('batch-progress-fill');
  if (progressBar && progressFill) {
    progressBar.classList.toggle('show', running || batchPushState.results.length > 0);
    const pct = q.length > 0 ? ((idx + 1) / q.length * 100) : 0;
    progressFill.style.width = Math.min(100, Math.max(0, pct)) + '%';
  }

  // Update status display
  const statusDiv = document.getElementById('batch-push-status');
  if (statusDiv) {
    statusDiv.classList.toggle('show', running || batchPushState.results.length > 0);
    if (running || batchPushState.results.length > 0) {
      const done = batchPushState.results.length;
      const total = q.length;
      const currentItem = running && idx >= 0 && idx < q.length ? q[idx] : null;
      const nextSendIn = running && batchPushState.timer
        ? Math.round(batchPushState.intervalMinutes * 60 - ((Date.now() - (batchPushState.startedAt + idx * batchPushState.intervalMinutes * 60000)) / 1000))
        : 0;

      statusDiv.innerHTML = `
        <div class="batch-status-grid">
          <div class="batch-stat">
            <div class="stat-num" style="color:var(--teal)">${done}</div>
            <div class="stat-label">已完成</div>
          </div>
          <div class="batch-stat">
            <div class="stat-num" style="color:var(--text)">${total}</div>
            <div class="stat-label">总计</div>
          </div>
          <div class="batch-stat">
            <div class="stat-num" style="color:var(--orange)">${total - done}</div>
            <div class="stat-label">剩余</div>
          </div>
          ${batchPushState.results.filter(r => r.status === 'failed').length > 0 ? `
          <div class="batch-stat">
            <div class="stat-num" style="color:var(--red)">${batchPushState.results.filter(r => r.status === 'failed').length}</div>
            <div class="stat-label">失败</div>
          </div>` : ''}
          ${batchPushState.results.filter(r => r.status === 'unknown').length > 0 ? `
          <div class="batch-stat">
            <div class="stat-num" style="color:var(--orange)">${batchPushState.results.filter(r => r.status === 'unknown').length}</div>
            <div class="stat-label">结果待确认</div>
          </div>` : ''}
        </div>
        ${currentItem ? `
        <div class="batch-next-info">
          正在发送: <strong>${escapeHtml(currentItem.name || formatPhone(currentItem.phone))}</strong>
          ${running && idx < total - 1 ? ` · 下一封将在 <strong>${batchPushState.intervalMinutes} 分钟</strong>后发送` : ''}
          ${!running ? ' · 所有消息已处理完毕' : ''}
        </div>` : (!running && done > 0 ? `
        <div class="batch-next-info" style="color:var(--green);font-weight:600">全部消息已处理完毕</div>` : '')}
      `;
    }
  }
}

function updateBatchInterval(val) {
  batchPushState.intervalMinutes = parseInt(val) || 3;
}

function toggleBatchPanel() {
  const panel = document.getElementById('batch-push-panel');
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' || !panel.style.display ? 'block' : 'none';
}

/* ── Batch Customer Management ─────────────────────── */
async function removeCustomerFromBatch(scheduleId) {
  if (!(await uiConfirm('确定移除此客户？将从跟进计划中暂停该客户。'))) return;
  try {
    const r = await post(`/followups/${scheduleId}/remove-from-batch`, {});
    if (!r.ok) throw new Error(r.error || '服务器未确认更新');
    showToast('已移除');
    loadPage('followups');
  } catch(e) {
    uiAlert('移除失败: ' + (e.message || '网络错误'));
  }
}

async function addCustomerToBatch() {
  try {
    await _addCustomerToBatch();
  } catch (e) {
    uiAlert('加载可添加客户失败: ' + (e.message || '网络错误'));
  }
}

async function _addCustomerToBatch() {
  // Fetch all active customers not already in the batch
  const dueRes = await get('/followups?filter_type=due');
  const existingIds = new Set((dueRes.items || []).map(f => f.customer_id));
  const allCust = await get('/customers?per_page=100');
  const eligible = (allCust.items || []).filter(c => c.status === 'active' && !existingIds.has(c.id));
  if (eligible.length === 0) {
    uiAlert('没有可添加的客户（所有活跃客户已在跟进计划中）');
    return;
  }
  // Show a simple prompt with customer list
  let list = '选择要添加到批量推送的客户：\n\n';
  eligible.slice(0, 20).forEach((c, i) => {
    list += `${i + 1}. ${c.name || formatPhone(c.phone)} (${formatPhone(c.phone)})\n`;
  });
  if (eligible.length > 20) list += `... 共 ${eligible.length} 个\n`;
  const idx = await uiPrompt(list + '\n输入序号添加（多个用逗号分隔）：');
  if (!idx) return;
  const indices = idx.split(',').map(s => parseInt(s.trim()) - 1).filter(i => i >= 0 && i < eligible.length);
  if (indices.length === 0) return;
  let added = 0;
  for (const i of indices) {
    const r = await post('/followups/add-to-batch', {customer_id: eligible[i].id});
    if (r.ok) added++;
  }
  showToast(`已添加 ${added} 个客户到批次`);
  loadPage('followups');
}

// Backend-persisted source of truth. localStorage is only read once to migrate
// the old preference; it is never used to decide whether automation runs.
let proactiveFollowupsEnabled = false;
let proactiveFollowupsKnown = false;

function autoBatchReasonLabel(code) {
  const labels = {
    proactive_disabled: '主动自动跟进开关已关闭',
    quiet_hours: '当前处于静默时段',
    not_due: '跟进计划尚未到期',
    bot_paused: '机器人已暂停',
    quota_exceeded: '今日主动跟进配额已用完',
    schedule_inactive: '跟进计划已停用',
    customer_opted_out: '客户已退订',
    customer_blocked: '客户已拉黑',
    customer_inactive: '客户已标记为不活跃',
    no_phone: '客户缺少电话号码'
  };
  return labels[code] || code;
}

async function loadProactiveFollowupSetting() {
  try {
    let s = await get('/settings/proactive-followups');
    if (!s || typeof s.enabled !== 'boolean') throw new Error('无法读取主动自动跟进设置');
    if (!s.configured) {
      // One-time upgrade path from the old localStorage-only switch. The
      // backend default remains OFF, which matches the old unchecked default.
      const legacy = localStorage.getItem('autoBatchEnabled');
      if (legacy !== null) {
        const migrated = await put('/settings/proactive-followups', {enabled: legacy === '1'});
        if (!migrated || !migrated.ok) throw new Error('旧设置迁移失败');
        s = migrated;
        localStorage.removeItem('autoBatchEnabled');
      }
    }
    proactiveFollowupsEnabled = !!s.enabled;
    proactiveFollowupsKnown = true;
    const toggle = document.getElementById('auto-batch-toggle');
    if (toggle) toggle.checked = proactiveFollowupsEnabled;
    updateAutoBatchInfo();
    return s;
  } catch(e) {
    proactiveFollowupsKnown = false;
    const toggle = document.getElementById('auto-batch-toggle');
    if (toggle) toggle.checked = proactiveFollowupsEnabled;
    updateAutoBatchInfo();
    return null;
  }
}

async function toggleAutoBatch(enabled) {
  const toggle = document.getElementById('auto-batch-toggle');
  const previous = proactiveFollowupsEnabled;
  if (toggle) toggle.disabled = true;
  try {
    const r = await put('/settings/proactive-followups', {enabled: !!enabled});
    if (!r || !r.ok) throw new Error((r && r.error) || '保存失败');
    proactiveFollowupsEnabled = !!r.enabled;
    proactiveFollowupsKnown = true;
    if (toggle) toggle.checked = proactiveFollowupsEnabled;
    showToast(proactiveFollowupsEnabled ? '已开启主动自动跟进' : '已关闭主动自动跟进');
  } catch(e) {
    // Revert to the last server-confirmed value; never leave the UI claiming a
    // state the backend does not have.
    proactiveFollowupsEnabled = previous;
    if (toggle) toggle.checked = previous;
    uiAlert('保存失败，已恢复服务器状态: ' + (e.message || '网络错误'));
  } finally {
    if (toggle) toggle.disabled = false;
    updateAutoBatchInfo();
  }
}

function updateAutoBatchInfo() {
  const info = document.getElementById('auto-batch-info');
  const toggle = document.getElementById('auto-batch-toggle');
  const badge = document.getElementById('auto-batch-status');
  if (toggle) toggle.checked = proactiveFollowupsEnabled;
  if (badge) {
    badge.className = 'badge ' + (!proactiveFollowupsKnown ? 'badge-gray' : proactiveFollowupsEnabled ? 'badge-green' : 'badge-gray');
    badge.textContent = !proactiveFollowupsKnown ? '状态未知' : proactiveFollowupsEnabled ? '已开启' : '已关闭';
  }
  if (info) {
    info.textContent = !proactiveFollowupsKnown
      ? '无法读取服务器设置，请检查后端连接或刷新页面'
      : proactiveFollowupsEnabled
        ? '已开启：每 5 分钟到期检查与每日 10:00 批次会自动发送；客户即时回复不受此开关影响'
        : '已关闭：两个定时入口都不会自动发送；手动批量可在确认后显式绕过，客户即时回复不受影响';
  }
}

let followupView = 'due';
function selectFollowupView(view) {
  if (batchPushState.running) return;
  followupView = view === 'paused' ? 'paused' : 'due';
  loadPage('followups');
}
function followupModuleError(result, label) {
  if (result.status === 'fulfilled') return '';
  return `<div class="followup-module-error" role="status">${escapeHtml(label)}读取失败：${escapeHtml(result.reason?.message || '网络错误')}。请手动刷新。</div>`;
}

async function loadFollowups(el) {
  // A history-module failure must not erase a usable schedule list, or turn
  // missing history into a healthy zero. Never retry sending as a side effect.
  const modules = await Promise.allSettled([
    get('/followups?filter_type=due'),
    get('/followups?filter_type=today_sent'),
    get('/followups?filter_type=failed'),
    get('/followups?filter_type=unknown'),
    get('/followups?filter_type=paused'),
  ]);
  if (modules[0].status === 'rejected') throw modules[0].reason;
  const [dueRes, sentRes, failedRes, unknownRes, pausedRes] = modules.map(r => r.status === 'fulfilled' ? r.value : {items: []});
  const issueItems = [...failedRes.items, ...unknownRes.items]
    .sort((a, b) => String(b.sent_at || '').localeCompare(String(a.sent_at || '')));
  const dueCount = dueRes.items.length;
  const overdueCount = dueRes.items.filter(f => f.next_followup_at && new Date(f.next_followup_at) < new Date()).length;
  const running = batchPushState.running;

  const visibleSchedules = followupView === 'paused' ? pausedRes.items : dueRes.items;
  const dueRows = visibleSchedules.map(f => {
    const overdue = f.next_followup_at && new Date(f.next_followup_at) < new Date();
    return `<tr>
      <td>
        <div class="person">
          ${avatarHtml(f.name, f.phone, 'sm')}
          <div class="person-main">
            <a class="person-name" href="#" onclick="viewCustomer(${Number(f.customer_id)});return false">${escapeHtml((f.name||'').substring(0,28))}</a>
            <div class="person-sub">${escapeHtml(f.company||'')}</div>
          </div>
        </div>
      </td>
      <td class="mono">${escapeHtml(formatPhone(f.phone))}</td>
      <td class="text-muted">${friendlyDate(f.next_followup_at)} ${timeOnly(f.next_followup_at)}</td>
      <td class="text-muted">${f.frequency_days ? '每 ' + escapeHtml(String(f.frequency_days)) + ' 天' : '—'}</td>
      <td>${followupView === 'paused' ? '<span class="badge badge-gray">已暂停</span>' : overdue ? '<span class="badge badge-orange">已逾期</span>' : '<span class="badge badge-gray">待跟进</span>'}</td>
      <td class="actions">
        <div class="table-actions">
          ${followupView !== 'paused' ? `<button class="btn btn-primary btn-xs" onclick="event.stopPropagation();sendFollowupNow(${Number(f.id)})">立即发送</button>` : ''}
          <button class="btn btn-outline btn-xs" onclick="toggleFollowup(${Number(f.id)})">${followupView === 'paused' ? '恢复跟进' : '暂停'}</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  const sentRows = sentRes.items.map(f => `
    <tr>
      <td><div class="person">${avatarHtml(f.name, f.phone, 'sm')}<div class="person-main"><div class="person-name">${escapeHtml((f.name||'').substring(0,28))}</div></div></div></td>
      <td class="mono">${escapeHtml(formatPhone(f.phone))}</td>
      <td class="text-muted" style="white-space:nowrap">${timeShort(f.sent_at)}</td>
      <td>${badgeSent(f.status)}</td>
    </tr>`).join('');

  const issueRows = issueItems.map(f => `
    <tr>
      <td><div class="person">${avatarHtml(f.name, f.phone, 'sm')}<div class="person-main"><div class="person-name">${escapeHtml((f.name||'').substring(0,28))}</div><div class="person-sub">${escapeHtml(formatPhone(f.phone))}</div></div></div></td>
      <td>${badgeSent(f.status)}</td>
      <td class="text-muted" style="max-width:260px">${escapeHtml((f.error_message||'—').substring(0,70))}</td>
      <td class="text-muted" style="white-space:nowrap">${timeShort(f.sent_at)}</td>
    </tr>`).join('');

  const batchCustomerListHtml = dueRes.items.map(f => `
    <div class="batch-customer-item" data-sid="${f.id}">
      <input type="checkbox" class="batch-cust-check" data-sid="${f.id}" ${running ? 'disabled' : ''} checked>
      <span class="cust-name">${escapeHtml((f.name||'').substring(0,25))}</span>
      <span style="font-family:var(--mono);font-size:11px;color:var(--text3)">${escapeHtml(formatPhone(f.phone))}</span>
      <span class="cust-status" style="font-size:11px;color:var(--text3)"></span>
      <button class="btn btn-ghost btn-xs" style="color:var(--red);margin-left:auto" onclick="event.stopPropagation();removeCustomerFromBatch(${f.id})" title="移除此客户" ${running ? 'disabled' : ''}>移除</button>
    </div>`).join('');

  el.innerHTML = `
    ${pageHeader('跟进管理', '定时跟进管理 · 批量推送')}

    <div class="panel followup-automation">
      <div class="followup-automation-main">
        <div class="followup-automation-title">
          <h3>主动自动跟进</h3>
          <label class="switch" title="主动自动跟进开关">
            <input type="checkbox" aria-label="主动自动跟进" id="auto-batch-toggle" onchange="toggleAutoBatch(this.checked)" ${running ? 'disabled' : ''}>
            <span class="slider"></span>
          </label>
          <span class="badge" id="auto-batch-status">读取中</span>
        </div>
        <div class="text-muted followup-automation-frequency">每 5 分钟检查 · 每日 10:00 批次</div>
      </div>
      <div class="text-muted" id="auto-batch-info" aria-live="polite">正在读取自动跟进设置…</div>
    </div>

    <div class="batch-summary">
      <div>
        <div class="batch-summary-title"><strong>${dueCount}</strong> 个客户待跟进${overdueCount ? `<span class="overdue">· ${overdueCount} 个已逾期</span>` : ''}</div>
        <div class="batch-summary-sub">${dueCount ? '批量发送前需确认；结果待确认不会自动重发。' : '暂无到期跟进任务。'}</div>
      </div>
      <div class="batch-summary-actions">
        <button class="btn btn-outline" onclick="addCustomerToBatch()" ${running ? 'disabled' : ''}>${uiIcon('plus')} 添加客户</button>
        ${dueCount ? `<button class="btn btn-outline" onclick="toggleBatchPanel()">批量设置</button>
        <button class="btn btn-primary" id="batch-start-btn" onclick="startBatchPush()" ${running ? 'disabled' : ''}>${uiIcon('send')} ${running ? '推送中...' : '批量推送'}</button>
        <button class="btn btn-danger" id="batch-stop-btn" onclick="stopBatchPush()" style="display:${running?'':'none'}">停止推送</button>` : ''}
      </div>
    </div>

    ${dueCount ? `
    <div class="batch-push-panel${running ? ' running' : ''}" id="batch-push-panel" style="display:${running?'block':'none'}">
      <div class="batch-push-header">
        <h3>批量推送设置</h3>
        <span class="text-muted text-xs">按选中客户顺序发送，每条之间等待设定间隔</span>
      </div>
      <div class="batch-push-controls">
        <div class="batch-interval-group">
          <label>发送间隔</label>
          <select id="batch-interval" onchange="updateBatchInterval(this.value)" ${running ? 'disabled' : ''}>
            <option value="1" ${batchPushState.intervalMinutes===1?'selected':''}>1 分钟</option>
            <option value="2" ${batchPushState.intervalMinutes===2?'selected':''}>2 分钟</option>
            <option value="3" ${batchPushState.intervalMinutes===3?'selected':''}>3 分钟</option>
            <option value="5" ${batchPushState.intervalMinutes===5?'selected':''}>5 分钟</option>
            <option value="10" ${batchPushState.intervalMinutes===10?'selected':''}>10 分钟</option>
          </select>
        </div>
        <button class="btn btn-outline btn-xs" onclick="toggleSelectAllBatch(true)" id="batch-select-all">全选</button>
        <button class="btn btn-outline btn-xs" onclick="toggleSelectAllBatch(false)" id="batch-deselect-all">取消全选</button>
      </div>
      <div class="batch-customer-list show" id="batch-customer-list">${batchCustomerListHtml}</div>
      <div class="batch-progress-bar" id="batch-progress-bar"><div class="batch-progress-fill" id="batch-progress-fill" style="width:0%"></div></div>
      <div class="batch-push-status" id="batch-push-status"></div>
    </div>` : ''}

    <div class="panel followup-schedules">
      <div class="followup-tabs" role="tablist" aria-label="跟进计划状态">
        <button class="followup-tab ${followupView === 'due' ? 'active' : ''}" role="tab" aria-selected="${followupView === 'due'}" onclick="selectFollowupView('due')" ${running ? 'disabled' : ''}>待跟进 <span>(${dueCount})</span></button>
        <button class="followup-tab ${followupView === 'paused' ? 'active' : ''}" role="tab" aria-selected="${followupView === 'paused'}" onclick="selectFollowupView('paused')" ${running ? 'disabled' : ''}>已暂停 <span>(${modules[4].status === 'fulfilled' ? pausedRes.items.length : '—'})</span></button>
      </div>
      ${followupView === 'paused' ? followupModuleError(modules[4], '已暂停计划') : ''}
      <div class="table-wrap">
        <table class="table-wide">
          <thead><tr><th>客户</th><th>电话</th><th>计划时间</th><th>频率</th><th>状态</th><th class="actions">操作</th></tr></thead>
          <tbody>${dueRows || `<tr><td colspan="6" class="table-empty"><div class="empty-state"><p>${followupView === 'paused' ? (modules[4].status === 'fulfilled' ? '暂无已暂停计划' : '无法读取已暂停计划') : '暂无到期跟进客户'}</p></div></td></tr>`}</tbody>
        </table>
      </div>
    </div>

    <div class="followup-lower">
      <div class="panel">
        <div class="panel-header"><h3>今日已发送</h3><span class="panel-meta">${modules[1].status === 'fulfilled' ? sentRes.items.length : '—'} 条</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>客户</th><th>电话</th><th>发送时间</th><th>状态</th></tr></thead>
            <tbody>${sentRows || `<tr><td colspan="4" class="table-empty"><div class="empty-state"><p>${modules[1].status === 'fulfilled' ? '今日暂无已发送记录' : '发送记录读取失败'}</p></div></td></tr>`}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><h3>发送异常 / 结果待确认</h3><span class="panel-meta">${modules[2].status === 'fulfilled' && modules[3].status === 'fulfilled' ? issueItems.length : '部分数据'}</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>客户</th><th>结果</th><th>错误信息</th><th>时间</th></tr></thead>
            <tbody>${issueRows || `<tr><td colspan="4" class="table-empty"><div class="empty-state"><p>${modules[2].status === 'fulfilled' && modules[3].status === 'fulfilled' ? '暂无发送异常' : '异常记录未能完整加载'}</p></div></td></tr>`}</tbody>
          </table>
        </div>
        ${followupModuleError(modules[2], '失败记录')}${followupModuleError(modules[3], '待确认记录')}
        <div class="panel-note">结果“待确认”表示消息可能已送达，系统不会自动重试；批量发送前需再次确认。</div>
      </div>
    </div>`;

  await loadProactiveFollowupSetting();
  if (running) updateBatchPushUI();
}

async function toggleFollowup(sid) {
  try {
    const r = await post(`/followups/${sid}/toggle`, {});
    if (!r.ok) throw new Error(r.error || '服务器未确认更新');
    await loadPage('followups');
  } catch(e) {
    uiAlert('更新跟进状态失败：' + (e.message || '网络错误'));
  }
}

async function sendFollowupNow(sid) {
  if (!(await uiConfirm('确认立即向该客户发送跟进消息？'))) return;
  try {
  let r = await post(`/followups/${sid}/send-now`, {overrides: []});
  if (!r.ok && r.status === 'blocked' && r.overridable_reasons && r.overridable_reasons.length) {
    const labels = r.overridable_reasons.map(autoBatchReasonLabel).join('、');
    if (!(await uiConfirm(`以下限制会阻止自动跟进：${labels}\n\n是否以人工方式显式绕过这些限制继续发送？\n（每日配额、暂停状态、客户联系状态不能被绕过）`))) return;
    r = await post(`/followups/${sid}/send-now`, {overrides: r.overridable_reasons});
  }
  if (r.ok) {
    uiAlert(r.overrides_applied && r.overrides_applied.length
      ? '发送成功！（已按人工操作显式绕过：' + r.overrides_applied.map(autoBatchReasonLabel).join('、') + '）'
      : '发送成功！');
    loadPage('followups');
  } else if (r.status === 'unknown') {
    uiAlert('结果待确认：消息可能已送达。系统不会自动重试。\n\n' + (r.error || ''));
    loadPage('followups');
  } else if (r.status === 'blocked') {
    uiAlert('发送被阻止: ' + (r.error || r.reason || '未知原因'));
  } else {
    uiAlert('发送失败: ' + (r.error||'未知错误'));
    loadPage('followups');
  }
  } catch(e) {
    uiAlert('发送请求未能确认，请先检查发送记录，不要立即重复发送：' + (e.message || '网络错误'));
  }
}

