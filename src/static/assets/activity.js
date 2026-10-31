function parseLogLine(line) {
  const raw = String(line || '');
  const m = raw.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+\[(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\]\s*(.*)$/);
  if (m) {
    let level = m[2].toUpperCase();
    if (level === 'WARN') level = 'WARNING';
    if (level === 'CRITICAL') level = 'ERROR';
    return {time: m[1].replace('T',' ').slice(0,19), level, msg: m[3], raw};
  }
  let level = 'INFO';
  if (raw.includes('[ERROR]') || raw.includes('[CRITICAL]')) level = 'ERROR';
  else if (raw.includes('[WARNING]')) level = 'WARNING';
  else if (raw.includes('[DEBUG]')) level = 'DEBUG';
  return {time: raw.slice(0,19), level, msg: raw.slice(20), raw};
}

async function loadActivity(el) {
  const d = await get('/activity?lines=200');
  const rows = (d.lines || []).map(line => {
    const p = parseLogLine(line);
    const levelClass = p.level === 'ERROR' ? 'error' : p.level === 'WARNING' ? 'warning' : p.level === 'DEBUG' ? 'debug' : 'info';
    return `<tr class="log-row ${levelClass}">
      <td class="log-time">${escapeHtml(p.time)}</td>
      <td><span class="log-level ${levelClass}">${escapeHtml(p.level)}</span></td>
      <td class="log-msg">${escapeHtml(p.msg || p.raw)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    ${pageHeader('运行日志', '最近机器人事件', `<button class="btn btn-outline btn-sm" onclick="loadPage('activity')">${uiIcon('refresh')} 刷新日志</button>`)}
    <div class="panel">
      <div class="panel-header"><h3>事件记录</h3><span class="panel-meta">${d.error ? '日志读取异常' : (d.lines||[]).length + ' 行'}</span></div>
      <div class="table-wrap">
        <table class="table-wide log-table">
          <thead><tr><th style="width:170px">时间</th><th style="width:110px">级别</th><th>事件</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="3" class="table-empty"><div class="empty-state"><p>暂无运行日志</p>${d.error ? `<div class="text-muted text-xs">${escapeHtml(d.error)}</div>` : ''}</div></td></tr>`}</tbody>
        </table>
      </div>
      <div class="log-source">日志来源：${escapeHtml(d.source || '未找到日志文件')}${d.error ? ' · ' + escapeHtml(d.error) : ''}</div>
    </div>`;
}

/* ── Batch Push Unload Guard ────────────────────────────── */
window.addEventListener('beforeunload', function(e) {
  if (batchPushState && batchPushState.running) {
    e.preventDefault();
    e.returnValue = '批量推送正在进行中，离开页面将中断推送。确定要离开吗？';
    return e.returnValue;
  }
});

// Override navigate to warn during batch push
const _originalNavigate = navigate;
navigate = async function(page) {
  if (batchPushState && batchPushState.running) {
    if (!(await uiConfirm('批量推送正在进行中，切换页面将丢失推送进度。\n\n确定要离开吗？'))) return;
    resetBatchState();
  }
  _originalNavigate(page);
};

