async function loadDashboard(el) {
  const d = await get('/dashboard');
  const c = d.counts, w = d.workspace || {}, b = d.bridge || {};
  const connected = b.online && b.authenticated;
  updateBridgeIndicator({...b, known: true});
  updateInboxCount(w.needs_reply || 0);
  const tasks = (w.tasks || []).map(t => `
    <div class="focus-task">
      ${avatarHtml(t.name, t.phone)}
      <div class="focus-task-copy">
        <div class="focus-task-title"><button class="customer-link" onclick="viewCustomer(${Number(t.id)})">${escapeHtml(t.name || formatPhone(t.phone))}</button>
          <span class="badge ${t.needs_reply ? 'badge-blue' : 'badge-orange'}">${t.needs_reply ? '待回复' : '到期跟进'}</span></div>
        <p>${escapeHtml(t.needs_reply ? t.last_content || '客户发来了新消息' : `${t.company || '客户'} · 计划 ${friendlyDate(t.next_followup_at)} ${timeOnly(t.next_followup_at)}`)}</p>
      </div>
      <button class="btn btn-outline btn-sm" onclick="openConversation(${Number(t.id)})">${t.needs_reply ? '去回复' : '查看对话'} ${uiIcon('chevronRight')}</button>
    </div>`).join('');
  const leads = w.priority_leads || [];
  const people = leads.length ? leads : d.recent_active.slice(0, 4);
  const peopleHtml = people.map(p => `<button class="opportunity-row" onclick="viewCustomer(${Number(p.id)})">
    ${avatarHtml(p.name, p.phone)}<span class="opportunity-copy"><strong>${escapeHtml(p.name || formatPhone(p.phone))}</strong><small>${escapeHtml(p.company || '未填写公司')}</small></span>
    ${leads.length ? `<span class="lead-score">${Number(p.score)}<small>意向分</small></span>` : `<span class="muted-small">${timeAgo(p.last_contact)}</span>`}
    ${uiIcon('chevronRight')}</button>`).join('');
  const upcoming = d.upcoming.slice(0, 5).map(u => `<button class="schedule-day" onclick="showFollowupDate('${u.date}')"><span>${friendlyDate(u.date)}</span><strong>${Number(u.count)}</strong><small>位客户</small></button>`).join('');
  const issues = d.failed_recent.map(f => `<tr>
    <td><div class="person">${avatarHtml(f.name, f.phone, 'sm')}<button class="customer-link person-name" onclick="viewCustomer(${Number(f.customer_id || f.id)})">${escapeHtml(f.name || formatPhone(f.phone))}</button></div></td>
    <td>${badgeSent(f.status)}</td><td class="issue-reason">${escapeHtml(f.error_message || '暂无详细信息')}</td>
    <td class="text-muted">${timeAgo(f.sent_at)}</td><td><button class="btn btn-ghost btn-sm" onclick="openConversation(${Number(f.customer_id || f.id)})">查看 ${uiIcon('chevronRight')}</button></td>
  </tr>`).join('');
  el.innerHTML = `
    ${pageHeader('今日工作台', '把时间留给值得推进的客户。', `<button class="btn btn-primary" onclick="openInbox()">${uiIcon('message')} 打开收件箱</button>`)}
    <section class="daily-focus">
      <div class="daily-focus-copy"><span class="eyebrow"><i></i> 今日销售节奏</span><h2>${w.needs_reply ? `${Number(w.needs_reply)} 位客户，等待你的回应` : '客户动态已就位，开始今天的跟进'}<span>。</span></h2>
        <p>${Number(c.due_overdue)} 位客户已到跟进时间 · ${Number(c.today_inbound)} 条今日来信</p>
        <button class="btn btn-primary" onclick="${w.tasks?.length ? `openConversation(${Number(w.tasks[0].id)})` : "navigate('followups')"}">${w.tasks?.length ? '处理第一项待办' : '查看跟进计划'} ${uiIcon('chevronRight')}</button>
      </div>
      <button class="connection-summary" onclick="navigate('bridge')"><span class="connection-symbol ${connected ? 'is-online' : ''}">${uiIcon('whatsapp')}</span>
        <span><small>WhatsApp 连接</small><strong>${connected ? '连接正常' : b.online ? '等待扫码认证' : '尚未连接'}</strong><em>${connected ? '随时准备接收客户消息' : '前往连接中心查看状态'} ${uiIcon('chevronRight')}</em></span>
      </button>
    </section>
    <div class="stats workspace-stats">
      ${workspaceMetric('message', '待回复客户', w.needs_reply || 0, '最后有效消息来自客户', 'openInbox(\'reply\')', 'blue')}
      ${workspaceMetric('calendar', '到期跟进', c.due_overdue, `今日计划 ${c.due_today} 位`, "navigate('followups')", 'orange')}
      ${workspaceMetric('users', '活跃客户', c.active_customers, `客户总数 ${c.total_customers} 位`, "navigate('customers')", 'green')}
      ${workspaceMetric('send', '今日已发送跟进', c.sent_fu_today, `失败 ${c.failed_fu_today} · 待确认 ${c.unknown_fu_today || 0}`, "navigate('followups')", 'teal')}
    </div>
    <div class="workspace-grid">
      <section class="panel focus-panel"><div class="panel-header"><div><span class="eyebrow">NEXT TO DO</span><h3>优先处理</h3></div><button class="btn btn-ghost btn-sm" onclick="navigate('followups')">全部跟进 ${uiIcon('chevronRight')}</button></div>
        <div class="focus-task-list">${tasks || `<div class="workspace-empty">${uiIcon('check')}<strong>当前没有待处理事项</strong><p>新的客户来信和到期跟进会出现在这里。</p><button class="btn btn-outline btn-sm" onclick="navigate('customers')">查看客户</button></div>`}</div>
        <div class="panel-footnote">优先显示待回复客户，其次为到期跟进；最多显示 6 位。</div>
      </section>
      <section class="panel opportunity-panel"><div class="panel-header"><div><span class="eyebrow">CUSTOMER FOCUS</span><h3>${leads.length ? '值得关注的客户' : '最近联系的客户'}</h3></div>${uiIcon('users')}</div>
        <div>${peopleHtml || '<div class="workspace-empty"><p>导入客户后，在这里查看客户动态。</p></div>'}</div>
        <div class="panel-footnote">${leads.length ? '按已有意向评分排序，评分用于辅助判断。' : '积累对话与评分后，这里将展示重点客户。'}</div>
      </section>
    </div>
    <section class="panel schedule-panel"><div class="schedule-heading"><span class="soft-icon">${uiIcon('calendar')}</span><div><h3>接下来的跟进</h3><p>提前安排，保持联系。</p></div></div><div class="schedule-days">${upcoming || '<span class="text-muted">暂无后续跟进计划</span>'}</div><button class="btn btn-ghost btn-sm" onclick="navigate('followups')">查看计划 ${uiIcon('chevronRight')}</button></section>
    <section class="panel dashboard-issues"><div class="panel-header"><div><h3>需要留意的发送</h3><p>发送失败与结果待确认的消息，分别处理。</p></div><span class="badge ${issues ? 'badge-orange' : 'badge-green'}">${d.failed_recent.length} 条记录</span></div>
      ${issues ? `<div class="table-wrap"><table><thead><tr><th>客户</th><th>发送状态</th><th>原因</th><th>时间</th><th></th></tr></thead><tbody>${issues}</tbody></table></div>` : '<div class="inline-empty">暂无发送异常记录</div>'}
    </section>`;
}

function workspaceMetric(icon, label, value, hint, action, tone) {
  return `<button class="stat-card metric-button" onclick="${action}"><div class="stat-top"><span class="stat-label">${label}</span><span class="metric-icon ${tone}">${uiIcon(icon)}</span></div><div class="stat-val">${Number(value) || 0}<span>${icon === 'send' ? '次' : '位'}</span></div><div class="stat-sub">${escapeHtml(hint)} ${uiIcon('chevronRight')}</div></button>`;
}
