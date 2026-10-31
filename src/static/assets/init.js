/* ── Init ─────────────────────────────────────────────────── */
(async function init() {
  const configured = await checkSetupStatus();
  // Browsing local business data does not require an AI key. Setup remains
  // available in page headers; actual AI requests still require credentials.
  if (configured === false) setupConfigured = false;
  checkBotState();
  setInterval(checkBotState, 15000);
  // Load the backend-persisted proactive switch (and migrate a legacy
  // localStorage value once). Never decide automation from localStorage.
  loadProactiveFollowupSetting();
  const hash = location.hash.replace('#','') || 'dashboard';
  _originalNavigate(hash);
})();
