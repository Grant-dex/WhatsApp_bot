/* Shared, read-only customer intelligence. These endpoints do not call an LLM. */
const segmentLabels = {hot:'高意向', warm:'有意向', cold:'待培育', dormant:'待唤醒', new:'新客户'};
const intentLabels = {rfq:'询问价格', technical:'关注技术参数', delivery_inquiry:'询问交期', warranty_inquiry:'关注售后', payment_inquiry:'询问付款', urgent:'需求紧急', complaint:'提出问题', competitor_mention:'对比供应商', closing_signal:'出现采购信号', stop_request:'提出停止联系'};
const scoreLabels = {recency:'近期互动', depth:'对话深度', reply_rate:'回复情况', signals:'采购信号', followup_response:'跟进回应', order_bonus:'历史订单', inactivity_penalty:'沉默扣分'};

function updateInboxCount(count) {
  const el = document.getElementById('inbox-count');
  if (el) { el.textContent = Number(count) > 99 ? '99+' : String(Number(count) || 0); el.hidden = !count; el.title = '待回复客户'; }
}
function parseCustomerTags(value) {
  if (Array.isArray(value)) return value.filter(t => typeof t === 'string');
  try { const tags = JSON.parse(value || '[]'); if (Array.isArray(tags)) return tags.filter(t => typeof t === 'string'); } catch (_) {}
  return String(value || '').split(/[,，]/).map(x => x.trim()).filter(Boolean);
}
function insightSkeleton() {
  return '<div class="insight-skeleton" aria-label="正在读取客户分析"><span></span><span></span><span></span></div>';
}
function renderCustomerInsights(d) {
  const score = d.score || {}, intent = d.intent || {};
  const hasMessages = !!intent.has_recent_activity;
  const points = Math.max(0, Math.min(100, Number(score.score) || 0));
  const memories = (d.memory || []).filter(m => m.content).slice(0, 4);
  const breakdown = Object.entries(score.breakdown || {}).map(([k, v]) => `<div><span>${escapeHtml(scoreLabels[k] || k)}</span><strong>${k === 'inactivity_penalty' && v ? '−' : ''}${Number(v) || 0}</strong></div>`).join('');
  return `<section class="insight-score"><div class="insight-section-title"><h4>客户洞察</h4><span class="insight-label">规则分析</span></div>
    <div class="score-summary"><div class="score-number">${points}<small>/ 100</small></div><span class="badge ${score.segment === 'hot' ? 'badge-orange' : 'badge-teal'}">${escapeHtml(segmentLabels[score.segment] || '待分析')}</span></div>
    <div class="score-track"><span style="width:${points}%"></span></div>
    <p class="insight-caption">${hasMessages ? escapeHtml(intent.stage_desc || '尚未识别明确销售阶段') : '客户来信不足，阶段暂未识别'}</p>
    <details class="score-details"><summary>查看评分依据</summary><div>${breakdown}</div><p>意向分用于辅助排序，不代表成交概率。</p></details>
    <div class="insight-updated">计算于 ${escapeHtml(timeShort(d.computed_at))}</div>
  </section>
  ${(intent.detected_intents || []).length ? `<section class="insight-section"><h4>近期关注</h4><div class="insight-tags">${intent.detected_intents.map(i => `<span>${escapeHtml(intentLabels[i] || i)}</span>`).join('')}</div><p class="insight-caption">基于最近客户来信的关键词识别。</p></section>` : ''}
  <section class="insight-section"><h4>需求与记忆</h4>${memories.length ? `<ul class="memory-list">${memories.map(m => `<li>${escapeHtml(m.content)}</li>`).join('')}</ul><p class="insight-caption">历史提取内容，请结合原对话核实。</p>` : '<p class="context-empty">尚无已提取的客户记忆，可先在备注中记录需求。</p>'}</section>`;
}
async function fillCustomerInsights(target, id, isCurrent) {
  try {
    const data = await get('/agent/customer-analysis/' + Number(id));
    if (target.isConnected && isCurrent()) target.innerHTML = renderCustomerInsights(data);
  } catch (_) {
    if (target.isConnected && isCurrent()) {
      target.innerHTML = '<div class="insight-error"><p>客户分析暂时无法读取。</p><button class="btn btn-outline btn-sm">重试分析</button></div>';
      target.querySelector('button').onclick = () => { target.innerHTML = insightSkeleton(); fillCustomerInsights(target, id, isCurrent); };
    }
  }
}
function renderContextOrders(orders) {
  return `<section class="insight-section"><div class="insight-section-title"><h4>关联订单 <span>${orders.length}</span></h4></div>${orders.length ? orders.slice(0, 3).map(o => `<button class="context-order" onclick="openOrderForm(${Number(o.id)})"><span><strong>${escapeHtml(o.order_no)}</strong><small>${escapeHtml(o.product || '未填写产品')}</small></span>${statusLabel(o.status)}</button>`).join('') : '<p class="context-empty">还没有关联订单</p>'}</section>`;
}
