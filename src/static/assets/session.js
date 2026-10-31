// 会话相关的通用逻辑：401 自动跳登录 + 侧边栏底部显示当前账号
(function () {
  var origFetch = window.fetch;
  window.fetch = function () {
    return origFetch.apply(this, arguments).then(function (res) {
      if (res.status === 401 && window.location.pathname !== '/login') {
        window.location.href = '/login?next=' + encodeURIComponent(
          window.location.pathname + window.location.search);
      }
      return res;
    });
  };

  function mountUserChip(me) {
    var nav = document.querySelector('nav');
    if (!nav) return;

    var box = document.createElement('div');
    box.className = 'wa-user-chip';
    box.style.cssText = [
      'margin:auto 0 0', 'padding:12px 14px 14px',
      'border-top:1px solid rgba(255,255,255,.08)'
    ].join(';');

    var email = document.createElement('div');
    email.textContent = me.email;
    email.title = me.email;
    email.style.cssText = [
      'font-size:12px', 'line-height:1.4', 'color:rgba(255,255,255,.62)',
      'margin-bottom:8px', 'overflow:hidden', 'text-overflow:ellipsis',
      'white-space:nowrap'
    ].join(';');

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '退出登录';
    btn.style.cssText = [
      'width:100%', 'height:30px', 'border:1px solid rgba(255,255,255,.14)',
      'background:transparent', 'color:rgba(255,255,255,.72)', 'border-radius:7px',
      'font-size:12px', 'cursor:pointer', 'font-family:inherit'
    ].join(';');
    btn.onmouseenter = function () { btn.style.background = 'rgba(255,255,255,.06)'; };
    btn.onmouseleave = function () { btn.style.background = 'transparent'; };
    btn.onclick = function () {
      origFetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
        .then(function () { window.location.href = '/login'; });
    };

    box.appendChild(email);
    box.appendChild(btn);
    nav.appendChild(box);

    // 折叠态下隐藏，避免挤压图标
    var observer = new MutationObserver(function () {
      box.style.display = document.body.classList.contains('nav-collapsed') ? 'none' : '';
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    if (document.body.classList.contains('nav-collapsed')) box.style.display = 'none';
  }

  origFetch('/api/auth/me', { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) { if (me && me.email) mountUserChip(me); })
    .catch(function () { /* 离线或无会话时忽略 */ });
})();
