async function loadProductDocs(el) {
  const d = await get('/product-docs');
  productDocsCache = d.items;
  const rows = d.items.map(doc => `
    <tr>
      <td>
        <div class="person">
          <span class="document-mark">${uiIcon('doc')}</span>
          <div class="person-main">
            <div class="person-name" style="max-width:360px">${escapeHtml((doc.title||'').substring(0,60))}</div>
            
          </div>
        </div>
      </td>
      <td class="text-muted" style="max-width:420px">${escapeHtml((doc.content||'').substring(0,100))}${(doc.content||'').length>100?'…':''}</td>
      <td class="text-muted document-updated">${escapeHtml(timeShort(doc.updated_at))}</td>
      <td class="actions">
        <div class="table-actions">
          <button class="btn btn-outline btn-xs" onclick="editProductDoc(${doc.id})">编辑</button>
          <button class="btn btn-danger btn-xs" onclick="deleteProductDoc(${doc.id})">删除</button>
        </div>
      </td>
    </tr>`).join('');

  el.innerHTML = `
    ${pageHeader('产品资料', '管理 AI 回复引用的产品参数和文档',
      `<button class="btn btn-outline" id="upload-docs-btn" onclick="uploadProductDocs()">${uiIcon('upload')} 上传文件</button>
       <button class="btn btn-primary" onclick="editProductDoc(0)">${uiIcon('plus')} 新建文档</button>`)}
    <div class="documents-note">
        <span>共 ${d.items.length} 份资料</span>
        <span style="color:var(--border)">|</span>
        <span>支持 TXT、Markdown、PDF、Word、Excel、CSV；扫描版图片 OCR 需安装可选依赖</span>
    </div>
    <div class="panel documents-panel">
      <div class="table-wrap">
        <table class="table-wide">
          <thead><tr><th>标题</th><th>内容摘要</th><th>更新时间</th><th class="actions">操作</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="4" class="table-empty"><div class="empty-state">${uiIcon('doc')}<p>暂无产品资料</p><button class="btn btn-primary btn-sm" onclick="uploadProductDocs()">上传第一份资料</button></div></td></tr>`}</tbody>
        </table>
      </div>
    </div>`;
}

function uploadProductDocs() {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.multiple = true;
  inp.accept = '.txt,.md,.markdown,.pdf,.docx,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.gif,.bmp,.webp';
  inp.onchange = async () => {
    const files = inp.files;
    if (!files.length) return;
    const btn = document.getElementById('upload-docs-btn');
    const origText = btn ? btn.textContent : "上传文件";
    if (btn) { btn.disabled = true; btn.textContent = '处理中...'; }
    try {
      const fd = new FormData();
      for (const f of files) fd.append('files', f);
      const r = await fetch(API + '/product-docs/upload', {method:'POST', body:fd});
      const d = await readJson(r);
      if (!r.ok) throw new Error(d.error || d.detail || ('HTTP ' + r.status));
      if (d.error) { uiAlert('上传失败：' + d.error); return; }
      let msg = `上传完成！成功 ${d.imported.length} 个`;
      if (d.failed.length) {
        msg += `，失败 ${d.failed.length} 个`;
        msg += '\n\n失败详情：\n' + d.failed.map(f => `${f.filename}: ${f.reason}`).join('\n');
      }
      uiAlert(msg);
      await loadPage('product-docs');
    } catch (e) {
      await uiAlert('上传失败：' + e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = origText; }
    }
  };
  inp.click();
}

async function editProductDoc(id) {
  try { await renderProductDocForm(id); }
  catch (e) { await uiAlert('无法读取文档：' + e.message); }
}

async function renderProductDocForm(id) {
  let title = '', content = '';
  if (id) {
    const cached = productDocsCache.find(d => d.id === id);
    if (cached) {
      title = cached.title; content = cached.content;
    } else {
      const r = await get('/product-docs');
      const doc = r.items.find(d => d.id === id);
      if (doc) { title = doc.title; content = doc.content; }
    }
  }
  openSidebar(`
    <div class="sidebar-header">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <h4>${id ? '编辑文档' : '新建文档'}</h4>
        <button onclick="closeSidebar()" style="background:none;border:none;color:var(--text3);font-size:20px;cursor:pointer;line-height:1">×</button>
      </div>
    </div>
    <div class="sidebar-body">
      <label class="f-label">标题</label>
      <input class="input" id="doc-title" value="${escapeHtml(title)}" style="margin-bottom:12px">
      <label class="f-label">内容（AI 回复客户时会引用此内容）</label>
      <textarea class="input" id="doc-content" rows="14" style="margin-bottom:16px;font-family:monospace;font-size:13px">${escapeHtml(content)}</textarea>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="saveProductDoc(${id})">保存</button>
        <button class="btn btn-outline" onclick="closeSidebar()">取消</button>
      </div>
    </div>`);
}

async function saveProductDoc(id) {
  const button = document.querySelector('#detail-sidebar .btn-primary');
  if (button && button.disabled) return;
  if (button) button.disabled = true;
  try { await persistProductDoc(id); }
  catch (e) { await uiAlert('保存失败：' + e.message); }
  finally { if (button) button.disabled = false; }
}

async function persistProductDoc(id) {
  const title = document.getElementById('doc-title').value.trim();
  const content = document.getElementById('doc-content').value.trim();
  if (!title) { uiAlert('请输入标题'); return; }
  let r;
  if (id) {
    r = await put('/product-docs/' + id, {title, content});
  } else {
    r = await post('/product-docs', {title, content});
  }
  if (r.error) { uiAlert('保存失败：' + r.error); return; }
  closeSidebar();
  await loadPage('product-docs');
}

async function deleteProductDoc(id) {
  if (!(await uiConfirm('确定删除此文档？删除后 AI 回复将不再引用此内容。'))) return;
  try {
    const r = await del('/product-docs/' + id);
    if (r.error) throw new Error(r.error);
    await loadPage('product-docs');
  } catch (e) { await uiAlert('删除失败：' + e.message); }
}


