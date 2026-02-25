'use strict';

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------

function _ensureToastContainer() {
  let c = document.getElementById('toast-container');
  if (!c) {
    c = document.createElement('div');
    c.id = 'toast-container';
    c.className = 'toast-container';
    document.body.appendChild(c);
  }
  return c;
}

/**
 * Show a toast notification.
 * @param {string}  message
 * @param {'error'|'success'|'info'} type
 * @param {number}  duration  ms before auto-dismiss (0 = manual only)
 */
function showToast(message, type = 'info', duration = 4000) {
  const container = _ensureToastContainer();
  const icons = { error: '\u2718', success: '\u2713', info: '\u24d8' };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type] || ''}</span>
    <span class="toast-body">${esc(message)}</span>
    <button class="toast-close" aria-label="Dismiss">&times;</button>`;
  toast.querySelector('.toast-close').addEventListener('click', () => _dismissToast(toast));
  container.appendChild(toast);
  if (duration > 0) setTimeout(() => _dismissToast(toast), duration);
}

function _dismissToast(toast) {
  if (toast._removing) return;
  toast._removing = true;
  toast.classList.add('toast-removing');
  toast.addEventListener('animationend', () => toast.remove());
}

/** Set a button to loading state; returns a restore function */
function btnLoading(btn, loadingText) {
  if (!btn) return () => {};
  const orig = btn.textContent;
  const wasDisabled = btn.disabled;
  btn.textContent = loadingText || orig;
  btn.classList.add('btn-loading');
  btn.disabled = true;
  return () => {
    btn.textContent = orig;
    btn.classList.remove('btn-loading');
    btn.disabled = wasDisabled;
  };
}

// ---------------------------------------------------------------------------
// Auth state
// ---------------------------------------------------------------------------

let _authMode = 'none';  // 'cognito' | 'api_key' | 'none' — set at startup
let _cognitoConfig = {};  // { userPoolId, clientId, region }

// Legacy API-key auth
let _apiKey = localStorage.getItem('ra_api_key') || '';

// Cognito auth
let _idToken = localStorage.getItem('ra_id_token') || '';
let _refreshToken = localStorage.getItem('ra_refresh_token') || '';
let _userEmail = '';
let _tokenExpiry = 0;  // epoch ms

let _userRole = 'admin';  // default; will be fetched from /me
let _roleOverride = localStorage.getItem('ra_role_override') || '';  // dev role switcher

/** Discover auth mode from the server. */
async function _initAuth() {
  try {
    const res = await fetch('/auth/config');
    if (res.ok) {
      const cfg = await res.json();
      _authMode = cfg.mode || 'none';
      if (_authMode === 'cognito') {
        _cognitoConfig = { userPoolId: cfg.userPoolId, clientId: cfg.clientId, region: cfg.region };
        // Try to restore session from stored tokens
        if (_idToken) {
          try {
            const payload = JSON.parse(atob(_idToken.split('.')[1]));
            _userEmail = payload.email || payload['cognito:username'] || '';
            _tokenExpiry = (payload.exp || 0) * 1000;
            if (Date.now() > _tokenExpiry) {
              // Token expired — try refresh
              if (_refreshToken) {
                await _refreshCognitoTokens();
              } else {
                _clearCognitoSession();
              }
            }
          } catch (_) { _clearCognitoSession(); }
        }
      }
    }
  } catch (_) { /* keep defaults */ }
}

function _clearCognitoSession() {
  _idToken = '';
  _refreshToken = '';
  _userEmail = '';
  _tokenExpiry = 0;
  localStorage.removeItem('ra_id_token');
  localStorage.removeItem('ra_refresh_token');
}

/** Call Cognito InitiateAuth / RespondToAuthChallenge via fetch. */
async function _cognitoCall(action, body) {
  const url = `https://cognito-idp.${_cognitoConfig.region}.amazonaws.com/`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    const msg = data.message || data.__type || 'Authentication failed';
    throw new Error(msg);
  }
  return data;
}

/** Authenticate with email + password. */
async function _cognitoLogin(email, password) {
  const data = await _cognitoCall('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: _cognitoConfig.clientId,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });

  if (data.ChallengeName === 'NEW_PASSWORD_REQUIRED') {
    return { challenge: 'NEW_PASSWORD_REQUIRED', session: data.Session, email };
  }

  _storeCognitoTokens(data.AuthenticationResult);
  return { success: true };
}

/** Respond to NEW_PASSWORD_REQUIRED challenge. */
async function _cognitoNewPassword(session, email, newPassword) {
  const data = await _cognitoCall('RespondToAuthChallenge', {
    ChallengeName: 'NEW_PASSWORD_REQUIRED',
    ClientId: _cognitoConfig.clientId,
    Session: session,
    ChallengeResponses: {
      USERNAME: email,
      NEW_PASSWORD: newPassword,
    },
  });
  _storeCognitoTokens(data.AuthenticationResult);
  return { success: true };
}

/** Refresh tokens using the refresh token. */
async function _refreshCognitoTokens() {
  try {
    const data = await _cognitoCall('InitiateAuth', {
      AuthFlow: 'REFRESH_TOKEN_AUTH',
      ClientId: _cognitoConfig.clientId,
      AuthParameters: { REFRESH_TOKEN: _refreshToken },
    });
    _storeCognitoTokens(data.AuthenticationResult);
  } catch (_) {
    _clearCognitoSession();
  }
}

/** Store tokens from a successful auth. */
function _storeCognitoTokens(result) {
  _idToken = result.IdToken;
  if (result.RefreshToken) _refreshToken = result.RefreshToken;
  localStorage.setItem('ra_id_token', _idToken);
  if (_refreshToken) localStorage.setItem('ra_refresh_token', _refreshToken);
  try {
    const payload = JSON.parse(atob(_idToken.split('.')[1]));
    _userEmail = payload.email || payload['cognito:username'] || '';
    _tokenExpiry = (payload.exp || 0) * 1000;
  } catch (_) { /* ignore */ }
}

/** Ensure the ID token is fresh (auto-refresh if expiring soon). */
async function _ensureFreshToken() {
  if (_authMode !== 'cognito' || !_idToken) return;
  // Refresh if within 5 minutes of expiry
  if (Date.now() > _tokenExpiry - 5 * 60 * 1000) {
    if (_refreshToken) await _refreshCognitoTokens();
  }
}

/** Build common headers for API calls. */
function _apiHeaders() {
  if (_authMode === 'cognito' && _idToken) {
    const h = { 'Authorization': `Bearer ${_idToken}` };
    return h;
  }
  const h = {};
  if (_apiKey) h['X-API-Key'] = _apiKey;
  if (_roleOverride) h['X-User-Role'] = _roleOverride;
  return h;
}

/** Fetch the current user's role from the server. */
async function _fetchRole() {
  try {
    await _ensureFreshToken();
    const res = await fetch('/me', { headers: _apiHeaders() });
    if (res.ok) {
      const data = await res.json();
      _userRole = data.role || 'admin';
      if (data.email && data.email !== 'anonymous') _userEmail = data.email;
    }
  } catch (_) { /* keep default */ }
}

/** Return html if the current user has at least editor role, else ''. */
function ifEditor(html) { return (_userRole === 'editor' || _userRole === 'admin') ? html : ''; }

/** Return html if the current user has admin role, else ''. */
function ifAdmin(html) { return _userRole === 'admin' ? html : ''; }

/** True when the current user can edit (editor or admin). */
function canEdit() { return _userRole === 'editor' || _userRole === 'admin'; }

/** True when the current user is an admin. */
function canAdmin() { return _userRole === 'admin'; }

function _syncHeader() {
  // --- Logout / change-key button ---
  const existing = document.getElementById('logout-btn');
  if (_authMode === 'cognito' && _idToken) {
    if (!existing) {
      const wrap = document.createElement('span');
      wrap.id = 'logout-btn';
      wrap.style.cssText = 'display:flex;align-items:center;gap:8px;margin-left:auto';
      const emailSpan = document.createElement('span');
      emailSpan.className = 'header-email';
      emailSpan.style.cssText = 'font-size:0.75rem;color:#aaa';
      emailSpan.textContent = _userEmail;
      const roleBadge = document.createElement('span');
      roleBadge.className = 'header-role-badge';
      roleBadge.textContent = _userRole;
      roleBadge.dataset.role = _userRole;
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-secondary';
      btn.style.cssText = 'font-size:0.75rem';
      btn.textContent = 'Logout';
      btn.addEventListener('click', () => {
        _clearCognitoSession();
        _userRole = 'admin';
        _syncHeader();
        renderLogin();
      });
      wrap.appendChild(emailSpan);
      wrap.appendChild(roleBadge);
      wrap.appendChild(btn);
      document.querySelector('.site-header').appendChild(wrap);
    } else {
      const emailSpan = existing.querySelector('.header-email');
      if (emailSpan) emailSpan.textContent = _userEmail;
      const roleBadge = existing.querySelector('.header-role-badge');
      if (roleBadge) { roleBadge.textContent = _userRole; roleBadge.dataset.role = _userRole; }
    }
  } else if (_authMode === 'api_key' && _apiKey) {
    if (!existing) {
      const btn = document.createElement('button');
      btn.id = 'logout-btn';
      btn.className = 'btn btn-sm btn-secondary';
      btn.style.cssText = 'font-size:0.75rem';
      btn.textContent = 'Change API Key';
      btn.addEventListener('click', () => {
        localStorage.removeItem('ra_api_key');
        _apiKey = '';
        _syncHeader();
        renderLogin();
      });
      document.querySelector('.site-header').appendChild(btn);
    }
  } else {
    if (existing) existing.remove();
  }

  // Role switcher dropdown — only shown in non-Cognito modes (dev aid)
  let roleSwitcherWrap = document.querySelector('.role-switcher-wrap');
  if (_authMode === 'cognito') {
    if (roleSwitcherWrap) roleSwitcherWrap.remove();
  } else {
    let roleSwitcher = document.getElementById('role-switcher');
    if (!roleSwitcher) {
      const wrap = document.createElement('div');
      wrap.className = 'role-switcher-wrap';
      wrap.innerHTML = `<label class="role-switcher-label">Role:</label>
        <select id="role-switcher" class="role-switcher">
          <option value="">auto</option>
          <option value="viewer">viewer</option>
          <option value="editor">editor</option>
          <option value="admin">admin</option>
        </select>`;
      document.querySelector('.site-header').appendChild(wrap);
      roleSwitcher = document.getElementById('role-switcher');
      roleSwitcher.addEventListener('change', async () => {
        _roleOverride = roleSwitcher.value;
        if (_roleOverride) localStorage.setItem('ra_role_override', _roleOverride);
        else localStorage.removeItem('ra_role_override');
        await _fetchRole();
        _syncHeader();
        router();
      });
    }
    roleSwitcher.value = _roleOverride;
    roleSwitcher.className = `role-switcher role-${_userRole}`;
  }
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  await _ensureFreshToken();
  const opts = { method, headers: _apiHeaders() };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  if (res.status === 401) {
    if (_authMode === 'cognito') _clearCognitoSession();
    renderLogin('Your session has expired. Please log in again.');
    throw new Error('Unauthorised');
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch {}
    const err = new Error(msg);
    err.httpStatus = res.status;
    throw err;
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

// ---------------------------------------------------------------------------
// Login screen
// ---------------------------------------------------------------------------

function renderLogin(errorMsg) {
  _syncHeader();
  if (_authMode === 'cognito') {
    document.getElementById('app').innerHTML = `
      <section class="panel" style="max-width:420px;margin:60px auto">
        <h3>Sign In</h3>
        <p style="line-height:1.5">Enter your email and password to access the Catalogue Tool.</p>
        ${errorMsg ? `<p class="error">${esc(errorMsg)}</p>` : ''}
        <div class="form-row" style="margin-top:16px">
          <label style="width:90px">Email</label>
          <input id="login-email" type="email" autocomplete="username"
                 placeholder="you@example.com" style="flex:1">
        </div>
        <div class="form-row" style="margin-top:8px">
          <label style="width:90px">Password</label>
          <input id="login-password" type="password" autocomplete="current-password"
                 placeholder="Password" style="flex:1">
        </div>
        <div class="form-actions" style="margin-top:12px">
          <button id="login-btn" class="btn btn-primary" onclick="handleCognitoLogin()">Sign In</button>
        </div>
      </section>`;
    setTimeout(() => document.getElementById('login-email')?.focus(), 0);
    ['login-email', 'login-password'].forEach(id => {
      document.getElementById(id)?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleCognitoLogin();
      });
    });
  } else {
    document.getElementById('app').innerHTML = `
      <section class="panel" style="max-width:420px;margin:60px auto">
        <h3>API Key Required</h3>
        <p style="line-height:1.5">Enter the API key configured on this server.
           Leave blank if the server is running without authentication (development mode).</p>
        ${errorMsg ? `<p class="error">${esc(errorMsg)}</p>` : ''}
        <div class="form-row" style="margin-top:16px">
          <label style="width:90px">API Key</label>
          <input id="login-key-input" type="password" autocomplete="current-password"
                 placeholder="Paste your API key here" style="flex:1">
        </div>
        <div class="form-actions" style="margin-top:12px">
          <button class="btn btn-primary" onclick="handleLogin()">Connect</button>
        </div>
      </section>`;
    setTimeout(() => document.getElementById('login-key-input')?.focus(), 0);
    document.getElementById('login-key-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleLogin();
    });
  }
}

function _renderNewPasswordForm(session, email, errorMsg) {
  document.getElementById('app').innerHTML = `
    <section class="panel" style="max-width:420px;margin:60px auto">
      <h3>Set New Password</h3>
      <p style="line-height:1.5">You must set a new password on first login.</p>
      ${errorMsg ? `<p class="error">${esc(errorMsg)}</p>` : ''}
      <div class="form-row" style="margin-top:16px">
        <label style="width:90px">New Password</label>
        <input id="new-password" type="password" autocomplete="new-password"
               placeholder="At least 12 characters" style="flex:1">
      </div>
      <div class="form-row" style="margin-top:8px">
        <label style="width:90px">Confirm</label>
        <input id="new-password-confirm" type="password" autocomplete="new-password"
               placeholder="Confirm new password" style="flex:1">
      </div>
      <div class="form-actions" style="margin-top:12px">
        <button id="set-password-btn" class="btn btn-primary">Set Password</button>
      </div>
    </section>`;
  setTimeout(() => document.getElementById('new-password')?.focus(), 0);
  document.getElementById('set-password-btn').addEventListener('click', async () => {
    const pwd = document.getElementById('new-password').value;
    const confirm = document.getElementById('new-password-confirm').value;
    if (pwd !== confirm) {
      _renderNewPasswordForm(session, email, 'Passwords do not match.');
      return;
    }
    if (pwd.length < 12) {
      _renderNewPasswordForm(session, email, 'Password must be at least 12 characters.');
      return;
    }
    const btn = document.getElementById('set-password-btn');
    const restore = btnLoading(btn, 'Setting\u2026');
    try {
      await _cognitoNewPassword(session, email, pwd);
      _syncHeader();
      await _fetchRole();
      router();
    } catch (err) {
      restore();
      _renderNewPasswordForm(session, email, err.message);
    }
  });
  ['new-password', 'new-password-confirm'].forEach(id => {
    document.getElementById(id)?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('set-password-btn')?.click();
    });
  });
}

async function handleCognitoLogin() {
  const email = (document.getElementById('login-email')?.value ?? '').trim();
  const password = (document.getElementById('login-password')?.value ?? '').trim();
  if (!email || !password) { renderLogin('Please enter both email and password.'); return; }
  const btn = document.getElementById('login-btn');
  const restore = btnLoading(btn, 'Signing in\u2026');
  try {
    const result = await _cognitoLogin(email, password);
    if (result.challenge === 'NEW_PASSWORD_REQUIRED') {
      _renderNewPasswordForm(result.session, result.email);
      return;
    }
    _syncHeader();
    await _fetchRole();
    router();
  } catch (err) {
    restore();
    renderLogin(err.message);
  }
}

async function handleLogin() {
  const key = (document.getElementById('login-key-input')?.value ?? '').trim();
  _apiKey = key;
  if (key) localStorage.setItem('ra_api_key', key);
  else localStorage.removeItem('ra_api_key');
  _syncHeader();
  await _fetchRole();
  router();
}

// ---------------------------------------------------------------------------
// HTML escaping
// ---------------------------------------------------------------------------

function esc(v) {
  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

function navigate(hash) { location.hash = hash; }

function _highlightNav() {
  const hash = location.hash || '#/';
  document.querySelectorAll('.site-nav a:not([target])').forEach(a => {
    const href = a.getAttribute('href');
    const active = href === '#/'
      ? (hash === '#/' || hash === '')
      : (hash === href || hash.startsWith(href + '/'));
    a.classList.toggle('active', active);
  });
}

function router() {
  _syncHeader();
  _highlightNav();
  const hash = location.hash || '#/';
  const importMatch = hash.match(/^#\/import\/([^/]+)/);
  const indexDetailMatch = hash.match(/^#\/index\/([^/]+)/);
  const tmplEditMatch = hash.match(/^#\/templates\/([^/]+)\/edit$/);
  const idxTmplEditMatch = hash.match(/^#\/index-templates\/([^/]+)\/edit$/);
  if (importMatch)             renderDetail(importMatch[1]);
  else if (indexDetailMatch)   renderIndexDetail(indexDetailMatch[1]);
  else if (idxTmplEditMatch)   renderIndexTemplateEdit(idxTmplEditMatch[1]);
  else if (tmplEditMatch)      renderTemplateEdit(tmplEditMatch[1]);
  else if (hash === '#/index')             renderIndexList();
  else if (hash === '#/templates')         renderTemplates();
  else if (hash === '#/audit')             renderAuditLog();
  else if (hash === '#/settings')          renderSettings();
  else                                     renderList();
}

window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', async () => {
  // Discover auth mode before anything else
  await _initAuth();
  _syncHeader();
  // Show environment banner for non-production hosts
  if (/^staging[.-]/i.test(location.hostname)) {
    const banner = document.createElement('div');
    banner.className = 'env-banner env-staging';
    banner.textContent = 'STAGING';
    document.body.insertBefore(banner, document.body.firstChild);
    document.title = 'RA Catalogue Tool (staging)';
  } else if (/^(localhost|127\.0\.0\.1)$/i.test(location.hostname)) {
    const banner = document.createElement('div');
    banner.className = 'env-banner env-local';
    banner.textContent = 'LOCAL DEV';
    document.body.insertBefore(banner, document.body.firstChild);
    document.title = 'RA Catalogue Tool (local)';
  } else {
    document.title = 'RA Catalogue Tool (prod)';
  }
  // If Cognito mode and not logged in, show login
  if (_authMode === 'cognito' && !_idToken) {
    renderLogin();
    return;
  }
  await _fetchRole();
  router();
});

// ---------------------------------------------------------------------------
// Audit log viewer (shared helper + per-import panel + global page)
// ---------------------------------------------------------------------------

function _auditActionLabel(action) {
  const labels = {
    override_set: 'Override set',
    override_deleted: 'Override deleted',
    work_excluded: 'Work excluded',
    work_included: 'Work included',
    reimport: 'Re-import',
    template_created: 'Template created',
    template_updated: 'Template updated',
    template_deleted: 'Template deleted',
    template_duplicated: 'Template duplicated',
    index_template_created: 'Index template created',
    index_template_updated: 'Index template updated',
    index_template_deleted: 'Index template deleted',
    index_template_duplicated: 'Index template duplicated',
    index_artist_excluded: 'Artist excluded',
    index_artist_included: 'Artist included',
    index_artist_company_set: 'Company set',
    index_artist_company_unset: 'Company unset',
    index_artist_unmerged: 'Artist unmerged',
  };
  return labels[action] || action;
}

function _auditLogTable(logs) {
  if (!logs.length) return '<p class="muted">No audit log entries.</p>';

  const rows = logs.map(log => {
    const who = [log.cat_no, log.artist_name, log.title].filter(Boolean).join(' \u2013 ');
    let workCell;
    if (log.work_id) {
      workCell = `<button type="button" class="link-btn" onclick="scrollToWork('${esc(log.work_id)}')">${esc(who || log.work_id.slice(0, 8) + '\u2026')}</button>`;
    } else if (log.artist_id && log.index_artist_name) {
      workCell = `<button type="button" class="link-btn" onclick="scrollToIndexArtist('${esc(log.artist_id)}')">${esc(log.index_artist_name)}</button>`;
    } else if (log.template_name) {
      workCell = `<span class="muted">${esc(log.template_name)}</span>`;
    } else {
      workCell = '<span class="muted">\u2014</span>';
    }

    let change = '';
    if (log.action === 'reimport') {
      change = esc(log.new_value || '');
    } else if (log.field) {
      const parts = [];
      if (log.old_value != null) parts.push(`<span class="audit-old">${esc(log.old_value)}</span>`);
      parts.push('\u2192');
      if (log.new_value != null) parts.push(`<span class="audit-new">${esc(log.new_value)}</span>`);
      else parts.push('<span class="muted">(cleared)</span>');
      change = `<code>${esc(log.field)}</code>: ${parts.join(' ')}`;
    }

    const user = log.user_email && log.user_email !== 'anonymous'
      ? `<span class="muted" style="font-size:0.8em">${esc(log.user_email)}</span>`
      : '<span class="muted">—</span>';

    return `<tr>
      <td class="col-ts muted">${esc(formatDate(log.created_at))}</td>
      <td>${user}</td>
      <td><span class="badge badge-audit">${esc(_auditActionLabel(log.action))}</span></td>
      <td>${workCell}</td>
      <td>${change}</td>
    </tr>`;
  }).join('');

  return `<table class="data-table audit-table">
    <thead><tr><th class="col-ts">Time</th><th>User</th><th>Action</th><th>Subject</th><th>Change</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderAuditPanel(logs) {
  const panel = document.getElementById('audit-panel');
  if (!panel) return;
  if (!logs.length) {
    panel.innerHTML = '<p class="muted" style="padding:4px 0">No audit log entries yet.</p>';
    return;
  }
  panel.innerHTML = `
    <details>
      <summary class="section-summary"><span class="section-name">Audit Log</span>
        <span class="section-meta">${logs.length} entr${logs.length !== 1 ? 'ies' : 'y'}</span>
      </summary>
      ${_auditLogTable(logs)}
    </details>`;
}

async function renderAuditLog() {
  document.getElementById('app').innerHTML = `
    <h2 class="page-heading">Audit Log</h2>
    <section class="panel" id="audit-global"><p class="loading">Loading\u2026</p></section>`;

  try {
    const logs = await api('GET', '/audit-log?limit=500');
    const container = document.getElementById('audit-global');
    if (!logs.length) {
      container.innerHTML = '<p class="muted">No audit log entries.</p>';
      return;
    }

    // Split into template-level and import-level entries
    const templateLogs = logs.filter(l => !l.import_id);
    const importLogs = logs.filter(l => l.import_id);

    // Group import logs by import_id
    const byImport = new Map();
    for (const log of importLogs) {
      if (!byImport.has(log.import_id)) byImport.set(log.import_id, []);
      byImport.get(log.import_id).push(log);
    }

    let html = `<p class="muted" style="margin-bottom:12px">${logs.length} entries</p>`;

    // Template events section
    if (templateLogs.length) {
      html += `
        <details class="section-block" open>
          <summary class="section-summary">
            <span class="section-name">Template changes</span>
            <span class="section-meta">${templateLogs.length} entr${templateLogs.length !== 1 ? 'ies' : 'y'}</span>
          </summary>
          ${_auditLogTable(templateLogs)}
        </details>`;
    }

    // Import event sections
    for (const [importId, iLogs] of byImport) {
      html += `
        <details class="section-block" open>
          <summary class="section-summary">
            <span class="section-name">Import <code class="import-id" title="${esc(importId)}">${esc(importId.slice(0, 8))}&hellip;</code></span>
            <span class="section-meta">${iLogs.length} entr${iLogs.length !== 1 ? 'ies' : 'y'}</span>
            <a href="#/import/${esc(importId)}" class="btn btn-xs btn-secondary" style="margin-left:auto" onclick="event.stopPropagation()">View import</a>
          </summary>
          ${_auditLogTable(iLogs)}
        </details>`;
    }
    container.innerHTML = html;
  } catch (err) {
    document.getElementById('audit-global').innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Settings page
// ---------------------------------------------------------------------------

async function renderSettings() {
  const app = document.getElementById('app');
  app.innerHTML = '<p class="loading" style="padding:40px 0">Loading settings&hellip;</p>';
  let cfg, knownArtists;
  try {
    [cfg, knownArtists] = await Promise.all([
      api('GET', '/config'),
      api('GET', '/known-artists'),
    ]);
  } catch (e) { app.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }

  // Load display prefs from localStorage
  const dispCfg = _getDisplayCfg();
  const dispCurr = dispCfg.currency_symbol;
  const dispSep  = dispCfg.thousands_separator;
  const dispDp   = dispCfg.decimal_places;
  const dispEdPrefix   = dispCfg.edition_prefix;
  const dispEdBrackets = dispCfg.edition_brackets;

  const sepOpts = (val) => [
    [',', ', &nbsp; 1,000'],
    ['.', '. &nbsp; 1.000'],
    [' ', 'space &nbsp; 1 000'],
    ['',  'none &nbsp; 1000'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');
  const dpOpts = (val) => [
    ['0', '0 &nbsp;&mdash;&nbsp; 1,500'],
    ['2', '2 &nbsp;&mdash;&nbsp; 1,500.00'],
  ].map(([v, label]) => `<option value="${v}"${String(val) === v ? ' selected' : ''}>${label}</option>`).join('');
  const honorificTokensValue = Array.isArray(cfg.honorific_tokens)
    ? cfg.honorific_tokens.join(', ')
    : (cfg.honorific_tokens ?? 'RA, PRA, PPRA, HON, HONRA, ELECT, EX, OFFICIO');

  app.innerHTML = `
    <h2 class="page-heading">Settings</h2>

    ${canAdmin() && _authMode === 'cognito' ? `
    <h3 class="settings-group-heading">Users</h3>
    <p class="settings-group-desc">Manage who can access the Catalogue Tool and their permission level.</p>
    <section class="panel" id="users-panel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h4 class="panel-subheading" style="margin:0">User Accounts</h4>
        <button class="btn btn-sm btn-primary" onclick="_showCreateUserForm()">+ New User</button>
      </div>
      <div id="create-user-form-slot"></div>
      <table class="data-table" id="users-table">
        <thead><tr><th>Email</th><th>Role</th><th>Status</th><th style="width:180px">Actions</th></tr></thead>
        <tbody><tr><td colspan="4" class="muted">Loading&hellip;</td></tr></tbody>
      </table>
    </section>
    ` : ''}

    <h3 class="settings-group-heading">Normalisation</h3>
    <p class="settings-group-desc">Applied when an Excel file is imported. Changes here take effect on the <em>next</em> import.</p>
    <section class="panel">
      <h4 class="panel-subheading">Honorific Tokens</h4>
      <div class="settings-form">
        <div class="form-row">
          <label>Recognised tokens</label>
          <input id="cfg-honorific-tokens" type="text" value="${esc(honorificTokensValue)}"${canAdmin() ? '' : ' readonly'}>
          <span class="form-hint">Comma-separated list of abbreviations stripped from the end of artist names, e.g. &ldquo;RA, HON, PRA&rdquo;</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <h4 class="panel-subheading">Known Artists</h4>
      <p class="form-hint" style="margin:0 0 12px">Map recurring raw spreadsheet values to corrected output. Matched during import.</p>
      <table class="data-table known-artists-table" id="known-artists-table">
        <thead>
          <tr>
            <th>Match First</th>
            <th>Match Last</th>
            <th>Match Quals</th>
            <th>&rarr; First</th>
            <th>&rarr; Last</th>
            <th>&rarr; Quals</th>
            <th>&rarr; A2 First</th>
            <th>&rarr; A2 Last</th>
            <th>&rarr; A2 Quals</th>
            <th>A1 RA</th>
            <th>A2 RA</th>
            <th>Company</th>
            <th>Index Name Preview</th>
            <th>Notes</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${knownArtists.map(ka => _knownArtistRow(ka)).join('')}
        </tbody>
      </table>
      <div style="margin-top:8px">
        ${ifEditor('<button class="btn btn-sm" onclick="addKnownArtistRow()">+ Add entry</button>')}
        ${ifAdmin(`<button class="btn btn-sm" onclick="seedKnownArtists()" style="margin-left:8px" title="Load built-in known artists (won&rsquo;t overwrite existing entries)">Load defaults</button>`)}
        <span id="known-artists-status" class="status-msg" style="margin-left:8px"></span>
      </div>
    </section>

    <h3 class="settings-group-heading">Preview</h3>
    <p class="settings-group-desc">Controls how values appear in this browser view only &mdash; stored locally, never sent to the server.</p>
    <section class="panel">
      <h4 class="panel-subheading">HTML Preview Formatting</h4>
      <div class="settings-form">
        <div class="form-row">
          <label>Currency symbol</label>
          <input id="disp-currency" type="text" value="${esc(dispCurr)}" style="max-width:80px">
        </div>
        <div class="form-row">
          <label>Thousands separator</label>
          <select id="disp-thousands-sep">${sepOpts(dispSep)}</select>
        </div>
        <div class="form-row">
          <label>Decimal places</label>
          <select id="disp-decimal-places">${dpOpts(dispDp)}</select>
        </div>
        <div class="form-row">
          <label>Edition prefix</label>
          <input id="disp-edition-prefix" type="text" value="${esc(dispEdPrefix)}" style="max-width:200px">
          <span class="form-hint">e.g. &ldquo;edition of&rdquo; &rarr; &ldquo;edition of 10 at &pound;500&rdquo;</span>
        </div>
        <div class="form-row">
          <label>Edition brackets</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="disp-edition-brackets"${dispEdBrackets ? ' checked' : ''}>
            Wrap edition info in brackets
          </label>
        </div>
      </div>
    </section>

    <div class="form-actions" style="padding-bottom:20px">
      <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
      <span id="settings-status" class="status-msg"></span>
    </div>`;

  // Populate Index Name previews now that the DOM is ready
  _refreshAllKaPreviews();

  // Load users table (admin + Cognito only)
  if (canAdmin() && _authMode === 'cognito') _loadUsersTable();
}

async function saveSettings() {
  const rawTokens = document.getElementById('cfg-honorific-tokens')?.value ?? '';
  const honorific_tokens = rawTokens.split(',').map(t => t.trim()).filter(Boolean);
  const statusEl = document.getElementById('settings-status');
  if (!statusEl) return;
  statusEl.textContent = 'Saving\u2026';
  statusEl.className = 'status-msg';
  try {
    await api('PUT', '/config', { honorific_tokens });
    _saveDisplayCfg(
      (document.getElementById('disp-currency')?.value      ?? '').trim() || '\u00a3',
      document.getElementById('disp-thousands-sep')?.value  ?? ',',
      Number(document.getElementById('disp-decimal-places')?.value ?? '0'),
      (document.getElementById('disp-edition-prefix')?.value ?? '').trim() || 'edition of',
      document.getElementById('disp-edition-brackets')?.checked ?? true,
    );
    statusEl.textContent = '\u2713 Saved';
    statusEl.className = 'status-msg success';
  } catch (e) {
    statusEl.textContent = `Error: ${esc(e.message)}`;
    statusEl.className = 'status-msg error';
  }
}

// ---------------------------------------------------------------------------
// User management (admin-only, Cognito mode)
// ---------------------------------------------------------------------------

async function _loadUsersTable() {
  const tbody = document.querySelector('#users-table tbody');
  if (!tbody) return;
  try {
    const users = await api('GET', '/users');
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">No users found.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map(u => {
      const statusBadge = u.enabled
        ? (u.status === 'CONFIRMED' ? '<span class="badge badge-ok">Active</span>'
           : `<span class="badge badge-warn">${esc(u.status)}</span>`)
        : '<span class="badge badge-error">Disabled</span>';
      const roleOpts = ['viewer', 'editor', 'admin'].map(r =>
        `<option value="${r}"${r === u.role ? ' selected' : ''}>${r}</option>`
      ).join('');
      return `<tr data-username="${esc(u.username)}">
        <td>${esc(u.email)}</td>
        <td><select class="user-role-select role-switcher role-${u.role}" onchange="_changeUserRole('${esc(u.username)}', this.value, this)" style="font-size:0.8rem;padding:2px 6px">${roleOpts}</select></td>
        <td>${statusBadge}</td>
        <td>
          ${u.enabled
            ? `<button class="btn btn-sm" onclick="_toggleUser('${esc(u.username)}', false)" style="font-size:0.75rem">Disable</button>`
            : `<button class="btn btn-sm" onclick="_toggleUser('${esc(u.username)}', true)" style="font-size:0.75rem">Enable</button>`}
          <button class="btn btn-sm" onclick="_showResetPassword('${esc(u.username)}')" style="font-size:0.75rem;margin-left:4px">Reset PW</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="error">${esc(e.message)}</td></tr>`;
  }
}

function _showCreateUserForm() {
  const slot = document.getElementById('create-user-form-slot');
  if (!slot) return;
  if (slot.innerHTML.trim()) { slot.innerHTML = ''; return; }  // toggle
  slot.innerHTML = `
    <div class="settings-form" style="background:#f9f9f9;padding:12px;border-radius:6px;margin-bottom:12px">
      <div class="form-row">
        <label style="width:120px">Email</label>
        <input id="new-user-email" type="email" placeholder="user@example.com" style="flex:1">
      </div>
      <div class="form-row" style="margin-top:6px">
        <label style="width:120px">Role</label>
        <select id="new-user-role">
          <option value="viewer">viewer</option>
          <option value="editor" selected>editor</option>
          <option value="admin">admin</option>
        </select>
      </div>
      <div class="form-row" style="margin-top:6px">
        <label style="width:120px">Temp password</label>
        <input id="new-user-password" type="text" placeholder="Min 12 chars, upper+lower+number" style="flex:1" value="">
      </div>
      <div class="form-actions" style="margin-top:8px">
        <button class="btn btn-primary btn-sm" onclick="_createUser()">Create User</button>
        <button class="btn btn-sm" onclick="document.getElementById('create-user-form-slot').innerHTML=''">Cancel</button>
        <span id="create-user-status" class="status-msg" style="margin-left:8px"></span>
      </div>
    </div>`;
  document.getElementById('new-user-email')?.focus();
}

async function _createUser() {
  const email = (document.getElementById('new-user-email')?.value ?? '').trim();
  const role = document.getElementById('new-user-role')?.value ?? 'viewer';
  const password = (document.getElementById('new-user-password')?.value ?? '').trim();
  const statusEl = document.getElementById('create-user-status');
  if (!email) { if (statusEl) statusEl.textContent = 'Email is required'; return; }
  if (password && password.length < 12) { if (statusEl) statusEl.textContent = 'Password must be at least 12 characters'; return; }
  if (statusEl) { statusEl.textContent = 'Creating\u2026'; statusEl.className = 'status-msg'; }
  try {
    const body = { email, role };
    if (password) body.temporary_password = password;
    await api('POST', '/users', body);
    document.getElementById('create-user-form-slot').innerHTML = '';
    await _loadUsersTable();
  } catch (e) {
    if (statusEl) { statusEl.textContent = e.message; statusEl.className = 'status-msg error'; }
  }
}

async function _changeUserRole(username, newRole, selectEl) {
  const origClass = selectEl.className;
  try {
    await api('PUT', `/users/${encodeURIComponent(username)}`, { role: newRole });
    selectEl.className = `user-role-select role-switcher role-${newRole}`;
  } catch (e) {
    alert('Failed to change role: ' + e.message);
    await _loadUsersTable();  // revert
  }
}

async function _toggleUser(username, enable) {
  try {
    await api('POST', `/users/${encodeURIComponent(username)}/${enable ? 'enable' : 'disable'}`);
    await _loadUsersTable();
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

function _showResetPassword(username) {
  const newPw = prompt(`Enter a new temporary password for this user (min 12 chars):`);
  if (!newPw) return;
  if (newPw.length < 12) { alert('Password must be at least 12 characters.'); return; }
  _doResetPassword(username, newPw);
}

async function _doResetPassword(username, tempPassword) {
  try {
    await api('POST', `/users/${encodeURIComponent(username)}/reset-password`, { temporary_password: tempPassword });
    alert('Password reset. The user will be asked to set a new password on next login.');
  } catch (e) {
    alert('Failed: ' + e.message);
  }
}

// ---------------------------------------------------------------------------
// Known Artists CRUD
// ---------------------------------------------------------------------------

/**
 * Check if a quals string contains an RA-type designation.
 * Mirrors backend is_ra_member() logic.
 */
function _isRaMember(quals) {
  if (!quals) return false;
  return /\b(?:EX OFFICIO|RA ELECT|HON RA|HONRA|PPRA|PRA|RA)\b/i.test(quals);
}

/**
 * Build a styled Index Name preview from a Known Artist row's fields.
 * Uses resolved values where set, falling back to match values.
 * Respects the "cleared" state (empty string = clear the field).
 */
function _kaPreviewIndexName(tr) {
  const v = (cls) => tr.querySelector(cls)?.value?.trim() || '';
  const matchFirst = v('.ka-match-first');
  const matchLast = v('.ka-match-last');
  const isCompany = tr.querySelector('.ka-company')?.checked || false;

  // Resolve each field: cleared → empty, has value → use it, otherwise → match value
  function resolve(inputCls, matchVal) {
    const cell = tr.querySelector(inputCls)?.closest('.ka-res-cell');
    const clearBtn = cell?.querySelector('.ka-clear-btn');
    if (clearBtn && clearBtn.classList.contains('ka-clear-active')) return ''; // explicitly cleared
    const val = tr.querySelector(inputCls)?.value?.trim() || '';
    return val || matchVal; // fall back to match value
  }

  const firstName = resolve('.ka-res-first', matchFirst);
  const lastName = resolve('.ka-res-last', matchLast);
  const quals = resolve('.ka-res-quals', '');
  const a2First = resolve('.ka-res-a2-first', '');
  const a2Last = resolve('.ka-res-a2-last', '');
  const a2Quals = resolve('.ka-res-a2-quals', '');
  const a1RaStyled = tr.querySelector('.ka-a1-ra')?.checked || false;
  const a2RaStyled = tr.querySelector('.ka-a2-ra')?.checked || false;
  const surname = lastName || firstName || '';
  if (!surname) return '<span class="muted">&mdash;</span>';

  const isRa = _isRaMember(quals);
  const commaParts = [];
  const nameParts = [];

  // Surname — RA styling uses per-artist flag
  if (a1RaStyled) {
    commaParts.push(`<span class="idx-ra-styled" title="RA Member styling">${esc(surname)}</span>`);
  } else {
    commaParts.push(esc(surname));
  }

  // First name (only when both names present and not a company)
  if (!isCompany && lastName && firstName) {
    commaParts.push(esc(firstName));
  }

  // Quals as a pill (space-separated, no comma)
  if (quals) {
    const pillClass = isRa ? 'honorifics-pill idx-ra-quals' : 'honorifics-pill';
    nameParts.push(`<span class="${pillClass}">${esc(quals)}</span>`);
  }

  // Additional artists from structured fields
  const suffixes = [];
  if (a2First || a2Last) {
    const parts = ['and'];
    if (a2First) parts.push(esc(a2First));
    if (a2Last) {
      if (a2RaStyled) parts.push(`<span class="idx-ra-styled">${esc(a2Last)}</span>`);
      else parts.push(esc(a2Last));
    }
    let suffix = parts.join(' ');
    if (a2Quals) {
      const pillClass = a2RaStyled ? 'honorifics-pill idx-ra-quals' : 'honorifics-pill';
      suffix += ` <span class="${pillClass}">${esc(a2Quals)}</span>`;
    }
    suffixes.push(suffix);
  }

  let result = commaParts.join(', ');
  if (nameParts.length) result += ' ' + nameParts.join(' ');
  if (suffixes.length) result += ', ' + suffixes.join(', ');
  return result;
}

/** Update the preview cell in a Known Artist row. */
function _updateKaPreview(tr) {
  const cell = tr.querySelector('.ka-preview');
  if (cell) cell.innerHTML = _kaPreviewIndexName(tr);
}

/** Refresh all Known Artist preview cells (call after table body changes). */
function _refreshAllKaPreviews() {
  document.querySelectorAll('#known-artists-table tbody tr').forEach(_updateKaPreview);
}

/**
 * Build a resolved field cell with a clear toggle.
 * Three states:
 *   null  → input empty, placeholder "no change", clear button inactive
 *   ""    → input disabled, shows "(cleared)", clear button active
 *   "val" → input has text, clear button inactive
 */
function _kaResolvedCell(cls, value, showClear) {
  const isCleared = value === '';
  const hasValue = value !== null && value !== '';
  const displayVal = hasValue ? esc(value) : '';
  const clearActive = isCleared ? ' ka-clear-active' : '';
  const clearBtn = showClear
    ? ` <button type="button" class="ka-clear-btn${clearActive}" title="${isCleared ? 'Undo clear (revert to no change)' : 'Clear this field (set to empty)'}" onclick="_toggleKaClear(this)">\u2298</button>`
    : '';
  return `<td class="ka-res-cell"><input type="text" class="${cls}" value="${displayVal}" placeholder="${isCleared ? '(cleared)' : 'no change'}" ${isCleared ? 'disabled' : ''} oninput="_onKaResInput(this)">${clearBtn}</td>`;
}

/** When user types in a resolved field, deactivate clear state. */
function _onKaResInput(input) {
  const clearBtn = input.parentElement.querySelector('.ka-clear-btn');
  if (clearBtn) clearBtn.classList.remove('ka-clear-active');
  input.disabled = false;
  input.placeholder = 'no change';
  _updateKaPreview(input.closest('tr'));
}

/** Toggle a resolved field between "no change" (null) and "cleared" (""). */
function _toggleKaClear(btn) {
  const input = btn.parentElement.querySelector('input[type="text"]');
  const isActive = btn.classList.toggle('ka-clear-active');
  if (isActive) {
    input.value = '';
    input.disabled = true;
    input.placeholder = '(cleared)';
    btn.title = 'Undo clear (revert to no change)';
  } else {
    input.disabled = false;
    input.placeholder = 'no change';
    btn.title = 'Clear this field (set to empty)';
  }
  _updateKaPreview(input.closest('tr'));
}

function _knownArtistRow(ka) {
  const id = ka.id || '';
  const ro = canEdit() ? '' : ' readonly';
  const dis = canEdit() ? '' : ' disabled';
  return `<tr data-ka-id="${esc(id)}">
    <td><input type="text" class="ka-match-first" value="${esc(ka.match_first_name ?? '')}" placeholder="" oninput="_updateKaPreview(this.closest('tr'))"${ro}></td>
    <td><input type="text" class="ka-match-last" value="${esc(ka.match_last_name ?? '')}" placeholder="" oninput="_updateKaPreview(this.closest('tr'))"${ro}></td>
    <td><input type="text" class="ka-match-quals" value="${esc(ka.match_quals ?? '')}" placeholder="" oninput="_updateKaPreview(this.closest('tr'))"${ro}></td>
    ${_kaResolvedCell('ka-res-first', ka.resolved_first_name, true)}
    ${_kaResolvedCell('ka-res-last', ka.resolved_last_name, true)}
    ${_kaResolvedCell('ka-res-quals', ka.resolved_quals, true)}
    ${_kaResolvedCell('ka-res-a2-first', ka.resolved_artist2_first_name, true)}
    ${_kaResolvedCell('ka-res-a2-last', ka.resolved_artist2_last_name, true)}
    ${_kaResolvedCell('ka-res-a2-quals', ka.resolved_artist2_quals, true)}
    <td style="text-align:center"><input type="checkbox" class="ka-a1-ra" onchange="_updateKaPreview(this.closest('tr'))"${ka.resolved_artist1_ra_styled ? ' checked' : ''}${dis}></td>
    <td style="text-align:center"><input type="checkbox" class="ka-a2-ra" onchange="_updateKaPreview(this.closest('tr'))"${ka.resolved_artist2_ra_styled ? ' checked' : ''}${dis}></td>
    <td style="text-align:center"><input type="checkbox" class="ka-company" onchange="_updateKaPreview(this.closest('tr'))"${ka.resolved_is_company ? ' checked' : ''}${dis}></td>
    <td class="ka-preview col-index-name"></td>
    <td><input type="text" class="ka-notes" value="${esc(ka.notes ?? '')}"${ro}></td>
    <td>
      ${ifEditor(`<button class="btn btn-sm btn-danger" onclick="deleteKnownArtist(this)" title="Delete">&times;</button>
      <button class="btn btn-sm" onclick="saveKnownArtistRow(this)" title="Save">&check;</button>`)}
    </td>
  </tr>`;
}

function addKnownArtistRow() {
  const tbody = document.querySelector('#known-artists-table tbody');
  tbody.insertAdjacentHTML('beforeend', _knownArtistRow({
    id: '', match_first_name: '', match_last_name: '', match_quals: '',
    resolved_first_name: '', resolved_last_name: '',
    resolved_quals: '',
    resolved_artist2_first_name: '', resolved_artist2_last_name: '',
    resolved_artist2_quals: '',
    resolved_artist1_ra_styled: false, resolved_artist2_ra_styled: false,
    resolved_is_company: false, notes: '',
  }));
}

function _readKaRow(tr) {
  const companyEl = tr.querySelector('.ka-company');
  // Checkbox: checked = true, unchecked = null (don't override).
  const isCompany = companyEl?.checked ? true : null;

  // Resolved fields: three states
  //   clear button active (input disabled) → "" (clear the field)
  //   input has text                       → text value
  //   input empty, not cleared             → null (no change)
  function resVal(cls) {
    const cell = tr.querySelector(cls)?.closest('.ka-res-cell') || tr;
    const input = cell.querySelector(cls) || tr.querySelector(cls);
    const clearBtn = cell.querySelector('.ka-clear-btn');
    if (clearBtn && clearBtn.classList.contains('ka-clear-active')) return '';
    const v = input?.value?.trim();
    return v || null;
  }

  const val = (cls) => tr.querySelector(cls)?.value?.trim() || null;
  const a1RaEl = tr.querySelector('.ka-a1-ra');
  const a2RaEl = tr.querySelector('.ka-a2-ra');
  return {
    match_first_name:              val('.ka-match-first'),
    match_last_name:               val('.ka-match-last'),
    match_quals:                   val('.ka-match-quals'),
    resolved_first_name:           resVal('.ka-res-first'),
    resolved_last_name:            resVal('.ka-res-last'),
    resolved_quals:                resVal('.ka-res-quals'),
    resolved_artist2_first_name:   resVal('.ka-res-a2-first'),
    resolved_artist2_last_name:    resVal('.ka-res-a2-last'),
    resolved_artist2_quals:        resVal('.ka-res-a2-quals'),
    resolved_artist1_ra_styled:    a1RaEl?.checked || null,
    resolved_artist2_ra_styled:    a2RaEl?.checked || null,
    resolved_is_company:           isCompany,
    notes:                         val('.ka-notes'),
  };
}

async function saveKnownArtistRow(btn) {
  const tr = btn.closest('tr');
  const id = tr.dataset.kaId;
  const body = _readKaRow(tr);
  const statusEl = document.getElementById('known-artists-status');
  try {
    let result;
    if (id) {
      result = await api('PATCH', `/known-artists/${id}`, body);
    } else {
      result = await api('POST', '/known-artists', body);
      tr.dataset.kaId = result.id;
    }
    if (statusEl) { statusEl.textContent = '\u2713 Saved'; statusEl.className = 'status-msg success'; }
  } catch (e) {
    if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.className = 'status-msg error'; }
  }
}

async function deleteKnownArtist(btn) {
  const tr = btn.closest('tr');
  const id = tr.dataset.kaId;
  const statusEl = document.getElementById('known-artists-status');
  if (!id) { tr.remove(); return; }
  if (!confirm('Delete this known artist entry?')) return;
  try {
    await api('DELETE', `/known-artists/${id}`);
    tr.remove();
    if (statusEl) { statusEl.textContent = '\u2713 Deleted'; statusEl.className = 'status-msg success'; }
  } catch (e) {
    if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.className = 'status-msg error'; }
  }
}

async function seedKnownArtists() {
  const statusEl = document.getElementById('known-artists-status');
  try {
    const result = await api('POST', '/known-artists/seed');
    if (statusEl) {
      statusEl.textContent = `\u2713 ${result.added} added, ${result.skipped} already present`;
      statusEl.className = 'status-msg success';
    }
    // Reload the table
    const knownArtists = await api('GET', '/known-artists');
    const tbody = document.querySelector('#known-artists-table tbody');
    tbody.innerHTML = knownArtists.map(ka => _knownArtistRow(ka)).join('');
    _refreshAllKaPreviews();
  } catch (e) {
    if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.className = 'status-msg error'; }
  }
}

// ---------------------------------------------------------------------------
// Settings helpers
// ---------------------------------------------------------------------------

function moveComponent(btn, dir) {
  const row = btn.closest('.component-row');
  const list = row.parentElement;
  if (dir === -1 && row.previousElementSibling) {
    list.insertBefore(row, row.previousElementSibling);
  } else if (dir === 1 && row.nextElementSibling) {
    list.insertBefore(row.nextElementSibling, row);
  }
}

// ---------------------------------------------------------------------------
// Templates list page
// ---------------------------------------------------------------------------

async function renderTemplates() {
  const app = document.getElementById('app');
  app.innerHTML = '<p class="loading" style="padding:40px 0">Loading templates&hellip;</p>';

  let lowTemplates, idxTemplates;
  try {
    [lowTemplates, idxTemplates] = await Promise.all([
      api('GET', '/templates'),
      api('GET', '/index/templates'),
    ]);
  } catch (e) { app.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }

  // --- List of Works templates table ---
  const lowRows = lowTemplates.map(t => {
    const created = t.created_at ? new Date(t.created_at).toLocaleDateString('en-GB') : '';
    const builtinBadge = t.is_builtin
      ? '<span class="badge badge-builtin">built-in</span>'
      : '';
    const editBtn = `<a class="btn btn-sm" href="#/templates/${esc(t.id)}/edit">${(t.is_builtin || !canEdit()) ? 'View' : 'Edit'}</a>`;
    const dupBtn  = ifEditor(`<button class="btn btn-sm" onclick="duplicateTemplate('${esc(t.id)}',this)">Duplicate</button>`);
    const delBtn  = t.is_builtin
      ? ''
      : ifAdmin(`<button class="btn btn-sm btn-danger" onclick="deleteTemplate('${esc(t.id)}','${esc(t.name)}',this)">Delete</button>`);
    return `<tr class="template-row">
      <td>${esc(t.name)} ${builtinBadge}</td>
      <td>${esc(created)}</td>
      <td class="table-actions">${editBtn} ${dupBtn} ${delBtn}</td>
    </tr>`;
  }).join('');

  // --- Index templates table ---
  const idxRows = idxTemplates.map(t => {
    const created = t.created_at ? new Date(t.created_at).toLocaleDateString('en-GB') : '';
    const builtinBadge = t.is_builtin
      ? '<span class="badge badge-builtin">built-in</span>'
      : '';
    const editBtn = `<a class="btn btn-sm" href="#/index-templates/${esc(t.id)}/edit">${(t.is_builtin || !canEdit()) ? 'View' : 'Edit'}</a>`;
    const dupBtn  = ifEditor(`<button class="btn btn-sm" onclick="duplicateIndexTemplate('${esc(t.id)}',this)">Duplicate</button>`);
    const delBtn  = t.is_builtin
      ? ''
      : ifAdmin(`<button class="btn btn-sm btn-danger" onclick="deleteIndexTemplate('${esc(t.id)}','${esc(t.name)}',this)">Delete</button>`);
    return `<tr class="template-row">
      <td>${esc(t.name)} ${builtinBadge}</td>
      <td>${esc(created)}</td>
      <td class="table-actions">${editBtn} ${dupBtn} ${delBtn}</td>
    </tr>`;
  }).join('');

  const emptyRow = '<tr><td colspan="3" style="padding:20px;color:var(--muted)">No templates yet.</td></tr>';

  app.innerHTML = `
    <h2 class="page-heading" style="margin-bottom:20px">Export Templates</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:20px">Templates define InDesign export settings. Choose one each time you export.</p>

    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <h3 style="margin:0">List of Works</h3>
      ${ifEditor('<a class="btn btn-sm btn-primary" href="#/templates/new/edit">+ New</a>')}
    </div>
    <section class="panel" style="padding:0;overflow:hidden;margin-bottom:28px">
      <table class="data-table" style="width:100%">
        <thead><tr><th>Name</th><th>Created</th><th></th></tr></thead>
        <tbody>${lowRows || emptyRow}</tbody>
      </table>
    </section>

    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <h3 style="margin:0">Artists Index</h3>
      ${ifEditor('<a class="btn btn-sm btn-primary" href="#/index-templates/new/edit">+ New</a>')}
    </div>
    <section class="panel" style="padding:0;overflow:hidden">
      <table class="data-table" style="width:100%">
        <thead><tr><th>Name</th><th>Created</th><th></th></tr></thead>
        <tbody>${idxRows || emptyRow}</tbody>
      </table>
    </section>`;
}

async function duplicateTemplate(id, btnEl) {
  const restore = btnLoading(btnEl, 'Duplicating');
  try {
    const created = await api('POST', `/templates/${id}/duplicate`);
    location.hash = `#/templates/${created.id}/edit`;
  } catch (e) {
    showToast(`Could not duplicate: ${e.message}`, 'error');
  } finally {
    restore();
  }
}

async function deleteTemplate(id, name, btnEl) {
  if (!confirm(`Delete template "${name}"? This cannot be undone.`)) return;
  const restore = btnLoading(btnEl, 'Deleting');
  try {
    await api('DELETE', `/templates/${id}`);
    showToast('Template deleted', 'success', 3000);
    renderTemplates();
  } catch (e) {
    showToast(`Could not delete: ${e.message}`, 'error');
  } finally {
    restore();
  }
}

// ---------------------------------------------------------------------------
// Index template CRUD
// ---------------------------------------------------------------------------

async function duplicateIndexTemplate(id, btnEl) {
  const restore = btnLoading(btnEl, 'Duplicating');
  try {
    const created = await api('POST', `/index/templates/${id}/duplicate`);
    location.hash = `#/index-templates/${created.id}/edit`;
  } catch (e) {
    showToast(`Could not duplicate: ${e.message}`, 'error');
  } finally {
    restore();
  }
}

async function deleteIndexTemplate(id, name, btnEl) {
  if (!confirm(`Delete template "${name}"? This cannot be undone.`)) return;
  const restore = btnLoading(btnEl, 'Deleting');
  try {
    await api('DELETE', `/index/templates/${id}`);
    showToast('Template deleted', 'success', 3000);
    renderTemplates();
  } catch (e) {
    showToast(`Could not delete: ${e.message}`, 'error');
  } finally {
    restore();
  }
}

// ---------------------------------------------------------------------------
// Index template edit page
// ---------------------------------------------------------------------------

async function renderIndexTemplateEdit(id) {
  const app = document.getElementById('app');
  app.innerHTML = '<p class="loading" style="padding:40px 0">Loading&hellip;</p>';

  const isNew = id === 'new';
  let cfg = {};
  let isBuiltin = false;

  if (!isNew) {
    try { cfg = await api('GET', `/index/templates/${id}`); }
    catch (e) { app.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    isBuiltin = cfg.is_builtin ?? false;
  }

  const ro = isBuiltin ? ' readonly disabled' : '';
  const roCheck = isBuiltin ? ' disabled' : '';

  const backLink = '<a href="#/templates" style="font-size:13px;color:var(--muted)">&larr; Back to templates</a>';
  const heading = isNew ? 'New Index Template' : esc(cfg.name ?? 'Edit Index Template');
  const builtinNote = isBuiltin
    ? `<div class="info-banner" style="margin-bottom:16px;padding:10px 14px;background:var(--bg-alt);border-radius:6px;font-size:13px;color:var(--muted)">
        <strong>Built-in template</strong> &mdash; read-only. <button class="btn btn-sm" onclick="duplicateIndexTemplate('${esc(id)}',this)">Duplicate to edit</button>
       </div>`
    : '';
  const saveBtn = isBuiltin
    ? ''
    : `<button class="btn btn-primary" onclick="saveIndexTemplate('${isNew ? 'new' : esc(id)}')">Save Template</button>`;

  const catSepOpts = [',', ';', ' '].map(v => {
    const label = v === ',' ? 'comma (,)' : v === ';' ? 'semicolon (;)' : 'space';
    const sel = (cfg.cat_no_separator ?? ',') === v ? ' selected' : '';
    return `<option value="${esc(v)}"${sel}>${label}</option>`;
  }).join('');

  const _idxSectionSepOpts = (val) => [
    ['paragraph',     '1 paragraph return (blank line)'],
    ['2paragraph',    '2 paragraph returns (blank lines)'],
    ['column_break',  'Column break'],
    ['frame_break',   'Frame break'],
    ['none',          'None (continuous)'],
    ['page_break',    'Page break'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');

  app.innerHTML = `
    <div style="margin-bottom:4px">${backLink}</div>
    <h2 class="page-heading">${heading}</h2>
    ${builtinNote}

    <section class="panel"><div class="settings-form"><div class="form-row">
      <label>Template name</label>
      <input id="idx-tmpl-name" type="text" value="${esc(isNew ? '' : (cfg.name ?? ''))}" placeholder="e.g. Summer Exhibition 2026"${ro}>
    </div></div></section>

    <h3 class="settings-group-heading">InDesign Paragraph Style</h3>
    <section class="panel">
      <div class="settings-form">
        <div class="form-row">
          <label>Entry paragraph</label>
          <input id="idx-tmpl-entry-style" type="text" value="${esc(cfg.entry_style ?? 'Index Text')}"${ro}>
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">InDesign Character Styles</h3>
    <section class="panel">
      <p style="color:var(--muted);font-size:12px;margin-bottom:14px">Leave blank to output plain text for that element.</p>
      <div class="settings-form">
        <div class="form-row"><label>RA member surname</label><input id="idx-tmpl-ra-surname" type="text" value="${esc(cfg.ra_surname_style ?? 'RA Member Cap Surname')}"${ro}></div>
        <div class="form-row"><label>RA caps (quals)</label><input id="idx-tmpl-ra-caps" type="text" value="${esc(cfg.ra_caps_style ?? 'RA Caps')}"${ro}></div>
        <div class="form-row"><label>Non-RA honorifics</label><input id="idx-tmpl-honorifics" type="text" value="${esc(cfg.honorifics_style ?? 'Small caps')}"${ro}></div>
        <div class="form-row"><label>Cat numbers</label><input id="idx-tmpl-cat-no" type="text" value="${esc(cfg.cat_no_style ?? 'Index works numbers')}"${ro}></div>
        <div class="form-row"><label>Expert numbers</label><input id="idx-tmpl-expert-numbers" type="text" value="${esc(cfg.expert_numbers_style ?? 'Expert numbers')}"${ro}></div>
      </div>
    </section>

    <h3 class="settings-group-heading">Behaviour</h3>
    <section class="panel">
      <div class="settings-form">
        <div class="form-row">
          <label>Quals lowercase</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="idx-tmpl-quals-lower"${(cfg.quals_lowercase !== false) ? ' checked' : ''}${roCheck}>
            Force qualifications to lowercase
          </label>
        </div>
        <div class="form-row">
          <label>Expert numbers</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="idx-tmpl-expert-enabled"${cfg.expert_numbers_enabled ? ' checked' : ''}${roCheck}>
            Apply Expert numbers style to leading digits in names
          </label>
        </div>
        <div class="form-row">
          <label>Cat number separator</label>
          <select id="idx-tmpl-cat-sep"${isBuiltin ? ' disabled' : ''}>${catSepOpts}</select>
        </div>
        <div class="form-row">
          <label>Cat sep. char style</label>
          <input id="idx-tmpl-cat-sep-style" type="text" value="${esc(cfg.cat_no_separator_style ?? '')}"${ro} placeholder="(none)">
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">Letter Groups</h3>
    <section class="panel">
      <p style="color:var(--muted);font-size:12px;margin-bottom:12px">Controls for alphabetical letter groups (A, B, C…) in the export.</p>
      <div class="settings-form">
        <div class="form-row">
          <label>Between letters</label>
          <select id="idx-tmpl-section-sep"${isBuiltin ? ' disabled' : ''}>${_idxSectionSepOpts(cfg.section_separator ?? 'paragraph')}</select>
        </div>
        <div class="form-row">
          <label>Separator style</label>
          <input id="idx-tmpl-section-sep-style" value="${esc(cfg.section_separator_style ?? '')}"${isBuiltin ? ' disabled' : ''} placeholder="(none)">
        </div>
        <div class="form-row">
          <label>Letter headings</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="idx-tmpl-letter-heading" ${cfg.letter_heading_enabled ? 'checked' : ''}${isBuiltin ? ' disabled' : ''}>
            Insert a heading line (A, B, C\u2026) at the start of each letter group
          </label>
        </div>
        <div class="form-row">
          <label>Heading style</label>
          <input id="idx-tmpl-letter-heading-style" value="${esc(cfg.letter_heading_style ?? '')}"${isBuiltin ? ' disabled' : ''} placeholder="(uses entry style)">
        </div>
      </div>
    </section>

    <div class="form-actions" style="padding-bottom:20px">
      ${saveBtn}
      <span id="idx-tmpl-status" class="status-msg"></span>
    </div>`;
}

async function saveIndexTemplate(id) {
  const nameEl = document.getElementById('idx-tmpl-name');
  const name = (nameEl?.value ?? '').trim();
  if (!name) { showToast('Please enter a template name.', 'error'); nameEl?.focus(); return; }

  const body = {
    name,
    entry_style:          (document.getElementById('idx-tmpl-entry-style')?.value ?? '').trim() || 'Index Text',
    ra_surname_style:     (document.getElementById('idx-tmpl-ra-surname')?.value  ?? '').trim() || 'RA Member Cap Surname',
    ra_caps_style:        (document.getElementById('idx-tmpl-ra-caps')?.value     ?? '').trim() || 'RA Caps',
    cat_no_style:         (document.getElementById('idx-tmpl-cat-no')?.value      ?? '').trim(),
    honorifics_style:     (document.getElementById('idx-tmpl-honorifics')?.value  ?? '').trim(),
    expert_numbers_style: (document.getElementById('idx-tmpl-expert-numbers')?.value ?? '').trim(),
    quals_lowercase:       document.getElementById('idx-tmpl-quals-lower')?.checked ?? true,
    expert_numbers_enabled: document.getElementById('idx-tmpl-expert-enabled')?.checked ?? false,
    cat_no_separator:      document.getElementById('idx-tmpl-cat-sep')?.value ?? ',',
    cat_no_separator_style: (document.getElementById('idx-tmpl-cat-sep-style')?.value ?? '').trim(),
    section_separator:      document.getElementById('idx-tmpl-section-sep')?.value ?? 'paragraph',
    section_separator_style:(document.getElementById('idx-tmpl-section-sep-style')?.value ?? '').trim(),
    letter_heading_enabled:  document.getElementById('idx-tmpl-letter-heading')?.checked ?? false,
    letter_heading_style:   (document.getElementById('idx-tmpl-letter-heading-style')?.value ?? '').trim(),
  };

  const statusEl = document.getElementById('idx-tmpl-status');
  if (statusEl) { statusEl.textContent = 'Saving\u2026'; statusEl.className = 'status-msg'; }
  try {
    let result;
    if (id === 'new') {
      result = await api('POST', '/index/templates', body);
      location.hash = `#/index-templates/${result.id}/edit`;
    } else {
      await api('PUT', `/index/templates/${id}`, body);
      if (statusEl) { statusEl.textContent = '\u2713 Saved'; statusEl.className = 'status-msg success'; }
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = `Error: ${esc(e.message)}`; statusEl.className = 'status-msg error'; }
  }
}

// ---------------------------------------------------------------------------
// Template edit page
// ---------------------------------------------------------------------------

async function renderTemplateEdit(id) {
  const app = document.getElementById('app');
  app.innerHTML = '<p class="loading" style="padding:40px 0">Loading&hellip;</p>';

  const isNew = id === 'new';
  let cfg = {};
  let isBuiltin = false;

  if (!isNew) {
    try { cfg = await api('GET', `/templates/${id}`); }
    catch (e) { app.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    isBuiltin = cfg.is_builtin ?? false;
  }

  // helpers
  const _sepOpts = (val) => [
    ['none',         'none'],
    ['space',        'space'],
    ['tab',          'tab'],
    ['right_tab',    'right-indent tab (uses tab stop)'],
    ['soft_return',  'soft return (\\n)'],
    ['hard_return',  'hard return'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');

  const _sectionSepOpts = (val) => [
    ['paragraph',    'Paragraph return (blank line)'],
    ['column_break', 'Column break'],
    ['frame_break',  'Frame break'],
    ['page_break',   'Page break'],
    ['none',         'None (continuous)'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');

  const sepOpts = (val) => [
    [',', ', &nbsp; 1,000'],
    ['.', '. &nbsp; 1.000'],
    [' ', 'space &nbsp; 1 000'],
    ['',  'none &nbsp; 1000'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');

  const dpOpts = (val) => [
    ['0', '0 &mdash; 1,500'],
    ['2', '2 &mdash; 1,500.00'],
  ].map(([v, label]) => `<option value="${v}"${String(val) === v ? ' selected' : ''}>${label}</option>`).join('');

  // components
  const COMP_LABELS = {
    work_number: 'Work Number', artist: 'Artist', title: 'Title',
    edition: 'Edition info', artwork: 'Artwork number', price: 'Price', medium: 'Medium',
  };
  const defaultComponents = [
    {field:'work_number',separator_after:'tab',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'artist',separator_after:'tab',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'title',separator_after:'tab',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'edition',separator_after:'tab',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'artwork',separator_after:'tab',omit_sep_when_empty:true,enabled:false,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'price',separator_after:'none',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
    {field:'medium',separator_after:'none',omit_sep_when_empty:true,enabled:true,max_line_chars:null,next_component_position:'end_of_text',balance_lines:false},
  ];
  const savedComponents = cfg.components ?? defaultComponents;
  const savedFields = new Set(savedComponents.map(c => c.field));
  const mergedComponents = [
    ...savedComponents,
    ...defaultComponents.filter(c => !savedFields.has(c.field)),
  ];

  const ro = isBuiltin ? ' readonly disabled' : '';
  const roCheck = isBuiltin ? ' disabled' : '';

  const componentRowsHTML = mergedComponents.map(c => {
    const label = COMP_LABELS[c.field] ?? c.field;
    const enabled = c.enabled ?? true;
    const maxChars = c.max_line_chars ?? '';
    const nextPos = c.next_component_position ?? 'end_of_text';
    const balance = c.balance_lines ?? false;
    const posDisabled = (maxChars === '' || maxChars === null) ? 'disabled' : '';
    const balDisabled = posDisabled;
    return `
    <div class="component-row" data-field="${esc(c.field)}" style="opacity:${enabled ? 1 : 0.45}">
      <div class="component-main">
        <div class="component-handle">
          <button type="button" class="btn-icon" onclick="moveComponent(this,-1)" title="Move up"${isBuiltin ? ' disabled' : ''}>▲</button>
          <button type="button" class="btn-icon" onclick="moveComponent(this,1)" title="Move down"${isBuiltin ? ' disabled' : ''}>▼</button>
        </div>
        <span class="component-label">${esc(label)}</span>
        <select class="component-sep"${isBuiltin ? ' disabled' : ''}>${_sepOpts(c.separator_after)}</select>
        <label class="inline-check"><input type="checkbox" class="component-omit-sep" ${(c.omit_sep_when_empty ?? true) ? 'checked' : ''}${roCheck}> omit when empty</label>
        <label class="component-toggle" title="Include this component in the export">
          <input type="checkbox" class="component-enabled" ${enabled ? 'checked' : ''}${roCheck}
            onchange="this.closest('.component-row').style.opacity = this.checked ? 1 : 0.45"> include
        </label>
      </div>
      <div class="component-wrap-opts">
        <label>max chars/line <input type="number" class="component-max-chars" min="1" style="width:4.5em"
          value="${maxChars}" placeholder="none"${ro}
          oninput="const r=this.closest('.component-row');r.querySelector('.component-next-pos').disabled=!this.value;r.querySelector('.component-balance').disabled=!this.value"></label>
        <label>next component at
          <select class="component-next-pos" ${posDisabled}${isBuiltin ? ' disabled' : ''}>
            <option value="end_of_text" ${nextPos==='end_of_text'?'selected':''}>end of text</option>
            <option value="end_of_first_line" ${nextPos==='end_of_first_line'?'selected':''}>end of first line</option>
          </select>
        </label>
        <label class="inline-check"><input type="checkbox" class="component-balance" ${balance?'checked':''}${roCheck} ${balDisabled}> balance lines</label>
      </div>
    </div>`;
  }).join('');

  const backLink = `<a href="#/templates" style="font-size:13px;color:var(--muted)">&larr; Back to templates</a>`;
  const heading = isNew ? 'New Template' : esc(cfg.name ?? 'Edit Template');
  const builtinNote = isBuiltin
    ? `<div class="info-banner" style="margin-bottom:16px;padding:10px 14px;background:var(--bg-alt);border-radius:6px;font-size:13px;color:var(--muted)">
        <strong>Built-in template</strong> &mdash; read-only. <button class="btn btn-sm" onclick="duplicateTemplate('${esc(id)}',this)">Duplicate to edit</button>
       </div>`
    : '';
  const saveBtn = isBuiltin
    ? ''
    : `<button class="btn btn-primary" onclick="saveTemplate('${isNew ? 'new' : esc(id)}')">Save Template</button>`;

  app.innerHTML = `
    <div style="margin-bottom:4px">${backLink}</div>
    <h2 class="page-heading">${heading}</h2>
    ${builtinNote}

    ${isNew ? `<section class="panel"><div class="settings-form"><div class="form-row">
      <label>Template name</label>
      <input id="tmpl-name" type="text" placeholder="e.g. Summer Exhibition 2025">
    </div></div></section>` : ''}
    ${!isNew ? `<section class="panel"><div class="settings-form"><div class="form-row">
      <label>Template name</label>
      <input id="tmpl-name" type="text" value="${esc(cfg.name ?? '')}"${ro}>
    </div></div></section>` : ''}

    <h3 class="settings-group-heading">Formatting</h3>
    <section class="panel">
      <div class="settings-form">
        <div class="form-row">
          <label>Currency symbol</label>
          <input id="tmpl-currency" type="text" value="${esc(cfg.currency_symbol ?? '\u00a3')}" style="max-width:80px"${ro}>
        </div>
        <div class="form-row">
          <label>Thousands separator</label>
          <select id="tmpl-thousands-sep"${isBuiltin ? ' disabled' : ''}>${sepOpts(cfg.thousands_separator ?? ',')}</select>
        </div>
        <div class="form-row">
          <label>Decimal places</label>
          <select id="tmpl-decimal-places"${isBuiltin ? ' disabled' : ''}>${dpOpts(cfg.decimal_places ?? 0)}</select>
        </div>
        <div class="form-row">
          <label>Edition prefix</label>
          <input id="tmpl-edition-prefix" type="text" value="${esc(cfg.edition_prefix ?? 'edition of')}"${ro}>
          <span class="form-hint">e.g. &ldquo;edition of&rdquo; &rarr; &ldquo;edition of 10 at &pound;500&rdquo;</span>
        </div>
        <div class="form-row">
          <label>Edition brackets</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="tmpl-edition-brackets"${cfg.edition_brackets !== false ? ' checked' : ''}${roCheck}>
            Wrap edition info in brackets
          </label>
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">InDesign Paragraph Styles</h3>
    <section class="panel">
      <div class="settings-form">
        <div class="form-row">
          <label>Section heading</label>
          <input id="tmpl-section-style" type="text" value="${esc(cfg.section_style ?? 'SectionTitle')}"${ro}>
        </div>
        <div class="form-row">
          <label>Entry paragraph</label>
          <input id="tmpl-entry-style" type="text" value="${esc(cfg.entry_style ?? 'CatalogueEntry')}"${ro}>
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">InDesign Character Styles</h3>
    <section class="panel">
      <p style="color:var(--muted);font-size:12px;margin-bottom:14px">Leave blank to output plain text for that field.</p>
      <div class="settings-form">
        <div class="form-row"><label>Cat number</label><input id="tmpl-cat-no-style" type="text" value="${esc(cfg.cat_no_style ?? '')}"${ro}></div>
        <div class="form-row"><label>Artist name</label><input id="tmpl-artist-style" type="text" value="${esc(cfg.artist_style ?? '')}"${ro}></div>
        <div class="form-row">
          <label>Honorifics</label>
          <div class="form-row-controls">
            <input id="tmpl-honorifics-style" type="text" value="${esc(cfg.honorifics_style ?? '')}"${ro}>
            <label class="inline-check"><input id="tmpl-honorifics-lowercase" type="checkbox" ${cfg.honorifics_lowercase ? 'checked' : ''}${roCheck}> force lowercase</label>
          </div>
        </div>
        <div class="form-row"><label>Title</label><input id="tmpl-title-style" type="text" value="${esc(cfg.title_style ?? '')}"${ro}></div>
        <div class="form-row"><label>Price</label><input id="tmpl-price-style" type="text" value="${esc(cfg.price_style ?? '')}"${ro}></div>
        <div class="form-row"><label>Medium</label><input id="tmpl-medium-style" type="text" value="${esc(cfg.medium_style ?? '')}"${ro}></div>
        <div class="form-row"><label>Artwork number</label><input id="tmpl-artwork-style" type="text" value="${esc(cfg.artwork_style ?? '')}"${ro}></div>
      </div>
    </section>

    <h3 class="settings-group-heading">Section Separator</h3>
    <section class="panel">
      <p style="color:var(--muted);font-size:12px;margin-bottom:12px">What to insert between gallery sections in the export.</p>
      <div class="settings-form">
        <div class="form-row">
          <label>Between sections</label>
          <select id="tmpl-section-sep"${isBuiltin ? ' disabled' : ''}>${_sectionSepOpts(cfg.section_separator ?? 'paragraph')}</select>
        </div>
        <div class="form-row">
          <label>Separator style</label>
          <input id="tmpl-section-sep-style" value="${esc(cfg.section_separator_style ?? '')}"${isBuiltin ? ' disabled' : ''} placeholder="(none)">
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">Entry Layout</h3>
    <section class="panel">
      <p style="color:var(--muted);font-size:12px;margin-bottom:16px">Drag to reorder. Separator fires after each non-empty component. Right-align tab = <code>\y</code>, soft return = <code>\n</code>.</p>
      <div class="form-row" style="margin-bottom:12px">
        <label>Leading separator</label>
        <select id="tmpl-leading-sep"${isBuiltin ? ' disabled' : ''}>${_sepOpts(cfg.leading_separator ?? 'none')}</select>
      </div>
      <div id="tmpl-components" class="component-list">${componentRowsHTML}</div>
      <div class="form-row" style="margin-top:12px">
        <label>Trailing separator</label>
        <select id="tmpl-trailing-sep"${isBuiltin ? ' disabled' : ''}>${_sepOpts(cfg.trailing_separator ?? 'none')}</select>
      </div>
      <div class="form-row" style="margin-top:8px">
        <label class="inline-check" style="text-transform:none;font-size:13px">
          <input type="checkbox" id="tmpl-final-sep-from-last"
            ${(cfg.final_sep_from_last_component ?? false) ? 'checked' : ''}${roCheck}>
          When last component is omitted, adopt its separator for the final non-empty field
        </label>
      </div>
    </section>

    <div class="form-actions" style="padding-bottom:20px">
      ${saveBtn}
      <span id="tmpl-status" class="status-msg"></span>
    </div>`;
}

async function saveTemplate(id) {
  const nameEl = document.getElementById('tmpl-name');
  const name = (nameEl?.value ?? '').trim();
  if (!name) { showToast('Please enter a template name.', 'error'); nameEl?.focus(); return; }

  const components = Array.from(
    document.querySelectorAll('#tmpl-components .component-row')
  ).map(row => {
    const rawMax = row.querySelector('.component-max-chars')?.value;
    return {
      field: row.dataset.field,
      separator_after: row.querySelector('.component-sep')?.value ?? 'none',
      omit_sep_when_empty: row.querySelector('.component-omit-sep')?.checked ?? true,
      enabled: row.querySelector('.component-enabled')?.checked ?? true,
      max_line_chars: rawMax ? parseInt(rawMax, 10) : null,
      next_component_position: row.querySelector('.component-next-pos')?.value ?? 'end_of_text',
      balance_lines: row.querySelector('.component-balance')?.checked ?? false,
    };
  });

  const body = {
    name,
    currency_symbol:     (document.getElementById('tmpl-currency')?.value          ?? '').trim() || '\u00a3',
    thousands_separator:  document.getElementById('tmpl-thousands-sep')?.value      ?? ',',
    decimal_places:      Number(document.getElementById('tmpl-decimal-places')?.value ?? '0'),
    edition_prefix:      (document.getElementById('tmpl-edition-prefix')?.value     ?? '').trim() || 'edition of',
    edition_brackets:     document.getElementById('tmpl-edition-brackets')?.checked ?? true,
    section_style:       (document.getElementById('tmpl-section-style')?.value      ?? '').trim() || 'SectionTitle',
    entry_style:         (document.getElementById('tmpl-entry-style')?.value        ?? '').trim() || 'CatalogueEntry',
    section_separator:    document.getElementById('tmpl-section-sep')?.value        ?? 'paragraph',
    section_separator_style: (document.getElementById('tmpl-section-sep-style')?.value ?? '').trim(),
    cat_no_style:        (document.getElementById('tmpl-cat-no-style')?.value       ?? '').trim(),
    artist_style:        (document.getElementById('tmpl-artist-style')?.value       ?? '').trim(),
    honorifics_style:    (document.getElementById('tmpl-honorifics-style')?.value   ?? '').trim(),
    honorifics_lowercase: document.getElementById('tmpl-honorifics-lowercase')?.checked ?? false,
    title_style:         (document.getElementById('tmpl-title-style')?.value        ?? '').trim(),
    price_style:         (document.getElementById('tmpl-price-style')?.value        ?? '').trim(),
    medium_style:        (document.getElementById('tmpl-medium-style')?.value       ?? '').trim(),
    artwork_style:       (document.getElementById('tmpl-artwork-style')?.value      ?? '').trim(),
    leading_separator:    document.getElementById('tmpl-leading-sep')?.value        ?? 'none',
    trailing_separator:   document.getElementById('tmpl-trailing-sep')?.value       ?? 'none',
    final_sep_from_last_component: document.getElementById('tmpl-final-sep-from-last')?.checked ?? false,
    components,
  };

  const statusEl = document.getElementById('tmpl-status');
  if (statusEl) { statusEl.textContent = 'Saving\u2026'; statusEl.className = 'status-msg'; }
  try {
    let result;
    if (id === 'new') {
      result = await api('POST', '/templates', body);
      location.hash = `#/templates/${result.id}/edit`;
    } else {
      await api('PUT', `/templates/${id}`, body);
      if (statusEl) { statusEl.textContent = '\u2713 Saved'; statusEl.className = 'status-msg success'; }
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = `Error: ${esc(e.message)}`; statusEl.className = 'status-msg error'; }
  }
}

// ---------------------------------------------------------------------------
// Import list
// ---------------------------------------------------------------------------

async function renderList() {
  document.getElementById('app').innerHTML = `
    ${ifEditor(`<section class="panel">
      <h3>Import List of Works Excel File</h3>
      <form id="upload-form" class="upload-form">
        <input type="file" id="file-input" accept=".xlsx,.xls" required>
        <button type="submit" class="btn btn-primary">Upload</button>
      </form>
      <p id="upload-status" class="status-msg" style="margin-top:8px"></p>
    </section>`)}
    <section class="panel">
      <h3>List of Works Imports</h3>
      <div id="imports-list">Loading&hellip;</div>
    </section>`;

  document.getElementById('upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = document.getElementById('file-input').files[0];
    if (file) await handleUpload(file);
  });

  await loadImportList();
}

async function loadImportList() {
  const container = document.getElementById('imports-list');
  try {
    const imports = await api('GET', '/imports');
    if (!imports.length) {
      container.innerHTML = '<p class="muted">No imports yet.</p>';
      return;
    }
    const rows = imports.map(i => {
      const ovrCell = i.override_count > 0
        ? `${i.override_count}<br><span class="muted" style="font-size:11px">${esc(formatDate(i.last_override_at))}</span>`
        : `<span class="muted">&mdash;</span>`;
      return `
      <tr>
        <td><code class="import-id" title="${esc(i.id)}">${esc(i.id.slice(0, 8))}&hellip;</code></td>
        <td><a class="link" href="#/import/${esc(i.id)}">${esc(i.filename)}</a></td>
        <td>${esc(formatDate(i.uploaded_at))}</td>
        <td class="num">${i.sections}</td>
        <td class="num">${i.works}</td>
        <td class="num">${ovrCell}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="navigate('#/import/${esc(i.id)}')">View</button>
          ${ifAdmin(`<button class="btn btn-sm btn-danger" onclick="handleDelete('${esc(i.id)}', '${esc(i.filename.replace(/'/g, ''))}', this)">Delete</button>`)}
        </td>
      </tr>`;
    }).join('');
    container.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>ID</th><th>Filename</th><th>Uploaded</th>
          <th class="num">Sections</th><th class="num">Works</th>
          <th class="num">Overrides</th>
          <th>Actions</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (err) {
    container.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

async function handleUpload(file) {
  const statusEl = document.getElementById('upload-status');
  const uploadBtn = document.querySelector('#upload-form .btn-primary');
  const restore = btnLoading(uploadBtn, 'Uploading');
  statusEl.textContent = 'Uploading\u2026';
  statusEl.className = 'status-msg';
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/import', { method: 'POST', body: form, headers: _apiHeaders() });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) { const t = await res.text(); throw new Error(t); }
    const data = await res.json();
    statusEl.textContent = `\u2713 Uploaded (ID: ${data.import_id})`;
    statusEl.className = 'status-msg success';
    document.getElementById('file-input').value = '';
    await loadImportList();
  } catch (err) {
    statusEl.textContent = `Upload failed: ${err.message}`;
    statusEl.className = 'status-msg error';
  } finally {
    restore();
  }
}

async function handleDelete(id, filename, btnEl) {
  if (!confirm(`Delete import \u201c${filename}\u201d? This cannot be undone.`)) return;
  const restore = btnLoading(btnEl, 'Deleting');
  try {
    await api('DELETE', `/imports/${id}`);
    showToast('Import deleted', 'success', 3000);
    await loadImportList();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

async function handleReimport(importId, file) {
  const statusEl = document.getElementById('reimport-status');
  const btn = document.querySelector('#reimport-form .btn-primary');
  const restore = btnLoading(btn, 'Re-importing');
  statusEl.textContent = 'Re-importing\u2026';
  statusEl.className = 'status-msg';
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/imports/${importId}/reimport`, {
      method: 'PUT', body: form, headers: _apiHeaders(),
    });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) { const t = await res.text(); throw new Error(t); }
    const data = await res.json();
    const parts = [];
    if (data.matched)  parts.push(`${data.matched} matched`);
    if (data.added)    parts.push(`${data.added} added`);
    if (data.removed)  parts.push(`${data.removed} removed`);
    if (data.overrides_preserved) parts.push(`${data.overrides_preserved} overrides preserved`);
    const summary = parts.join(', ') || 'No changes';
    statusEl.textContent = `\u2713 Re-imported: ${summary}`;
    statusEl.className = 'status-msg success';
    showToast(`Re-import complete: ${summary}`, 'success', 5000);
    document.getElementById('reimport-file').value = '';
    // Refresh the detail view to show updated data
    await renderDetail(importId);
  } catch (err) {
    statusEl.textContent = `Re-import failed: ${err.message}`;
    statusEl.className = 'status-msg error';
    showToast(`Re-import failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

function formatDate(iso) {
  return new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}

function formatPrice(price_numeric, price_text, cfg) {
  if (price_numeric != null) {
    const dp  = (cfg?.decimal_places    ?? 0);
    const sep = (cfg?.thousands_separator ?? ',');
    const sym = (cfg?.currency_symbol    ?? '£');
    const fixed = Number(price_numeric).toFixed(dp);
    const [intPart, ...decParts] = fixed.split('.');
    const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
    return sym + grouped + (decParts.length ? '.' + decParts[0] : '');
  }
  return price_text ?? '';
}

// ---------------------------------------------------------------------------
// Display (HTML preview) formatting config — stored in localStorage only
// ---------------------------------------------------------------------------

function _getDisplayCfg() {
  try {
    const d = JSON.parse(localStorage.getItem('ra_display_cfg') || '{}');
    return {
      currency_symbol:     d.currency_symbol     ?? '\u00a3',
      thousands_separator: d.thousands_separator ?? ',',
      decimal_places:      d.decimal_places      ?? 0,
      edition_prefix:      d.edition_prefix      ?? 'edition of',
      edition_brackets:    d.edition_brackets    ?? true,
    };
  } catch {
    return { currency_symbol: '\u00a3', thousands_separator: ',', decimal_places: 0, edition_prefix: 'edition of', edition_brackets: true };
  }
}

function _saveDisplayCfg(currency_symbol, thousands_separator, decimal_places, edition_prefix, edition_brackets) {
  localStorage.setItem('ra_display_cfg', JSON.stringify(
    { currency_symbol, thousands_separator, decimal_places, edition_prefix, edition_brackets }
  ));
}

// ---------------------------------------------------------------------------
// Import detail
// ---------------------------------------------------------------------------

let _expandedWorkId = null;
let _workCache = {}; // workId -> work object, populated when sections render

/** Restore override button text when closing the form. */
function _restoreOverrideBtn(btn) {
  if (!btn) return;
  const hasOv = btn.dataset.hasOverride === '1';
  btn.textContent = hasOv ? 'Edit \u270e' : 'Edit';
  btn.className = `btn btn-xs ${hasOv ? 'btn-warning' : 'btn-secondary'}`;
}

async function renderDetail(importId) {
  _expandedWorkId = null;
  document.getElementById('app').innerHTML = `
    <div class="breadcrumb"><a href="#/">\u2190 All Imports</a></div>
    <h2 class="page-heading" id="detail-heading">Loading\u2026</h2>
    ${ifEditor(`<section class="panel reimport-panel">
      <h3>Update Import</h3>
      <p class="muted" style="font-size:12px;margin-bottom:10px">Select an updated version of the same spreadsheet. Existing overrides and exclusions will be preserved where possible.</p>
      <form id="reimport-form" class="upload-form">
        <input type="file" id="reimport-file" accept=".xlsx,.xls" required>
        <button type="submit" class="btn btn-primary">Re-import</button>
      </form>
      <p id="reimport-warn" class="status-msg" style="margin-top:4px;display:none"></p>
      <p id="reimport-status" class="status-msg" style="margin-top:8px"></p>
    </section>`)}
    <section class="panel">
      <h3>Export</h3>
      <div id="export-panel-${esc(importId)}"><p class="loading" style="padding:4px 0">Loading templates\u2026</p></div>
    </section>
    <section class="panel" id="warnings-panel"><p class="loading">Loading warnings\u2026</p></section>
    <section class="panel">
      <h3>Works</h3>
      <div class="works-filter-bar">
        <input type="text" id="works-filter" class="works-filter-input" placeholder="Filter by cat no, artist, or title\u2026" autocomplete="off">
        <span id="works-filter-count" class="works-filter-count"></span>
      </div>
      <div id="sections-container"><p class="loading">Loading\u2026</p></div>
    </section>
    <section class="panel" id="audit-panel"><p class="loading">Loading audit log\u2026</p></section>`;

  // Wire up re-import form
  document.getElementById('reimport-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = document.getElementById('reimport-file').files[0];
    if (file) await handleReimport(importId, file);
  });

  // Fetch import metadata for filename mismatch detection + heading
  let originalFilename = null;
  try {
    const allImports = await api('GET', '/imports');
    const thisImport = allImports.find(i => i.id === importId);
    if (thisImport) originalFilename = thisImport.filename;
  } catch (_) { /* non-critical */ }

  // Show filename in heading
  document.getElementById('detail-heading').textContent =
    originalFilename
      ? `Import \u2013 ${originalFilename}`
      : `Import \u2013 ${importId.slice(0, 8)}\u2026`;

  // Warn on filename mismatch
  const fileInput = document.getElementById('reimport-file');
  const warnEl = document.getElementById('reimport-warn');
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      const selected = fileInput.files[0];
      if (!selected || !originalFilename) { warnEl.style.display = 'none'; return; }
      if (selected.name !== originalFilename) {
        warnEl.textContent = `\u26a0 Selected file "${selected.name}" differs from the original "${originalFilename}". This will replace the current data.`;
        warnEl.className = 'status-msg warning';
        warnEl.style.display = '';
      } else {
        warnEl.style.display = 'none';
      }
    });
  }

  const cfg = _getDisplayCfg();

  const [sections, warnings, templates, auditLogs] = await Promise.all([
    api('GET', `/imports/${importId}/sections`).catch(e => ({ _error: e.message })),
    api('GET', `/imports/${importId}/warnings`).catch(() => []),
    api('GET', '/templates').catch(() => []),
    api('GET', `/imports/${importId}/audit-log`).catch(() => []),
  ]);

  // Populate template picker — restore last-used template from localStorage
  const _lastTmplKey = 'catalogue_last_template';
  const _lastTmplId = localStorage.getItem(_lastTmplKey) || '';
  const tmplOpts = templates.length
    ? templates.map(t => `<option value="${esc(t.id)}"${t.id === _lastTmplId ? ' selected' : ''}>${esc(t.name)}</option>`).join('')
    : '<option value="" disabled>No templates \u2014 create one in Templates</option>';
  const panelEl = document.getElementById(`export-panel-${importId}`);
  if (panelEl) panelEl.innerHTML = `
    <div class="export-buttons">
      <div class="template-row">
        <label class="export-template-label">Template</label>
        <select id="tmpl-select-${esc(importId)}"${templates.length ? '' : ' disabled'}>${tmplOpts}</select>
        <button class="btn btn-secondary" onclick="downloadExportWithTemplate('${esc(importId)}','tags','txt',null,this)">InDesign Tags (.txt)</button>
      </div>
      <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','json','json',null,null,this)">JSON</button>
      <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','xml','xml',null,null,this)">XML</button>
      <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','csv','csv',null,null,this)">CSV</button>
      <button class="btn btn-secondary btn-diff" onclick="showExportDiff('${esc(importId)}',this)">Show changes since last export</button>
    </div>
    <div id="diff-panel-${esc(importId)}"></div>`;

  // Persist template choice on change
  const _tmplSel = document.getElementById(`tmpl-select-${importId}`);
  if (_tmplSel) _tmplSel.addEventListener('change', () => localStorage.setItem(_lastTmplKey, _tmplSel.value));

  renderWarningsPanel(warnings);

  if (sections._error) {
    document.getElementById('sections-container').innerHTML = `<p class="error">${esc(sections._error)}</p>`;
    return;
  }
  renderSections(importId, sections, cfg);
  renderAuditPanel(auditLogs);
}

// ---------------------------------------------------------------------------
// Warnings panel state (module-level so filter toggles survive re-renders)
// ---------------------------------------------------------------------------
let _warningsAll = [];
let _hiddenWarningTypes = new Set();

function renderWarningsPanel(warnings) {
  _warningsAll = warnings;
  _hiddenWarningTypes = new Set();
  _buildWarningsPanel();
}

function _buildWarningsPanel() {
  const warnings = _warningsAll;
  const panel = document.getElementById('warnings-panel');
  if (!warnings.length) {
    panel.innerHTML = '<p class="no-warnings">\u2713 No validation warnings</p>';
    return;
  }
  panel.classList.add('has-warnings');

  // Summary counts by type
  const counts = {};
  for (const w of warnings) {
    counts[w.warning_type] = (counts[w.warning_type] || 0) + 1;
  }
  const summaryBadges = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => {
      const muted = _hiddenWarningTypes.has(type);
      return `<button type="button" class="badge badge-warning warning-filter-btn${muted ? ' badge-muted' : ''}" data-type="${esc(type)}" title="${muted ? 'Click to show' : 'Click to hide'}">${esc(type)}: ${n}</button>`;
    }).join('');

  // Detailed rows — filtered by hidden types
  const visible = warnings.filter(w => !_hiddenWarningTypes.has(w.warning_type));
  const rows = visible.map(w => {
    const who = [w.cat_no, w.artist_name, w.title].filter(Boolean).join(' \u2013 ');
    const workCell = (w.work_id && who)
      ? `<button type="button" class="link-btn" onclick="scrollToWork('${esc(w.work_id)}')">${esc(who)}</button>`
      : (esc(who) || '\u2014');
    return `<tr>
      <td><span class="badge badge-warning">${esc(w.warning_type)}</span></td>
      <td>${esc(w.message)}</td>
      <td class="muted col-work">${workCell}</td>
    </tr>`;
  }).join('');

  const hiddenCount = warnings.length - visible.length;
  const countLabel = hiddenCount > 0
    ? `${visible.length} shown of ${warnings.length}`
    : String(warnings.length);

  panel.innerHTML = `
    <h3>\u26a0 Validation Warnings (${countLabel})</h3>
    <div class="warning-filter-bar">${summaryBadges}</div>
    <details>
      <summary class="warnings-toggle">Show detail</summary>
      <table class="data-table warnings-table" style="margin-top:10px">
        <thead><tr><th>Type</th><th>Message</th><th>Work</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;

  // Attach badge click handlers after innerHTML
  panel.querySelectorAll('.warning-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      if (_hiddenWarningTypes.has(type)) {
        _hiddenWarningTypes.delete(type);
      } else {
        _hiddenWarningTypes.add(type);
      }
      _buildWarningsPanel();
    });
  });
}

function scrollToWork(workId) {
  const row = document.getElementById('wr-' + workId);
  if (!row) return;
  // Ensure parent <details> (section block) is open
  let el = row.parentElement;
  while (el) {
    if (el.tagName === 'DETAILS') el.open = true;
    el = el.parentElement;
  }
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  row.classList.remove('row-highlight');
  // Force reflow so re-adding the class restarts the animation
  void row.offsetWidth;
  row.classList.add('row-highlight');
  setTimeout(() => row.classList.remove('row-highlight'), 2500);
}

function _applyWorksFilter(query, countEl, totalWorks) {
  const q = query.trim().toLowerCase();
  const rows = document.querySelectorAll('.work-row');
  let visible = 0;
  rows.forEach(row => {
    if (!q) {
      row.style.display = '';
      visible++;
      return;
    }
    // Match against cat no (col 0), artist (col 1), title (col 2)
    const cells = row.cells;
    const text = [
      cells[0]?.textContent ?? '',
      cells[1]?.textContent ?? '',
      cells[2]?.textContent ?? '',
    ].join(' ').toLowerCase();
    const match = text.includes(q);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  // Also hide the override form row if its parent work row is hidden
  document.querySelectorAll('.override-form-row').forEach(fr => {
    const prevRow = fr.previousElementSibling;
    if (prevRow && prevRow.style.display === 'none') fr.style.display = 'none';
    else fr.style.display = '';
  });
  if (q) {
    countEl.textContent = `${visible} of ${totalWorks} works`;
  } else {
    countEl.textContent = '';
  }
}

function renderSections(importId, sections, cfg) {
  const container = document.getElementById('sections-container');
  if (!sections.length) {
    container.innerHTML = '<p class="muted">No sections found.</p>';
    return;
  }
  // Populate work cache so the override form can show normalised values
  _workCache = {};
  let totalWorks = 0;
  for (const section of sections) {
    for (const w of section.works) { _workCache[w.id] = w; }
    totalWorks += section.works.length;
  }
  // Wire up filter input
  const filterInput = document.getElementById('works-filter');
  const filterCount = document.getElementById('works-filter-count');
  if (filterInput) {
    filterInput.value = '';
    filterCount.textContent = '';
    filterInput.addEventListener('input', () => _applyWorksFilter(filterInput.value, filterCount, totalWorks));
  }
  container.innerHTML = sections.map(section => `
    <details class="section-block" open>
      <summary class="section-summary">
        <span class="section-name">${esc(section.name)}</span>
        <span class="section-meta">${section.works.length} work${section.works.length !== 1 ? 's' : ''}</span>
        <button type="button" class="btn btn-xs btn-secondary section-export-btn"
          onclick="event.preventDefault();downloadExportWithTemplate('${esc(importId)}','tags','txt','${esc(section.id)}',this,'${esc(section.name)}')">
          Export section
        </button>
      </summary>
      <table class="data-table works-table">
        <thead><tr>
          <th class="col-no">No.</th>
          <th>Artist</th>
          <th>Title</th>
          <th>Price</th>
          <th>Edition</th>
          <th>Artwork</th>
          <th>Medium</th>
          <th class="col-include"><abbr title="Include in export">Inc.</abbr></th>
          <th class="col-actions">Override</th>
        </tr></thead>
        <tbody id="tbody-${esc(section.id)}">
          ${section.works.map(w => workRowHTML(importId, w, cfg)).join('')}
        </tbody>
      </table>
    </details>`).join('');
}

function workRowHTML(importId, w, cfg) {
  const included = w.include_in_export !== false;
  const hasOverride = !!w.override;

  // Resolve effective values (override takes precedence)
  const o = w.override;
  const eff = {
    title:                o?.title_override           ?? w.title,
    artist_name:          o?.artist_name_override     ?? w.artist_name,
    artist_honorifics:    o?.artist_honorifics_override ?? w.artist_honorifics,
    price_numeric:        o?.price_numeric_override   ?? w.price_numeric,
    price_text:           o?.price_text_override      ?? w.price_text,
    edition_total:        o?.edition_total_override   ?? w.edition_total,
    edition_price_numeric: o?.edition_price_numeric_override ?? w.edition_price_numeric,
    medium:               o?.medium_override          ?? w.medium,
  };

  const honorifics = eff.artist_honorifics
    ? ` <span class="honorifics-pill${hasOverride && o?.artist_honorifics_override ? ' cell-overridden' : ''}">${esc(eff.artist_honorifics)}</span>`
    : '';
  const priceDisplay = formatPrice(eff.price_numeric, eff.price_text, cfg);

  // Edition: mimic the export renderer format
  const prefix = cfg?.edition_prefix ?? 'edition of';
  const brackets = cfg?.edition_brackets !== false;
  let editionDisplay = '';
  if (eff.edition_total && eff.edition_price_numeric) {
    const inner = `${prefix} ${eff.edition_total} at ${formatPrice(eff.edition_price_numeric, null, cfg)}`;
    editionDisplay = brackets ? `(${inner})` : inner;
  } else if (eff.edition_total) {
    const inner = `${prefix} ${eff.edition_total}`;
    editionDisplay = brackets ? `(${inner})` : inner;
  }

  const ovBtnClass = hasOverride ? 'btn-warning' : 'btn-secondary';
  const ovBtnLabel = hasOverride ? 'Edit \u270e' : 'Edit';

  return `
    <tr id="wr-${esc(w.id)}" class="work-row ${included ? '' : 'row-excluded'}">
      <td class="col-no">${esc(w.raw_cat_no ?? '')}</td>
      <td class="${hasOverride && o?.artist_name_override ? 'cell-overridden' : ''}">${esc(eff.artist_name ?? '')}${honorifics}</td>
      <td class="${hasOverride && o?.title_override ? 'cell-overridden' : ''}">${esc(eff.title ?? '')}</td>
      <td class="${hasOverride && (o?.price_numeric_override || o?.price_text_override) ? 'cell-overridden' : ''}">${esc(priceDisplay)}</td>
      <td class="${hasOverride && (o?.edition_total_override || o?.edition_price_numeric_override) ? 'cell-overridden' : ''}">${esc(editionDisplay)}</td>
      <td class="${hasOverride && o?.artwork_override ? 'cell-overridden' : ''}">${w.artwork != null ? esc(String(w.artwork)) : ''}</td>
      <td class="col-medium ${hasOverride && o?.medium_override ? 'cell-overridden' : ''}">${esc(eff.medium ?? '')}</td>
      <td class="col-include">
        ${canEdit() ? `<input type="checkbox" class="include-cb${included ? '' : ' excluded'}" id="incl-${esc(w.id)}"
          ${included ? 'checked' : ''}
          onchange="toggleInclude('${esc(importId)}','${esc(w.id)}',this)">` : (included ? '\u2713' : '\u2717')}
      </td>
      <td class="col-actions">
        ${ifEditor(`<button id="ov-btn-${esc(w.id)}" class="btn btn-xs ${ovBtnClass}" data-has-override="${hasOverride ? '1' : ''}"
          onclick="toggleOverrideForm('${esc(importId)}','${esc(w.id)}')">${ovBtnLabel}</button>`)}
      </td>
    </tr>
    <tr id="ovr-${esc(w.id)}" class="override-form-row" style="display:none">
      <td colspan="9" id="ovc-${esc(w.id)}"></td>
    </tr>`;
}

// ---------------------------------------------------------------------------
// Exclude / include
// ---------------------------------------------------------------------------

async function toggleInclude(importId, workId, checkbox) {
  const nowIncluded = checkbox.checked;
  checkbox.disabled = true;
  try {
    await api('PATCH', `/imports/${importId}/works/${workId}/exclude?exclude=${!nowIncluded}`);
    const row = document.getElementById(`wr-${workId}`);
    if (row) row.className = `work-row ${nowIncluded ? '' : 'row-excluded'}`;
    checkbox.className = `include-cb${nowIncluded ? '' : ' excluded'}`;
  } catch (err) {
    // Revert the checkbox on failure
    checkbox.checked = !nowIncluded;
    showToast(`Toggle failed: ${err.message}`, 'error');
  } finally {
    checkbox.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Override form
// ---------------------------------------------------------------------------

async function toggleOverrideForm(importId, workId) {
  const formRow = document.getElementById(`ovr-${workId}`);
  const btn     = document.getElementById(`ov-btn-${workId}`);

  // If this row is already open, close it
  if (_expandedWorkId === workId) {
    formRow.style.display = 'none';
    _restoreOverrideBtn(btn);
    _expandedWorkId = null;
    return;
  }

  // Close any other open override form
  if (_expandedWorkId) {
    const prev    = document.getElementById(`ovr-${_expandedWorkId}`);
    const prevBtn = document.getElementById(`ov-btn-${_expandedWorkId}`);
    if (prev)    prev.style.display = 'none';
    _restoreOverrideBtn(prevBtn);
  }

  _expandedWorkId = workId;
  btn.textContent = 'Close';
  btn.className = 'btn btn-xs btn-secondary';
  formRow.style.display = '';
  document.getElementById(`ovc-${workId}`).innerHTML = '<p class="loading" style="padding:12px">Loading\u2026</p>';

  let existing = null;
  try {
    existing = await api('GET', `/imports/${importId}/works/${workId}/override`);
  } catch (err) {
    if (err.httpStatus !== 404) {
      document.getElementById(`ovc-${workId}`).innerHTML = `<p class="error" style="padding:12px">${esc(err.message)}</p>`;
      return;
    }
    // 404 = no override yet, existing stays null
  }
  showOverrideForm(importId, workId, existing);
}

function showOverrideForm(importId, workId, existing) {
  const val = (f) => esc(existing?.[f] ?? '');

  // Effective current value = override if set, else normalised from cache
  const w   = _workCache[workId] ?? {};
  const o   = existing ?? {};
  const cur = {
    title_override:                    o.title_override                    ?? w.title                    ?? '',
    artist_name_override:              o.artist_name_override              ?? w.artist_name               ?? '',
    artist_honorifics_override:        o.artist_honorifics_override        ?? w.artist_honorifics          ?? '',
    price_text_override:               o.price_text_override               ?? w.price_text                ?? '',
    price_numeric_override:            o.price_numeric_override            ?? w.price_numeric              ?? '',
    edition_total_override:            o.edition_total_override            ?? w.edition_total              ?? '',
    edition_price_numeric_override:    o.edition_price_numeric_override    ?? w.edition_price_numeric      ?? '',
    artwork_override:                  o.artwork_override                  ?? w.artwork                    ?? '',
    medium_override:                   o.medium_override                   ?? w.medium                    ?? '',
  };

  // Returns a clickable hint that copies the current value into the named input/textarea
  const hint = (field, inputName) => {
    const v = cur[field];
    if (v === null || v === undefined || v === '') return '';
    const safe = esc(String(v));
    // Encode value as base64 to safely handle newlines in the onclick handler
    const b64 = btoa(unescape(encodeURIComponent(String(v))));
    return `<button type="button" class="current-val-hint"
      onclick="(function(){var el=document.querySelector('#ovf-${esc(workId)} [name=\\'${inputName}\\']');if(el)el.value=decodeURIComponent(escape(atob('${b64}')));})()">
      ${safe.replace(/\n/g, ' \u23ce ')}</button>`;
  };

  const cell = document.getElementById(`ovc-${workId}`);
  cell.innerHTML = `
    <div class="override-form">
      <h5>Override Fields <span class="muted" style="text-transform:none;font-weight:400">&ndash; leave blank to use current value &middot; click current value to copy &middot; use Enter in text fields to control line breaks in exports</span></h5>
      <div class="override-field-form" id="ovf-${esc(workId)}">
        <div class="form-row"><label>Title</label>
          ${hint('title_override','title_override')}
          <textarea name="title_override" rows="2" placeholder="Override title (use Enter for line breaks)">${val('title_override')}</textarea></div>
        <div class="form-row"><label>Artist</label>
          ${hint('artist_name_override','artist_name_override')}
          <textarea name="artist_name_override" rows="2" placeholder="Override artist (use Enter for line breaks)">${val('artist_name_override')}</textarea></div>
        <div class="form-row"><label>Honorifics</label>
          ${hint('artist_honorifics_override','artist_honorifics_override')}
          <input type="text" name="artist_honorifics_override" value="${val('artist_honorifics_override')}" placeholder="e.g. RA"></div>
        <div class="form-row"><label>Price text</label>
          ${hint('price_text_override','price_text_override')}
          <input type="text" name="price_text_override" value="${val('price_text_override')}" placeholder="e.g. NFS or 1500"></div>
        <div class="form-row"><label>Price numeric</label>
          ${hint('price_numeric_override','price_numeric_override')}
          <input type="number" step="0.01" min="0" name="price_numeric_override" value="${val('price_numeric_override')}" placeholder="e.g. 1500"></div>
        <div class="form-row"><label>Edition total</label>
          ${hint('edition_total_override','edition_total_override')}
          <input type="number" min="0" name="edition_total_override" value="${val('edition_total_override')}" placeholder="e.g. 10"></div>
        <div class="form-row"><label>Edition price</label>
          ${hint('edition_price_numeric_override','edition_price_numeric_override')}
          <input type="number" step="0.01" min="0" name="edition_price_numeric_override" value="${val('edition_price_numeric_override')}" placeholder="e.g. 750"></div>
        <div class="form-row"><label>Artwork</label>
          ${hint('artwork_override','artwork_override')}
          <input type="number" min="0" name="artwork_override" value="${val('artwork_override')}" placeholder="e.g. 42"></div>
        <div class="form-row"><label>Medium</label>
          ${hint('medium_override','medium_override')}
          <textarea name="medium_override" rows="2" placeholder="Override medium (use Enter for line breaks)">${val('medium_override')}</textarea></div>
        <div class="form-actions">
          <button class="btn btn-primary" onclick="saveOverride('${esc(importId)}','${esc(workId)}')">Save</button>
          ${existing ? `<button class="btn btn-danger" onclick="deleteOverride('${esc(importId)}','${esc(workId)}')">Delete Override</button>` : ''}
          <span id="ovs-${esc(workId)}" class="status-msg"></span>
        </div>
      </div>
    </div>`;
}

/** Re-render the visible work row cells after an override save/delete. */
function _refreshWorkRow(importId, workId) {
  const w = _workCache[workId];
  if (!w) return;
  const cfg = _getDisplayCfg();
  const tmp = document.createElement('tbody');
  tmp.innerHTML = workRowHTML(importId, w, cfg);
  const newRow = tmp.querySelector(`#wr-${CSS.escape(workId)}`);
  const oldRow = document.getElementById(`wr-${workId}`);
  if (oldRow && newRow) oldRow.replaceWith(newRow);
}

async function saveOverride(importId, workId) {
  const formEl = document.getElementById(`ovf-${workId}`);
  const statusEl = document.getElementById(`ovs-${workId}`);
  statusEl.textContent = 'Saving\u2026';
  statusEl.className = 'status-msg';

  const numFields = new Set(['price_numeric_override','edition_total_override','edition_price_numeric_override','artwork_override']);
  const allFields = ['title_override','artist_name_override','artist_honorifics_override',
    'price_text_override','price_numeric_override','edition_total_override','edition_price_numeric_override',
    'artwork_override','medium_override'];

  const body = {};
  for (const f of allFields) {
    const input = formEl.querySelector(`[name="${f}"]`);
    const raw = input?.value.trim() ?? '';
    if (raw === '') { body[f] = null; }
    else if (numFields.has(f)) { body[f] = Number(raw); }
    else { body[f] = raw; }
  }

  try {
    const result = await api('PUT', `/imports/${importId}/works/${workId}/override`, body);
    // Update cache so the form re-renders with normalised hints intact
    if (_workCache[workId]) _workCache[workId].override = result;
    _refreshWorkRow(importId, workId);
    showOverrideForm(importId, workId, result);
    const s = document.getElementById(`ovs-${workId}`);
    if (s) { s.textContent = '\u2713 Saved'; s.className = 'status-msg success'; }
    // Mark the row button — form stays open so show Close, but flag the override
    const btn = document.getElementById(`ov-btn-${workId}`);
    if (btn) { btn.textContent = 'Close'; btn.className = 'btn btn-xs btn-warning'; btn.dataset.hasOverride = '1'; }
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.className = 'status-msg error';
  }
}

async function deleteOverride(importId, workId) {
  if (!confirm('Delete override for this work?')) return;
  const statusEl = document.getElementById(`ovs-${workId}`);
  try {
    await api('DELETE', `/imports/${importId}/works/${workId}/override`);
    // Remove from cache
    if (_workCache[workId]) _workCache[workId].override = null;
    _refreshWorkRow(importId, workId);
    showOverrideForm(importId, workId, null);
    const s = document.getElementById(`ovs-${workId}`);
    if (s) { s.textContent = '\u2713 Override deleted'; s.className = 'status-msg success'; }
    // Restore the row button to plain Edit (override removed)
    const btn = document.getElementById(`ov-btn-${workId}`);
    if (btn) { btn.textContent = 'Close'; btn.className = 'btn btn-xs btn-secondary'; btn.dataset.hasOverride = ''; }
  } catch (err) {
    if (statusEl) { statusEl.textContent = `Error: ${err.message}`; statusEl.className = 'status-msg error'; }
  }
}

// ---------------------------------------------------------------------------
// Export diff viewer
// ---------------------------------------------------------------------------

async function showExportDiff(importId, btnEl) {
  const sel = document.getElementById(`tmpl-select-${importId}`);
  const tid = sel?.value || null;
  const panel = document.getElementById(`diff-panel-${importId}`);
  if (!panel) return;

  // Toggle off if already showing
  if (panel.dataset.visible === '1') {
    panel.innerHTML = '';
    panel.dataset.visible = '';
    return;
  }

  const restore = btnLoading(btnEl, 'Loading');
  try {
    let path = `/imports/${importId}/export-diff`;
    if (tid) path += `?template_id=${encodeURIComponent(tid)}`;
    const diff = await api('GET', path);
    panel.dataset.visible = '1';
    panel.innerHTML = _renderDiffPanel(diff);
  } catch (err) {
    panel.innerHTML = `<p class="error" style="margin-top:8px">${esc(err.message)}</p>`;
  } finally {
    restore();
  }
}

function _renderDiffPanel(diff) {
  if (diff.no_previous_export) {
    return `<div class="diff-result diff-info">
      <p><strong>No previous export found.</strong> Export the catalogue first, then use this to see what changed before the next export.</p>
    </div>`;
  }

  if (!diff.has_changes) {
    return `<div class="diff-result diff-ok">
      <p>\u2713 No changes since last export <span class="muted">(${esc(formatDate(diff.previous_exported_at))})</span></p>
    </div>`;
  }

  const parts = [];
  parts.push(`<div class="diff-result">`);
  parts.push(`<p class="diff-summary">Changes since last export <span class="muted">(${esc(formatDate(diff.previous_exported_at))})</span>:</p>`);

  // Summary badges
  const badges = [];
  if (diff.added.length)   badges.push(`<span class="badge badge-added">${diff.added.length} added</span>`);
  if (diff.removed.length) badges.push(`<span class="badge badge-removed">${diff.removed.length} removed</span>`);
  if (diff.changed.length) badges.push(`<span class="badge badge-changed">${diff.changed.length} changed</span>`);
  if (diff.unchanged_count) badges.push(`<span class="badge badge-unchanged">${diff.unchanged_count} unchanged</span>`);
  parts.push(`<div class="diff-badges">${badges.join(' ')}</div>`);

  // Changed works — field-level detail
  if (diff.changed.length) {
    parts.push('<h4 class="diff-heading">Changed works</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Cat No</th><th>Section</th><th>Field</th><th>Previous</th><th>Current</th></tr></thead><tbody>');
    for (const w of diff.changed) {
      const rowspan = w.fields.length;
      w.fields.forEach((f, i) => {
        parts.push('<tr>');
        if (i === 0) parts.push(`<td rowspan="${rowspan}" class="diff-catno">${esc(w.cat_no)}</td><td rowspan="${rowspan}">${esc(w.section)}</td>`);
        parts.push(`<td><code>${esc(f.field)}</code></td>`);
        parts.push(`<td class="diff-old">${f.old != null ? esc(String(f.old)) : '<span class="muted">\u2014</span>'}</td>`);
        parts.push(`<td class="diff-new">${f.new != null ? esc(String(f.new)) : '<span class="muted">\u2014</span>'}</td>`);
        parts.push('</tr>');
      });
    }
    parts.push('</tbody></table>');
  }

  // Added works
  if (diff.added.length) {
    parts.push('<h4 class="diff-heading">Added works</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Cat No</th><th>Section</th><th>Artist</th><th>Title</th><th>Price</th></tr></thead><tbody>');
    for (const w of diff.added) {
      parts.push(`<tr class="diff-row-added"><td>${esc(w.cat_no ?? '\u2014')}</td><td>${esc(w.section)}</td><td>${esc(w.artist ?? '')}</td><td>${esc(w.title ?? '')}</td><td>${esc(w.price_text ?? '')}</td></tr>`);
    }
    parts.push('</tbody></table>');
  }

  // Removed works
  if (diff.removed.length) {
    parts.push('<h4 class="diff-heading">Removed works</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Cat No</th><th>Section</th><th>Artist</th><th>Title</th><th>Price</th></tr></thead><tbody>');
    for (const w of diff.removed) {
      parts.push(`<tr class="diff-row-removed"><td>${esc(w.cat_no ?? '\u2014')}</td><td>${esc(w.section)}</td><td>${esc(w.artist ?? '')}</td><td>${esc(w.title ?? '')}</td><td>${esc(w.price_text ?? '')}</td></tr>`);
    }
    parts.push('</tbody></table>');
  }

  parts.push('</div>');
  return parts.join('');
}

// ---------------------------------------------------------------------------
// Index export diff viewer
// ---------------------------------------------------------------------------

async function showIndexExportDiff(importId, btnEl) {
  const sel = document.getElementById(`idx-tmpl-select-${importId}`);
  const tid = sel?.value || null;
  const panel = document.getElementById(`index-diff-panel-${importId}`);
  if (!panel) return;

  // Toggle off if already showing
  if (panel.dataset.visible === '1') {
    panel.innerHTML = '';
    panel.dataset.visible = '';
    return;
  }

  const restore = btnLoading(btnEl, 'Loading');
  try {
    let path = `/index/imports/${importId}/export-diff`;
    if (tid) path += `?template_id=${encodeURIComponent(tid)}`;
    const diff = await api('GET', path);
    panel.dataset.visible = '1';
    panel.innerHTML = _renderIndexDiffPanel(diff);
  } catch (err) {
    panel.innerHTML = `<p class="error" style="margin-top:8px">${esc(err.message)}</p>`;
  } finally {
    restore();
  }
}

function _renderIndexDiffPanel(diff) {
  if (diff.no_previous_export) {
    return `<div class="diff-result diff-info">
      <p><strong>No previous export found.</strong> Export the index first, then use this to see what changed before the next export.</p>
    </div>`;
  }

  if (!diff.has_changes) {
    return `<div class="diff-result diff-ok">
      <p>\u2713 No changes since last export <span class="muted">(${esc(formatDate(diff.previous_exported_at))})</span></p>
    </div>`;
  }

  const parts = [];
  parts.push(`<div class="diff-result">`);
  parts.push(`<p class="diff-summary">Changes since last export <span class="muted">(${esc(formatDate(diff.previous_exported_at))})</span>:</p>`);

  // Summary badges
  const badges = [];
  if (diff.added.length)   badges.push(`<span class="badge badge-added">${diff.added.length} added</span>`);
  if (diff.removed.length) badges.push(`<span class="badge badge-removed">${diff.removed.length} removed</span>`);
  if (diff.changed.length) badges.push(`<span class="badge badge-changed">${diff.changed.length} changed</span>`);
  if (diff.unchanged_count) badges.push(`<span class="badge badge-unchanged">${diff.unchanged_count} unchanged</span>`);
  parts.push(`<div class="diff-badges">${badges.join(' ')}</div>`);

  // Changed entries — field-level detail
  if (diff.changed.length) {
    parts.push('<h4 class="diff-heading">Changed entries</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Artist</th><th>Courtesy</th><th>Field</th><th>Previous</th><th>Current</th></tr></thead><tbody>');
    for (const e of diff.changed) {
      const rowspan = e.fields.length;
      e.fields.forEach((f, i) => {
        parts.push('<tr>');
        if (i === 0) parts.push(`<td rowspan="${rowspan}" class="diff-catno">${esc(e.name)}</td><td rowspan="${rowspan}">${esc(e.courtesy ?? '\u2014')}</td>`);
        const oldVal = _formatIndexDiffVal(f.field, f.old);
        const newVal = _formatIndexDiffVal(f.field, f.new);
        parts.push(`<td><code>${esc(f.field)}</code></td>`);
        parts.push(`<td class="diff-old">${oldVal}</td>`);
        parts.push(`<td class="diff-new">${newVal}</td>`);
        parts.push('</tr>');
      });
    }
    parts.push('</tbody></table>');
  }

  // Added entries
  if (diff.added.length) {
    parts.push('<h4 class="diff-heading">Added entries</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Artist</th><th>Courtesy</th><th>Cat Nos</th></tr></thead><tbody>');
    for (const e of diff.added) {
      parts.push(`<tr class="diff-row-added"><td>${esc(e.name)}</td><td>${esc(e.courtesy ?? '\u2014')}</td><td>${esc((e.cat_nos || []).join(', '))}</td></tr>`);
    }
    parts.push('</tbody></table>');
  }

  // Removed entries
  if (diff.removed.length) {
    parts.push('<h4 class="diff-heading">Removed entries</h4>');
    parts.push('<table class="data-table diff-table"><thead><tr><th>Artist</th><th>Courtesy</th><th>Cat Nos</th></tr></thead><tbody>');
    for (const e of diff.removed) {
      parts.push(`<tr class="diff-row-removed"><td>${esc(e.name)}</td><td>${esc(e.courtesy ?? '\u2014')}</td><td>${esc((e.cat_nos || []).join(', '))}</td></tr>`);
    }
    parts.push('</tbody></table>');
  }

  parts.push('</div>');
  return parts.join('');
}

function _formatIndexDiffVal(field, val) {
  if (val == null) return '<span class="muted">\u2014</span>';
  if (field === 'cat_nos' && Array.isArray(val)) return esc(val.join(', '));
  if (typeof val === 'boolean') return val ? 'Yes' : 'No';
  return esc(String(val));
}

// ---------------------------------------------------------------------------
// Export download
// ---------------------------------------------------------------------------

function downloadExportWithTemplate(importId, format, ext, sectionId = null, btnEl = null, sectionName = null) {
  const sel = document.getElementById(`tmpl-select-${importId}`);
  const tid = sel?.value || null;
  const tname = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : null;
  // Remember the last-used template
  if (tid) localStorage.setItem('catalogue_last_template', tid);
  downloadExport(importId, format, ext, sectionId, tid, btnEl, sectionName, tname);
}

async function downloadExport(importId, format, ext, sectionId = null, templateId = null, btnEl = null, sectionName = null, templateName = null) {
  const restore = btnLoading(btnEl, 'Exporting');
  try {
    let path = sectionId
      ? `/imports/${importId}/sections/${sectionId}/export-${format}`
      : `/imports/${importId}/export-${format}`;
    if (templateId) path += `?template_id=${encodeURIComponent(templateId)}`;
    const res = await fetch(path, { headers: _apiHeaders() });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const now = new Date();
    const ts = now.getFullYear().toString()
      + String(now.getMonth() + 1).padStart(2, '0')
      + String(now.getDate()).padStart(2, '0')
      + '-'
      + String(now.getHours()).padStart(2, '0')
      + String(now.getMinutes()).padStart(2, '0')
      + String(now.getSeconds()).padStart(2, '0');
    // Use section name for section exports, "catalogue" for full exports
    const slug = sectionName
      ? sectionName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
      : 'catalogue';
    const a = document.createElement('a');
    a.href = url;
    a.download = `${slug}-${importId.slice(0, 8)}-${ts}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    // Toast with template info for section exports
    if (sectionName && templateName) {
      showToast(`"${sectionName}" exported using template "${templateName}"`, 'success', 3500);
    } else if (sectionName) {
      showToast(`"${sectionName}" exported (default settings)`, 'success', 3000);
    } else {
      showToast('Export downloaded', 'success', 2500);
    }
  } catch (err) {
    showToast(`Export failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

// ===========================================================================
// Artists Index
// ===========================================================================

// ---------------------------------------------------------------------------
// Index — list page
// ---------------------------------------------------------------------------

async function renderIndexList() {
  document.getElementById('app').innerHTML = `
    ${ifEditor(`<section class="panel">
      <h3>Import Artists Index Excel File</h3>
      <form id="index-upload-form" class="upload-form">
        <input type="file" id="index-file-input" accept=".xlsx,.xls" required>
        <button type="submit" class="btn btn-primary">Upload</button>
      </form>
      <p id="index-upload-status" class="status-msg" style="margin-top:8px"></p>
    </section>`)}
    <section class="panel">
      <h3>Artists Index Imports</h3>
      <div id="index-imports-list">Loading\u2026</div>
    </section>`;

  document.getElementById('index-upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = document.getElementById('index-file-input').files[0];
    if (file) await handleIndexUpload(file);
  });

  await loadIndexImportList();
}

async function loadIndexImportList() {
  const container = document.getElementById('index-imports-list');
  try {
    const imports = await api('GET', '/index/imports');
    if (!imports.length) {
      container.innerHTML = '<p class="muted">No index imports yet.</p>';
      return;
    }
    const rows = imports.map(i => `
      <tr>
        <td><code class="import-id" title="${esc(i.id)}">${esc(i.id.slice(0, 8))}\u2026</code></td>
        <td><a class="link" href="#/index/${esc(i.id)}">${esc(i.filename)}</a></td>
        <td>${esc(formatDate(i.uploaded_at))}</td>
        <td class="num">${i.artist_count}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="navigate('#/index/${esc(i.id)}')">View</button>
          ${ifAdmin(`<button class="btn btn-sm btn-danger" onclick="handleIndexDelete('${esc(i.id)}', '${esc(i.filename.replace(/'/g, ''))}', this)">Delete</button>`)}
        </td>
      </tr>`).join('');
    container.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>ID</th><th>Filename</th><th>Uploaded</th>
          <th class="num">Artists</th>
          <th>Actions</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (err) {
    container.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

async function handleIndexUpload(file) {
  const statusEl = document.getElementById('index-upload-status');
  const uploadBtn = document.querySelector('#index-upload-form .btn-primary');
  const restore = btnLoading(uploadBtn, 'Uploading');
  statusEl.textContent = 'Uploading\u2026';
  statusEl.className = 'status-msg';
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/index/import', { method: 'POST', body: form, headers: _apiHeaders() });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) { const t = await res.text(); throw new Error(t); }
    const data = await res.json();
    statusEl.textContent = `\u2713 Uploaded (ID: ${data.import_id})`;
    statusEl.className = 'status-msg success';
    document.getElementById('index-file-input').value = '';
    await loadIndexImportList();
  } catch (err) {
    statusEl.textContent = `Upload failed: ${err.message}`;
    statusEl.className = 'status-msg error';
  } finally {
    restore();
  }
}

async function handleIndexDelete(id, filename, btnEl) {
  if (!confirm(`Delete index import \u201c${filename}\u201d? This cannot be undone.`)) return;
  const restore = btnLoading(btnEl, 'Deleting');
  try {
    await api('DELETE', `/index/imports/${id}`);
    showToast('Index import deleted', 'success', 3000);
    await loadIndexImportList();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

// ---------------------------------------------------------------------------
// Index — reimport
// ---------------------------------------------------------------------------

async function handleIndexReimport(importId, file) {
  const statusEl = document.getElementById('index-reimport-status');
  const btn = document.querySelector('#index-reimport-form .btn-primary');
  const restore = btnLoading(btn, 'Re-importing');
  statusEl.textContent = 'Re-importing\u2026';
  statusEl.className = 'status-msg';
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/index/imports/${importId}/reimport`, {
      method: 'PUT', body: form, headers: _apiHeaders(),
    });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) { const t = await res.text(); throw new Error(t); }
    const data = await res.json();
    const parts = [];
    if (data.matched)  parts.push(`${data.matched} matched`);
    if (data.added)    parts.push(`${data.added} added`);
    if (data.removed)  parts.push(`${data.removed} removed`);
    if (data.overrides_preserved) parts.push(`${data.overrides_preserved} overrides preserved`);
    const summary = parts.join(', ') || 'No changes';
    statusEl.textContent = `\u2713 Re-imported: ${summary}`;
    statusEl.className = 'status-msg success';
    showToast(`Re-import complete: ${summary}`, 'success', 5000);
    document.getElementById('index-reimport-file').value = '';
    await renderIndexDetail(importId);
  } catch (err) {
    statusEl.textContent = `Re-import failed: ${err.message}`;
    statusEl.className = 'status-msg error';
    showToast(`Re-import failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

// ---------------------------------------------------------------------------
// Index — detail page
// ---------------------------------------------------------------------------

let _indexArtistCache = {};  // artistId -> artist object

async function renderIndexDetail(importId) {
  _indexArtistCache = {};
  document.getElementById('app').innerHTML = `
    <div class="breadcrumb"><a href="#/index">\u2190 All Index Imports</a></div>
    <h2 class="page-heading" id="index-detail-heading">Loading\u2026</h2>
    ${ifEditor(`<section class="panel reimport-panel">
      <h3>Update Import</h3>
      <p class="muted" style="font-size:12px;margin-bottom:10px">Select an updated version of the same spreadsheet. Existing overrides and exclusions will be preserved where possible.</p>
      <form id="index-reimport-form" class="upload-form">
        <input type="file" id="index-reimport-file" accept=".xlsx,.xls" required>
        <button type="submit" class="btn btn-primary">Re-import</button>
      </form>
      <p id="index-reimport-warn" class="status-msg" style="margin-top:4px;display:none"></p>
      <p id="index-reimport-status" class="status-msg" style="margin-top:8px"></p>
    </section>`)}
    <section class="panel">
      <h3>Export</h3>
      <div id="index-export-panel"><p class="loading" style="padding:4px 0">Loading templates…</p></div>
    </section>
    <section class="panel" id="index-warnings-panel"><p class="loading">Loading warnings\u2026</p></section>
    <section class="panel">
      <h3>Artists</h3>
      <div class="works-filter-bar">
        <input type="text" id="index-filter" class="works-filter-input" placeholder="Filter by name, quals, or cat number\u2026" autocomplete="off">
        <span id="index-filter-count" class="works-filter-count"></span>
      </div>
      <div id="index-artists-container"><p class="loading">Loading\u2026</p></div>
    </section>
    <section class="panel" id="index-audit-panel"><p class="loading">Loading audit log\u2026</p></section>`;

  // Wire up index re-import form
  document.getElementById('index-reimport-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = document.getElementById('index-reimport-file').files[0];
    if (file) await handleIndexReimport(importId, file);
  });

  // Fetch import metadata
  let importFilename = null;
  try {
    const imports = await api('GET', '/index/imports');
    const thisImport = imports.find(i => i.id === importId);
    if (thisImport) importFilename = thisImport.filename;
  } catch (_) {}

  document.getElementById('index-detail-heading').textContent =
    importFilename
      ? `Artists Index \u2013 ${importFilename}`
      : `Artists Index \u2013 ${importId.slice(0, 8)}\u2026`;

  // Filename mismatch warning for reimport
  const idxFileInput = document.getElementById('index-reimport-file');
  const idxWarnEl = document.getElementById('index-reimport-warn');
  if (idxFileInput) {
    idxFileInput.addEventListener('change', () => {
      const selected = idxFileInput.files[0];
      if (!selected || !importFilename) { idxWarnEl.style.display = 'none'; return; }
      if (selected.name !== importFilename) {
        idxWarnEl.textContent = `\u26a0 Selected file "${selected.name}" differs from the original "${importFilename}". This will replace the current data.`;
        idxWarnEl.className = 'status-msg warning';
        idxWarnEl.style.display = '';
      } else {
        idxWarnEl.style.display = 'none';
      }
    });
  }

  const [artists, warnings, idxTemplates, auditLogs] = await Promise.all([
    api('GET', `/index/imports/${importId}/artists`).catch(e => ({ _error: e.message })),
    api('GET', `/index/imports/${importId}/warnings`).catch(() => []),
    api('GET', '/index/templates').catch(() => []),
    api('GET', `/imports/${importId}/audit-log`).catch(() => []),
  ]);

  // Populate index template picker
  const _lastIdxTmplKey = 'catalogue_last_index_template';
  const _lastIdxTmplId = localStorage.getItem(_lastIdxTmplKey) || '';
  const idxTmplOpts = idxTemplates.length
    ? idxTemplates.map(t => `<option value="${esc(t.id)}"${t.id === _lastIdxTmplId ? ' selected' : ''}>${esc(t.name)}</option>`).join('')
    : '<option value="" disabled>No templates \u2014 create one in Templates</option>';
  const exportPanel = document.getElementById('index-export-panel');
  if (exportPanel) exportPanel.innerHTML = `
    <div class="export-buttons">
      <div class="template-row">
        <label class="export-template-label">Template</label>
        <select id="idx-tmpl-select-${esc(importId)}"${idxTemplates.length ? '' : ' disabled'}>${idxTmplOpts}</select>
        <button class="btn btn-primary" onclick="downloadIndexExport('${esc(importId)}',this)">Export InDesign Tags (.txt)</button>
      </div>
      <button class="btn btn-secondary btn-diff" onclick="showIndexExportDiff('${esc(importId)}',this)">Show changes since last export</button>
    </div>
    <div id="index-diff-panel-${esc(importId)}"></div>`;
  const _idxTmplSel = document.getElementById(`idx-tmpl-select-${importId}`);
  if (_idxTmplSel) _idxTmplSel.addEventListener('change', () => localStorage.setItem(_lastIdxTmplKey, _idxTmplSel.value));

  // Warnings
  _renderIndexWarnings(warnings);

  if (artists._error) {
    document.getElementById('index-artists-container').innerHTML = `<p class="error">${esc(artists._error)}</p>`;
    return;
  }

  renderIndexArtists(importId, artists);
  renderIndexAuditPanel(auditLogs);
}

function renderIndexAuditPanel(logs) {
  const panel = document.getElementById('index-audit-panel');
  if (!panel) return;
  if (!logs.length) {
    panel.innerHTML = '<p class="muted" style="padding:4px 0">No audit log entries yet.</p>';
    return;
  }
  panel.innerHTML = `
    <details>
      <summary class="section-summary"><span class="section-name">Audit Log</span>
        <span class="section-meta">${logs.length} entr${logs.length !== 1 ? 'ies' : 'y'}</span>
      </summary>
      ${_auditLogTable(logs)}
    </details>`;
}

// ---------------------------------------------------------------------------
// Index warnings panel state (filter toggles survive re-renders)
// ---------------------------------------------------------------------------
let _indexWarningsAll = [];
let _hiddenIndexWarningTypes = new Set();

function _renderIndexWarnings(warnings) {
  _indexWarningsAll = warnings;
  _hiddenIndexWarningTypes = new Set();
  _buildIndexWarningsPanel();
}

function _buildIndexWarningsPanel() {
  const warnings = _indexWarningsAll;
  const panel = document.getElementById('index-warnings-panel');
  if (!warnings.length) {
    panel.innerHTML = '<p class="no-warnings">\u2713 No validation warnings</p>';
    return;
  }
  panel.classList.add('has-warnings');

  // Summary counts by type
  const counts = {};
  for (const w of warnings) {
    counts[w.warning_type] = (counts[w.warning_type] || 0) + 1;
  }
  const summaryBadges = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => {
      const muted = _hiddenIndexWarningTypes.has(type);
      return `<button type="button" class="badge badge-warning warning-filter-btn${muted ? ' badge-muted' : ''}" data-type="${esc(type)}" title="${muted ? 'Click to show' : 'Click to hide'}">${esc(type)}: ${n}</button>`;
    }).join('');

  // Detailed rows — filtered by hidden types
  const visible = warnings.filter(w => !_hiddenIndexWarningTypes.has(w.warning_type));
  const rows = visible.map(w => {
    const rowCell = (w.artist_id && w.row_number)
      ? `<button type="button" class="link-btn" onclick="scrollToIndexArtist('${esc(w.artist_id)}')">${esc('Row ' + w.row_number)}</button>`
      : (w.row_number ? esc('Row ' + w.row_number) : '\u2014');
    return `<tr>
      <td><span class="badge badge-warning">${esc(w.warning_type)}</span></td>
      <td>${esc(w.message)}</td>
      <td class="muted col-work">${rowCell}</td>
    </tr>`;
  }).join('');

  const hiddenCount = warnings.length - visible.length;
  const countLabel = hiddenCount > 0
    ? `${visible.length} shown of ${warnings.length}`
    : String(warnings.length);

  panel.innerHTML = `
    <h3>\u26a0 Validation Warnings (${countLabel})</h3>
    <div class="warning-filter-bar">${summaryBadges}</div>
    <details>
      <summary class="warnings-toggle">Show detail</summary>
      <table class="data-table warnings-table" style="margin-top:10px">
        <thead><tr><th>Type</th><th>Message</th><th>Row</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;

  // Attach badge click handlers
  panel.querySelectorAll('.warning-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      if (_hiddenIndexWarningTypes.has(type)) {
        _hiddenIndexWarningTypes.delete(type);
      } else {
        _hiddenIndexWarningTypes.add(type);
      }
      _buildIndexWarningsPanel();
    });
  });
}

function scrollToIndexArtist(artistId) {
  const row = document.getElementById('idx-' + artistId);
  if (!row) return;
  // Ensure parent <details> (letter section) is open
  let el = row.parentElement;
  while (el) {
    if (el.tagName === 'DETAILS') el.open = true;
    el = el.parentElement;
  }
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  row.classList.remove('row-highlight');
  // Force reflow so re-adding the class restarts the animation
  void row.offsetWidth;
  row.classList.add('row-highlight');
  setTimeout(() => row.classList.remove('row-highlight'), 2500);
}

function renderIndexArtists(importId, artists) {
  const container = document.getElementById('index-artists-container');
  if (!artists.length) {
    container.innerHTML = '<p class="muted">No artists found.</p>';
    return;
  }

  _indexArtistCache = {};
  for (const a of artists) _indexArtistCache[a.id] = a;

  const filterInput = document.getElementById('index-filter');
  const filterCount = document.getElementById('index-filter-count');
  if (filterInput) {
    filterInput.value = '';
    filterCount.textContent = '';
    filterInput.addEventListener('input', () => _applyIndexFilter(filterInput.value, filterCount, artists.length));
  }

  // Detect linked entries (same sort_key appearing more than once)
  const sortKeyCounts = {};
  for (const a of artists) {
    const sk = a.sort_key || '';
    sortKeyCounts[sk] = (sortKeyCounts[sk] || 0) + 1;
  }
  // Assign group colours to sort_keys with >1 entry
  const _GROUP_COLORS = ['#e74c3c','#2980b9','#27ae60','#f39c12','#8e44ad','#16a085','#d35400','#c0392b'];
  let colorIdx = 0;
  const sortKeyColor = {};
  for (const [sk, count] of Object.entries(sortKeyCounts)) {
    if (count > 1 && sk) {
      sortKeyColor[sk] = _GROUP_COLORS[colorIdx % _GROUP_COLORS.length];
      colorIdx++;
    }
  }

  // Group artists by first letter of sort_key
  const letterGroups = [];
  let currentLetter = null;
  let currentGroup = null;
  for (const a of artists) {
    const ch = (a.sort_key || '?')[0].toUpperCase();
    const letter = /\d/.test(ch) ? '#' : ch;
    if (letter !== currentLetter) {
      currentLetter = letter;
      currentGroup = { letter, artists: [] };
      letterGroups.push(currentGroup);
    }
    currentGroup.artists.push(a);
  }

  const theadHTML = `<thead><tr>
    <th>Index Name</th>
    <th>Last Name</th>
    <th>First Name</th>
    <th>Title</th>
    <th class="col-quals">Quals</th>
    <th>Courtesy / Company</th>
    <th>Cat Numbers</th>
    <th class="col-flags">Flags</th>
    <th class="col-include"><abbr title="Include in export">Inc.</abbr></th>
  </tr></thead>`;

  container.innerHTML = letterGroups.map(g => {
    const rows = g.artists.map(a => indexArtistRowHTML(importId, a, sortKeyColor[a.sort_key || ''])).join('');
    return `
    <details class="section-block" open>
      <summary class="section-summary">
        <span class="section-name">${esc(g.letter)}</span>
        <span class="section-meta">${g.artists.length} artist${g.artists.length !== 1 ? 's' : ''}</span>
        <button type="button" class="btn btn-xs btn-secondary section-export-btn"
          onclick="event.preventDefault();downloadIndexLetterExport('${esc(importId)}','${esc(g.letter)}',this)">
          Export &ldquo;${esc(g.letter)}&rdquo;
        </button>
      </summary>
      <table class="data-table index-table">
        ${theadHTML}
        <tbody>${rows}</tbody>
      </table>
    </details>`;
  }).join('');
}

/**
 * Build a rich HTML index name with styled honorifics and RA surname indicator.
 * Mirrors the structure of backend build_index_name() but adds visual cues
 * matching the character styles used in the InDesign Tagged Text export.
 */
function styledIndexName(a) {
  const surname = a.last_name || a.first_name || '';
  if (!surname) return '';

  // commaParts: surname, first name — joined with ", "
  // nameParts: quals — joined with space after the name
  const commaParts = [];
  const nameParts = [];

  // Surname — per-artist RA styling flag
  if (a.artist1_ra_styled) {
    commaParts.push(`<span class="idx-ra-styled" title="Styled as RA Member in print">${esc(surname)}</span>`);
  } else {
    commaParts.push(esc(surname));
  }

  // First name with optional title (only when both names present, not a company)
  if (!a.is_company && a.last_name && a.first_name) {
    const rest = [];
    if (a.title) rest.push(esc(a.title));
    rest.push(esc(a.first_name));
    commaParts.push(rest.join(' '));
  }

  // Quals — shown as a pill, different styling for RA vs non-RA
  // Quals follow the name with a space (no comma), matching LoW convention
  if (a.quals) {
    const pillClass = a.artist1_ra_styled ? 'honorifics-pill idx-ra-quals' : 'honorifics-pill';
    nameParts.push(`<span class="${pillClass}">${esc(a.quals)}</span>`);
  }

  // Additional artists from structured fields (never for companies)
  const suffixes = [];
  function _addArtist(first, last, quals, raStyled) {
    if (!first && !last) return;
    const parts = ['and'];
    if (first) parts.push(esc(first));
    if (last) {
      if (raStyled) parts.push(`<span class="idx-ra-styled">${esc(last)}</span>`);
      else parts.push(esc(last));
    }
    let suffix = parts.join(' ');
    if (quals) {
      const pillClass = raStyled ? 'honorifics-pill idx-ra-quals' : 'honorifics-pill';
      suffix += ` <span class="${pillClass}">${esc(quals)}</span>`;
    }
    suffixes.push(suffix);
  }
  if (!a.is_company) {
    _addArtist(a.artist2_first_name, a.artist2_last_name, a.artist2_quals, a.artist2_ra_styled);
    _addArtist(a.artist3_first_name, a.artist3_last_name, a.artist3_quals, a.artist3_ra_styled);
  }

  let result = commaParts.join(', ');
  if (nameParts.length) result += ' ' + nameParts.join(' ');
  if (suffixes.length) result += ', ' + suffixes.join(', ');
  return result;
}

function indexArtistRowHTML(importId, a, groupColor) {
  const included = a.include_in_export !== false;
  const groupStyle = groupColor ? `border-left: 4px solid ${groupColor};` : '';
  const badges = [];
  if (a.is_ra_member) badges.push('<span class="badge badge-ra">RA</span>');
  const isOverridden = a.is_company !== a.is_company_auto;
  const overrideClass = isOverridden ? ' badge-overridden' : '';
  if (a.is_company) {
    badges.push(canEdit()
      ? `<button class="badge badge-company badge-toggle${overrideClass}" title="${isOverridden ? 'Overridden — click to revert' : 'Click to mark as individual'}" onclick="toggleIndexCompany('${esc(importId)}','${esc(a.id)}',false)">Company</button>`
      : '<span class="badge badge-company">Company</span>');
  } else {
    badges.push(canEdit()
      ? `<button class="badge badge-company-off badge-toggle${overrideClass}" title="${isOverridden ? 'Overridden — click to revert' : 'Click to mark as company'}" onclick="toggleIndexCompany('${esc(importId)}','${esc(a.id)}',true)">Company?</button>`
      : '');
  }

  // Detect normalisation changes
  const hasNorm = (a.raw_last_name ?? '') !== (a.last_name ?? '')
    || (a.raw_first_name ?? '') !== (a.first_name ?? '')
    || (a.raw_quals ?? '') !== (a.quals ?? '');
  if (hasNorm) badges.push('<span class="badge badge-normalised" title="Values changed by normalisation">Norm</span>');
  if (a.has_known_artist) badges.push('<span class="badge badge-known" title="Matched a Known Artist rule">Known</span>');
  if (a.has_override) badges.push('<span class="badge badge-override" title="Has a user override">Override</span>');
  if (a.merged_from_rows && a.merged_from_rows.length > 1) {
    badges.push(`<span class="badge badge-merged" title="Merged from spreadsheet rows ${a.merged_from_rows.join(', ')}">Merged</span>`);
  }

  // Group cat numbers by courtesy
  const courtesyGroups = {};
  for (const cn of (a.cat_numbers || [])) {
    const key = cn.courtesy || '';
    if (!courtesyGroups[key]) courtesyGroups[key] = [];
    courtesyGroups[key].push(cn.cat_no);
  }
  const catDisplay = Object.entries(courtesyGroups).map(([courtesy, nums]) => {
    const numStr = nums.join(', ');
    return courtesy ? `${numStr} (${courtesy})` : numStr;
  }).join('; ');

  const courtesyDisplay = a.company || Object.keys(courtesyGroups).filter(k => k).join('; ');

  // Normalisation diff detection
  function diffCell(raw, normalised, label) {
    const r = raw ?? '';
    const n = normalised ?? '';
    if (r === n || (!r && !n)) return esc(n);
    return `<span class="norm-changed" title="Raw: ${esc(r)}">${esc(n)}</span>`;
  }

  // Additional artists display
  const additionalArtists = [];
  if (a.artist2_first_name || a.artist2_last_name) {
    const parts = [a.artist2_first_name, a.artist2_last_name].filter(Boolean);
    additionalArtists.push(parts.join(' '));
  }
  if (a.artist3_first_name || a.artist3_last_name) {
    const parts = [a.artist3_first_name, a.artist3_last_name].filter(Boolean);
    additionalArtists.push(parts.join(' '));
  }
  const additionalArtistDisplay = additionalArtists.length
    ? ` <span class="second-artist">${esc('and ' + additionalArtists.join(' and '))}</span>` : '';

  return `
    <tr id="idx-${esc(a.id)}" class="index-row ${included ? '' : 'row-excluded'}" style="${groupStyle}" onclick="toggleIndexDetail('${esc(a.id)}')">
      <td class="col-index-name">${styledIndexName(a)}</td>
      <td class="col-lastname">${diffCell(a.raw_last_name, a.last_name)}${additionalArtistDisplay}</td>
      <td>${diffCell(a.raw_first_name, a.first_name)}</td>
      <td>${esc(a.title ?? '')}</td>
      <td class="col-quals">${diffCell(a.raw_quals, a.quals)}</td>
      <td class="col-courtesy">${esc(courtesyDisplay)}</td>
      <td class="col-catnos">${esc(catDisplay)}</td>
      <td class="col-flags">${badges.join(' ')}</td>
      <td class="col-include">
        ${canEdit() ? `<input type="checkbox" class="include-cb${included ? '' : ' excluded'}" id="idx-incl-${esc(a.id)}"
          ${included ? 'checked' : ''}
          onclick="event.stopPropagation()"
          onchange="toggleIndexInclude('${esc(importId)}','${esc(a.id)}',this)">` : (included ? '\u2713' : '\u2717')}
      </td>
    </tr>
    <tr id="idx-detail-${esc(a.id)}" class="index-detail-row" style="display:none">
      <td colspan="9">
        <div class="index-detail">
          <table class="detail-table">
            <thead><tr><th>Field</th><th>Spreadsheet (raw)</th><th>Normalised</th></tr></thead>
            <tbody>
              <tr><td>Last Name</td><td>${esc(a.raw_last_name ?? '')}</td><td class="${(a.raw_last_name ?? '') !== (a.last_name ?? '') ? 'norm-highlight' : ''}">${esc(a.last_name ?? '')}</td></tr>
              <tr><td>First Name</td><td>${esc(a.raw_first_name ?? '')}</td><td class="${(a.raw_first_name ?? '') !== (a.first_name ?? '') ? 'norm-highlight' : ''}">${esc(a.first_name ?? '')}</td></tr>
              <tr><td>Quals</td><td>${esc(a.raw_quals ?? '')}</td><td class="${(a.raw_quals ?? '') !== (a.quals ?? '') ? 'norm-highlight' : ''}">${esc(a.quals ?? '')}</td></tr>
              <tr><td>Company</td><td>${esc(a.raw_company ?? '')}</td><td>${esc(a.company ?? '')}</td></tr>
              <tr><td>Address</td><td>${esc(a.raw_address ?? '')}</td><td><em class="muted">courtesy field</em></td></tr>
              <tr><td>RA Styled</td><td colspan="2">${a.artist1_ra_styled ? 'Yes' : 'No'}${a.artist2_ra_styled ? ' / A2: Yes' : ''}${a.artist3_ra_styled ? ' / A3: Yes' : ''}</td></tr>
              ${a.artist2_first_name || a.artist2_last_name ? `<tr><td>Artist 2</td><td colspan="2">${esc([a.artist2_first_name, a.artist2_last_name, a.artist2_quals].filter(Boolean).join(' '))}</td></tr>` : ''}
              ${a.artist3_first_name || a.artist3_last_name ? `<tr><td>Artist 3</td><td colspan="2">${esc([a.artist3_first_name, a.artist3_last_name, a.artist3_quals].filter(Boolean).join(' '))}</td></tr>` : ''}
            </tbody>
          </table>
          <div style="margin-top:8px">
            ${ifEditor(`<button class="btn btn-sm ${a.has_override ? 'btn-warning' : ''}" id="idx-ov-btn-${esc(a.id)}"
              onclick="event.stopPropagation(); toggleIndexOverrideForm('${esc(importId)}','${esc(a.id)}')">${a.has_override ? 'Edit Override' : 'Override\u2026'}</button>`)}
            ${canEdit() && a.merged_from_rows && a.merged_from_rows.length > 1 ? `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); unmergeArtist('${esc(importId)}','${esc(a.id)}')" title="Split back into ${a.merged_from_rows.length} separate entries (rows ${a.merged_from_rows.join(', ')})">Unmerge (rows ${a.merged_from_rows.join(', ')})</button>` : ''}
          </div>
          <div id="idx-ovc-${esc(a.id)}"></div>
        </div>
      </td>
    </tr>`;
}

function toggleIndexDetail(artistId) {
  const detailRow = document.getElementById(`idx-detail-${artistId}`);
  if (!detailRow) return;
  detailRow.style.display = detailRow.style.display === 'none' ? '' : 'none';
}

async function toggleIndexInclude(importId, artistId, checkbox) {
  const nowIncluded = checkbox.checked;
  checkbox.disabled = true;
  try {
    await api('PATCH', `/index/imports/${importId}/artists/${artistId}/exclude?exclude=${!nowIncluded}`);
    const row = document.getElementById(`idx-${artistId}`);
    if (row) row.className = `index-row ${nowIncluded ? '' : 'row-excluded'}`;
    checkbox.className = `include-cb${nowIncluded ? '' : ' excluded'}`;
  } catch (err) {
    checkbox.checked = !nowIncluded;
    showToast(`Toggle failed: ${err.message}`, 'error');
  } finally {
    checkbox.disabled = false;
  }
}

async function toggleIndexCompany(importId, artistId, newValue) {
  try {
    const resp = await api('PATCH', `/index/imports/${importId}/artists/${artistId}/company?is_company=${newValue}`);
    // Update cache and re-render the row
    const a = _indexArtistCache[artistId];
    if (a) {
      a.is_company = resp.is_company;
      if (resp.is_company_auto !== undefined) a.is_company_auto = resp.is_company_auto;
      const row = document.getElementById(`idx-${artistId}`);
      if (row) {
        const tmp = document.createElement('tbody');
        tmp.innerHTML = indexArtistRowHTML(importId, a);
        row.replaceWith(tmp.firstElementChild);
      }
    }
  } catch (err) {
    showToast(`Toggle failed: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Unmerge
// ---------------------------------------------------------------------------

async function unmergeArtist(importId, artistId) {
  if (!confirm('Split this merged entry back into separate entries?')) return;
  try {
    const resp = await api('POST', `/index/imports/${importId}/artists/${artistId}/unmerge`);
    showToast(`Unmerged into ${(resp.new_artist_ids?.length ?? 0) + 1} entries`, 'success');
    renderIndexDetail(importId);
  } catch (err) {
    showToast(`Unmerge failed: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Index artist override form
// ---------------------------------------------------------------------------

async function toggleIndexOverrideForm(importId, artistId) {
  const cell = document.getElementById(`idx-ovc-${artistId}`);
  if (!cell) return;
  // If form already visible, close it
  if (cell.innerHTML.trim()) {
    cell.innerHTML = '';
    const btn = document.getElementById(`idx-ov-btn-${artistId}`);
    if (btn) {
      const a = _indexArtistCache[artistId];
      const has = a?.has_override;
      btn.textContent = has ? 'Edit Override' : 'Override\u2026';
      btn.className = `btn btn-sm ${has ? 'btn-warning' : ''}`;
    }
    return;
  }

  // Try to load existing override
  let existing = null;
  try {
    existing = await api('GET', `/index/imports/${importId}/artists/${artistId}/override`);
  } catch (_) {
    // 404 = no override yet
  }
  showIndexOverrideForm(importId, artistId, existing);
}

function showIndexOverrideForm(importId, artistId, existing) {
  const val = (f) => esc(existing?.[f] ?? '');

  // Effective current value = override if set, else current resolved from cache
  const a = _indexArtistCache[artistId] ?? {};
  const o = existing ?? {};
  const cur = {
    first_name_override:              o.first_name_override              ?? a.first_name              ?? '',
    last_name_override:               o.last_name_override               ?? a.last_name               ?? '',
    title_override:                   o.title_override                   ?? a.title                   ?? '',
    quals_override:                   o.quals_override                   ?? a.quals                   ?? '',
    artist2_first_name_override:      o.artist2_first_name_override      ?? a.artist2_first_name      ?? '',
    artist2_last_name_override:       o.artist2_last_name_override       ?? a.artist2_last_name       ?? '',
    artist2_quals_override:           o.artist2_quals_override           ?? a.artist2_quals            ?? '',
    artist3_first_name_override:      o.artist3_first_name_override      ?? a.artist3_first_name      ?? '',
    artist3_last_name_override:       o.artist3_last_name_override       ?? a.artist3_last_name       ?? '',
    artist3_quals_override:           o.artist3_quals_override           ?? a.artist3_quals            ?? '',
  };

  // Returns a clickable hint that copies the current value into the named input
  const hint = (field, inputName) => {
    const v = cur[field];
    if (v === null || v === undefined || v === '') return '';
    const safe = esc(String(v));
    const b64 = btoa(unescape(encodeURIComponent(String(v))));
    return `<button type="button" class="current-val-hint"
      onclick="(function(){var el=document.querySelector('#idx-ovf-${esc(artistId)} [name=\\'${inputName}\\']');if(el)el.value=decodeURIComponent(escape(atob('${b64}')));})()">
      ${safe}</button>`;
  };

  const companyChecked = o.is_company_override === true ? ' checked' : '';
  const companyIndeterminate = o.is_company_override === null || o.is_company_override === undefined;

  const cell = document.getElementById(`idx-ovc-${artistId}`);
  cell.innerHTML = `
    <div class="override-form" style="margin-top:10px" onclick="event.stopPropagation()">
      <h5>Override Fields <span class="muted" style="text-transform:none;font-weight:400">&ndash; leave blank to use current value &middot; click current value to copy</span></h5>
      <div class="override-field-form" id="idx-ovf-${esc(artistId)}">
        <div class="form-row"><label>Last Name</label>
          ${hint('last_name_override','last_name_override')}
          <input type="text" name="last_name_override" value="${val('last_name_override')}" placeholder="Override last name"></div>
        <div class="form-row"><label>First Name</label>
          ${hint('first_name_override','first_name_override')}
          <input type="text" name="first_name_override" value="${val('first_name_override')}" placeholder="Override first name"></div>
        <div class="form-row"><label>Title</label>
          ${hint('title_override','title_override')}
          <input type="text" name="title_override" value="${val('title_override')}" placeholder="Override title (e.g. Sir)"></div>
        <div class="form-row"><label>Quals</label>
          ${hint('quals_override','quals_override')}
          <input type="text" name="quals_override" value="${val('quals_override')}" placeholder="Override quals (e.g. CBE RA)"></div>
        <div class="form-row"><label>A2 First Name</label>
          ${hint('artist2_first_name_override','artist2_first_name_override')}
          <input type="text" name="artist2_first_name_override" value="${val('artist2_first_name_override')}" placeholder="Artist 2 first name"></div>
        <div class="form-row"><label>A2 Last Name</label>
          ${hint('artist2_last_name_override','artist2_last_name_override')}
          <input type="text" name="artist2_last_name_override" value="${val('artist2_last_name_override')}" placeholder="Artist 2 last name"></div>
        <div class="form-row"><label>A2 Quals</label>
          ${hint('artist2_quals_override','artist2_quals_override')}
          <input type="text" name="artist2_quals_override" value="${val('artist2_quals_override')}" placeholder="Artist 2 quals"></div>
        <div class="form-row"><label>A3 First Name</label>
          ${hint('artist3_first_name_override','artist3_first_name_override')}
          <input type="text" name="artist3_first_name_override" value="${val('artist3_first_name_override')}" placeholder="Artist 3 first name"></div>
        <div class="form-row"><label>A3 Last Name</label>
          ${hint('artist3_last_name_override','artist3_last_name_override')}
          <input type="text" name="artist3_last_name_override" value="${val('artist3_last_name_override')}" placeholder="Artist 3 last name"></div>
        <div class="form-row"><label>A3 Quals</label>
          ${hint('artist3_quals_override','artist3_quals_override')}
          <input type="text" name="artist3_quals_override" value="${val('artist3_quals_override')}" placeholder="Artist 3 quals"></div>
        <div class="form-row"><label>RA Styling</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" name="artist1_ra_styled_override" ${o.artist1_ra_styled_override === true ? 'checked' : ''}
              ${o.artist1_ra_styled_override === null || o.artist1_ra_styled_override === undefined ? 'data-indeterminate="1"' : ''}>
            A1
          </label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" name="artist2_ra_styled_override" ${o.artist2_ra_styled_override === true ? 'checked' : ''}
              ${o.artist2_ra_styled_override === null || o.artist2_ra_styled_override === undefined ? 'data-indeterminate="1"' : ''}>
            A2
          </label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" name="artist3_ra_styled_override" ${o.artist3_ra_styled_override === true ? 'checked' : ''}
              ${o.artist3_ra_styled_override === null || o.artist3_ra_styled_override === undefined ? 'data-indeterminate="1"' : ''}>
            A3
          </label>
        </div>
        <div class="form-row"><label>Company</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" name="is_company_override" ${companyChecked}
              ${companyIndeterminate ? 'data-indeterminate="1"' : ''}>
            Mark as company
          </label>
        </div>
        <div class="form-actions">
          <button class="btn btn-primary" onclick="saveIndexOverride('${esc(importId)}','${esc(artistId)}')">Save</button>
          ${existing ? `<button class="btn btn-danger" onclick="deleteIndexOverride('${esc(importId)}','${esc(artistId)}')">Delete Override</button>` : ''}
          <span id="idx-ovs-${esc(artistId)}" class="status-msg"></span>
        </div>
      </div>
    </div>`;
}

/** Re-render visible index artist row cells after override save/delete. */
function _refreshIndexArtistRow(importId, artistId) {
  const a = _indexArtistCache[artistId];
  if (!a) return;
  const tmp = document.createElement('tbody');
  tmp.innerHTML = indexArtistRowHTML(importId, a);
  const oldRow = document.getElementById(`idx-${artistId}`);
  const newRow = tmp.querySelector(`#idx-${CSS.escape(artistId)}`);
  if (oldRow && newRow) oldRow.replaceWith(newRow);
  // Also replace the detail row
  const oldDetail = document.getElementById(`idx-detail-${artistId}`);
  const newDetail = tmp.querySelector(`#idx-detail-${CSS.escape(artistId)}`);
  if (oldDetail && newDetail) oldDetail.replaceWith(newDetail);
}

async function saveIndexOverride(importId, artistId) {
  const formEl = document.getElementById(`idx-ovf-${artistId}`);
  const statusEl = document.getElementById(`idx-ovs-${artistId}`);
  statusEl.textContent = 'Saving\u2026';
  statusEl.className = 'status-msg';

  const textFields = ['first_name_override', 'last_name_override', 'title_override',
    'quals_override', 'artist2_first_name_override', 'artist2_last_name_override',
    'artist2_quals_override', 'artist3_first_name_override', 'artist3_last_name_override',
    'artist3_quals_override'];

  const body = {};
  for (const f of textFields) {
    const input = formEl.querySelector(`[name="${f}"]`);
    const raw = input?.value.trim() ?? '';
    body[f] = raw === '' ? null : raw;
  }

  // Company checkbox: unchecked + was indeterminate = null (no override)
  // otherwise true/false
  const companyCb = formEl.querySelector('[name="is_company_override"]');
  if (companyCb) {
    if (companyCb.dataset.indeterminate === '1' && !companyCb.checked) {
      body.is_company_override = null;
    } else {
      body.is_company_override = companyCb.checked;
    }
    // Once user interacts, it's no longer indeterminate
    delete companyCb.dataset.indeterminate;
  }

  // RA styled checkboxes: same indeterminate logic
  for (const raField of ['artist1_ra_styled_override', 'artist2_ra_styled_override', 'artist3_ra_styled_override']) {
    const cb = formEl.querySelector(`[name="${raField}"]`);
    if (cb) {
      if (cb.dataset.indeterminate === '1' && !cb.checked) {
        body[raField] = null;
      } else {
        body[raField] = cb.checked;
      }
      delete cb.dataset.indeterminate;
    }
  }

  try {
    const result = await api('PUT', `/index/imports/${importId}/artists/${artistId}/override`, body);
    // Re-fetch the artist list to get recalculated index_name, is_company etc.
    await _reloadIndexArtist(importId, artistId);
    const a = _indexArtistCache[artistId];
    if (a) a.has_override = true;
    _refreshIndexArtistRow(importId, artistId);
    // Re-open the form with the saved data, and make detail row visible
    const detailRow = document.getElementById(`idx-detail-${artistId}`);
    if (detailRow) detailRow.style.display = '';
    showIndexOverrideForm(importId, artistId, result);
    const s = document.getElementById(`idx-ovs-${artistId}`);
    if (s) { s.textContent = '\u2713 Saved'; s.className = 'status-msg success'; }
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.className = 'status-msg error';
  }
}

async function deleteIndexOverride(importId, artistId) {
  if (!confirm('Delete all overrides for this artist?')) return;
  const statusEl = document.getElementById(`idx-ovs-${artistId}`);
  try {
    await api('DELETE', `/index/imports/${importId}/artists/${artistId}/override`);
    await _reloadIndexArtist(importId, artistId);
    const a = _indexArtistCache[artistId];
    if (a) a.has_override = false;
    _refreshIndexArtistRow(importId, artistId);
    const detailRow = document.getElementById(`idx-detail-${artistId}`);
    if (detailRow) detailRow.style.display = '';
    showIndexOverrideForm(importId, artistId, null);
    const s = document.getElementById(`idx-ovs-${artistId}`);
    if (s) { s.textContent = '\u2713 Deleted'; s.className = 'status-msg success'; }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = `Error: ${err.message}`;
      statusEl.className = 'status-msg error';
    }
  }
}

/** Re-fetch a single artist's resolved data and update the cache. */
async function _reloadIndexArtist(importId, artistId) {
  try {
    const artists = await api('GET', `/index/imports/${importId}/artists`);
    const found = artists.find(a => a.id === artistId);
    if (found) {
      _indexArtistCache[artistId] = found;
    }
  } catch (_) {
    // Fallback: ignore; the cached data will be stale
  }
}

function _applyIndexFilter(query, countEl, totalArtists) {
  const q = query.trim().toLowerCase();
  const rows = document.querySelectorAll('.index-row');
  let visible = 0;
  rows.forEach(row => {
    if (!q) {
      row.style.display = '';
      visible++;
      return;
    }
    const text = row.textContent.toLowerCase();
    const match = text.includes(q);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  // Show/hide letter-group blocks that have no visible rows
  document.querySelectorAll('#index-artists-container .section-block').forEach(block => {
    const visibleRows = block.querySelectorAll('.index-row');
    const anyVisible = Array.from(visibleRows).some(r => r.style.display !== 'none');
    block.style.display = (!q || anyVisible) ? '' : 'none';
  });
  if (q) {
    countEl.textContent = `${visible} of ${totalArtists} artists`;
  } else {
    countEl.textContent = '';
  }
}

// ---------------------------------------------------------------------------
// Index — export download
// ---------------------------------------------------------------------------

async function downloadIndexExport(importId, btnEl) {
  const sel = document.getElementById(`idx-tmpl-select-${importId}`);
  const tid = sel?.value || null;
  if (tid) localStorage.setItem('catalogue_last_index_template', tid);

  const restore = btnLoading(btnEl, 'Exporting');
  try {
    let path = `/index/imports/${importId}/export-tags`;
    const params = [];
    if (tid) params.push(`template_id=${encodeURIComponent(tid)}`);
    if (params.length) path += '?' + params.join('&');
    const res = await fetch(path, {
      headers: _apiHeaders(),
    });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const now = new Date();
    const ts = now.getFullYear().toString()
      + String(now.getMonth() + 1).padStart(2, '0')
      + String(now.getDate()).padStart(2, '0')
      + '-'
      + String(now.getHours()).padStart(2, '0')
      + String(now.getMinutes()).padStart(2, '0')
      + String(now.getSeconds()).padStart(2, '0');
    const a = document.createElement('a');
    a.href = url;
    a.download = `artists-index-${importId.slice(0, 8)}-${ts}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Index export downloaded', 'success', 2500);
  } catch (err) {
    showToast(`Export failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}

async function downloadIndexLetterExport(importId, letter, btnEl) {
  const sel = document.getElementById(`idx-tmpl-select-${importId}`);
  const tid = sel?.value || null;
  if (tid) localStorage.setItem('catalogue_last_index_template', tid);

  const restore = btnLoading(btnEl, 'Exporting');
  try {
    let path = `/index/imports/${importId}/export-tags`;
    const params = [`letter=${encodeURIComponent(letter)}`];
    if (tid) params.push(`template_id=${encodeURIComponent(tid)}`);
    path += '?' + params.join('&');
    const res = await fetch(path, {
      headers: _apiHeaders(),
    });
    if (res.status === 401) { renderLogin('Invalid or missing API key.'); return; }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const now = new Date();
    const ts = now.getFullYear().toString()
      + String(now.getMonth() + 1).padStart(2, '0')
      + String(now.getDate()).padStart(2, '0')
      + '-'
      + String(now.getHours()).padStart(2, '0')
      + String(now.getMinutes()).padStart(2, '0')
      + String(now.getSeconds()).padStart(2, '0');
    const a = document.createElement('a');
    a.href = url;
    a.download = `artists-index-${letter}-${importId.slice(0, 8)}-${ts}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(`Letter "${letter}" exported`, 'success', 2500);
  } catch (err) {
    showToast(`Export failed: ${err.message}`, 'error');
  } finally {
    restore();
  }
}
