'use strict';

// ---------------------------------------------------------------------------
// Auth state
// ---------------------------------------------------------------------------

let _apiKey = localStorage.getItem('ra_api_key') || '';

function _syncHeader() {
  const existing = document.getElementById('logout-btn');
  if (_apiKey) {
    if (!existing) {
      const btn = document.createElement('button');
      btn.id = 'logout-btn';
      btn.className = 'btn btn-sm btn-secondary';
      btn.style.cssText = 'margin-left:auto;font-size:0.75rem';
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
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const opts = { method, headers: { 'X-API-Key': _apiKey } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  if (res.status === 401) { renderLogin('Invalid or missing API key.'); throw new Error('Unauthorised'); }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch {}
    throw new Error(msg);
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

function handleLogin() {
  const key = (document.getElementById('login-key-input')?.value ?? '').trim();
  _apiKey = key;
  if (key) localStorage.setItem('ra_api_key', key);
  else localStorage.removeItem('ra_api_key');
  _syncHeader();
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
  const isSettings = hash === '#/settings';
  document.querySelectorAll('.site-nav a').forEach(a => {
    const wantsSettings = a.getAttribute('href') === '#/settings';
    a.classList.toggle('active', wantsSettings === isSettings);
  });
}

function router() {
  _syncHeader();
  _highlightNav();
  const hash = location.hash || '#/';
  const m = hash.match(/^#\/import\/([^/]+)/);
  if (m) renderDetail(m[1]);
  else if (hash === '#/settings') renderSettings();
  else    renderList();
}

window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', () => { _syncHeader(); router(); });

// ---------------------------------------------------------------------------
// Settings page
// ---------------------------------------------------------------------------

async function renderSettings() {
  const app = document.getElementById('app');
  app.innerHTML = '<p class="loading" style="padding:40px 0">Loading settings&hellip;</p>';
  let cfg;
  try { cfg = await api('GET', '/config'); }
  catch (e) { app.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }

  // Load display prefs
  let dispRaw = {};
  try { dispRaw = JSON.parse(localStorage.getItem('ra_display_cfg') || '{}'); } catch {}
  const dispMirror = dispRaw.mirror !== false;
  const dispCurr   = dispRaw.currency_symbol    ?? cfg.currency_symbol    ?? '£';
  const dispSep    = dispRaw.thousands_separator ?? cfg.thousands_separator ?? ',';
  const dispDp     = dispRaw.decimal_places      ?? cfg.decimal_places     ?? 0;

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
  const _sepOpts = (val) => [
    ['none',         'none'],
    ['space',        'space'],
    ['tab',          'tab'],
    ['right_tab',    'right-indent tab (uses tab stop)'],
    ['soft_return',  'soft return (\\n)'],
    ['hard_return',  'hard return'],
  ].map(([v, label]) => `<option value="${v}"${val === v ? ' selected' : ''}>${label}</option>`).join('');

  const honorificTokensValue = Array.isArray(cfg.honorific_tokens)
    ? cfg.honorific_tokens.join(', ')
    : (cfg.honorific_tokens ?? 'RA, PRA, PPRA, HON, HONRA, ELECT, EX, OFFICIO');

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
  // Merge: if a saved config is missing a known component, append it with defaults
  const savedComponents = cfg.components ?? defaultComponents;
  const savedFields = new Set(savedComponents.map(c => c.field));
  const mergedComponents = [
    ...savedComponents,
    ...defaultComponents.filter(c => !savedFields.has(c.field)),
  ];
  const componentRowsHTML = mergedComponents.map(c => {
    const label = COMP_LABELS[c.field] ?? c.field;
    const enabled = c.enabled ?? true;
    const maxChars = c.max_line_chars ?? '';
    const nextPos = c.next_component_position ?? 'end_of_text';
    const balance = c.balance_lines ?? false;
    const posDisabled = maxChars === '' || maxChars === null ? 'disabled' : '';
    const balDisabled = posDisabled;
    return `
    <div class="component-row" data-field="${esc(c.field)}" style="opacity:${enabled ? 1 : 0.45}">
      <div class="component-main">
        <div class="component-handle">
          <button type="button" class="btn-icon" onclick="moveComponent(this,-1)" title="Move up">▲</button>
          <button type="button" class="btn-icon" onclick="moveComponent(this,1)" title="Move down">▼</button>
        </div>
        <span class="component-label">${esc(label)}</span>
        <select class="component-sep">${_sepOpts(c.separator_after)}</select>
        <label class="inline-check"><input type="checkbox" class="component-omit-sep" ${(c.omit_sep_when_empty ?? true) ? 'checked' : ''}> omit when empty</label>
        <label class="component-toggle" title="Include this component in the export">
          <input type="checkbox" class="component-enabled" ${enabled ? 'checked' : ''}
            onchange="this.closest('.component-row').style.opacity = this.checked ? 1 : 0.45"> include
        </label>
      </div>
      <div class="component-wrap-opts">
        <label>max chars/line <input type="number" class="component-max-chars" min="1" style="width:4.5em"
          value="${maxChars}" placeholder="none"
          oninput="const r=this.closest('.component-row');r.querySelector('.component-next-pos').disabled=!this.value;r.querySelector('.component-balance').disabled=!this.value"></label>
        <label>next component at
          <select class="component-next-pos" ${posDisabled}>
            <option value="end_of_text" ${nextPos==='end_of_text'?'selected':''}>end of text</option>
            <option value="end_of_first_line" ${nextPos==='end_of_first_line'?'selected':''}>end of first line</option>
          </select>
          <span class="form-hint" style="display:inline">(soft returns used for line breaks within field)</span>
        </label>
        <label class="inline-check"><input type="checkbox" class="component-balance" ${balance?'checked':''} ${balDisabled}> balance lines</label>
      </div>
    </div>`;
  }).join('');

  app.innerHTML = `
    <h2 class="page-heading">Settings</h2>

    <h3 class="settings-group-heading">Normalisation</h3>
    <p class="settings-group-desc">Applied when an Excel file is imported. Changes here take effect on the <em>next</em> import.</p>
    <section class="panel">
      <h4 class="panel-subheading">Honorific Tokens</h4>
      <div class="settings-form">
        <div class="form-row">
          <label>Recognised tokens</label>
          <input id="cfg-honorific-tokens" type="text" value="${esc(honorificTokensValue)}">
          <span class="form-hint">Comma-separated list of abbreviations stripped from the end of artist names, e.g. &ldquo;RA, HON, PRA&rdquo;</span>
        </div>
      </div>
    </section>

    <h3 class="settings-group-heading">Export</h3>
    <p class="settings-group-desc">Saved to the server and applied to all InDesign tagged-text exports.</p>
    <section class="panel">
      <h4 class="panel-subheading">Formatting</h4>
      <div class="settings-form">
        <div class="form-row">
          <label>Currency symbol</label>
          <input id="cfg-currency" type="text" value="${esc(cfg.currency_symbol)}" style="max-width:80px">
        </div>
        <div class="form-row">
          <label>Thousands separator</label>
          <select id="cfg-thousands-sep">
            <option value=","  ${cfg.thousands_separator === ','  ? 'selected' : ''}>, &nbsp; 1,000</option>
            <option value="."  ${cfg.thousands_separator === '.'  ? 'selected' : ''}>. &nbsp; 1.000</option>
            <option value=" "  ${cfg.thousands_separator === ' '  ? 'selected' : ''}>space &nbsp; 1 000</option>
            <option value=""   ${cfg.thousands_separator === ''   ? 'selected' : ''}>none &nbsp; 1000</option>
          </select>
        </div>
        <div class="form-row">
          <label>Decimal places</label>
          <select id="cfg-decimal-places">
            <option value="0" ${cfg.decimal_places === 0 ? 'selected' : ''}>0 &nbsp;&mdash;&nbsp; 1,500</option>
            <option value="2" ${cfg.decimal_places === 2 ? 'selected' : ''}>2 &nbsp;&mdash;&nbsp; 1,500.00</option>
          </select>
        </div>
        <div class="form-row">
          <label>Edition prefix</label>
          <input id="cfg-edition-prefix" type="text" value="${esc(cfg.edition_prefix)}">
          <span class="form-hint">e.g. &ldquo;edition of&rdquo; &rarr; &ldquo;edition of 10 at &pound;500&rdquo;</span>
        </div>
        <div class="form-row">
          <label>Edition brackets</label>
          <label class="inline-check" style="text-transform:none;font-weight:normal">
            <input type="checkbox" id="cfg-edition-brackets"${cfg.edition_brackets !== false ? ' checked' : ''}>
            Wrap edition info in brackets
          </label>
          <span class="form-hint">e.g. &ldquo;(edition of 10 at &pound;500)&rdquo; vs &ldquo;edition of 10 at &pound;500&rdquo;</span>
        </div>
      </div>
    </section>
    <section class="panel">
      <h4 class="panel-subheading">InDesign Paragraph Styles</h4>
      <div class="settings-form">
        <div class="form-row">
          <label>Section heading</label>
          <input id="cfg-section-style" type="text" value="${esc(cfg.section_style)}">
          <span class="form-hint">Applied to section / room headings</span>
        </div>
        <div class="form-row">
          <label>Entry paragraph</label>
          <input id="cfg-entry-style" type="text" value="${esc(cfg.entry_style)}">
          <span class="form-hint">Applied to each catalogue entry row</span>
        </div>
      </div>
    </section>
    <section class="panel">
      <h4 class="panel-subheading">InDesign Character Styles</h4>
      <p style="color:var(--muted);font-size:12px;margin-bottom:14px">Leave blank to output plain text for that field.</p>
      <div class="settings-form">
        <div class="form-row">
          <label>Cat number</label>
          <input id="cfg-cat-no-style" type="text" value="${esc(cfg.cat_no_style)}">
        </div>
        <div class="form-row">
          <label>Artist name</label>
          <input id="cfg-artist-style" type="text" value="${esc(cfg.artist_style)}">
        </div>
        <div class="form-row">
          <label>Honorifics</label>
          <div class="form-row-controls">
            <input id="cfg-honorifics-style" type="text" value="${esc(cfg.honorifics_style)}">
            <label class="inline-check"><input id="cfg-honorifics-lowercase" type="checkbox" ${cfg.honorifics_lowercase ? 'checked' : ''}> force lowercase</label>
          </div>
          <span class="form-hint">Appended after artist name with a space. Use lowercase for small-caps character styles.</span>
        </div>
        <div class="form-row">
          <label>Title</label>
          <input id="cfg-title-style" type="text" value="${esc(cfg.title_style)}">
        </div>
        <div class="form-row">
          <label>Price</label>
          <input id="cfg-price-style" type="text" value="${esc(cfg.price_style)}">
        </div>
        <div class="form-row">
          <label>Medium</label>
          <input id="cfg-medium-style" type="text" value="${esc(cfg.medium_style ?? '')}">
        </div>
        <div class="form-row">
          <label>Artwork number</label>
          <input id="cfg-artwork-style" type="text" value="${esc(cfg.artwork_style ?? '')}">
        </div>
      </div>
    </section>
    <section class="panel">
      <h4 class="panel-subheading">Entry Layout</h4>
      <p style="color:var(--muted);font-size:12px;margin-bottom:16px">Drag to reorder with the arrows. The separator fires after each non-empty component. Right-align tab = <code>\y</code>, soft return = <code>\n</code> in InDesign tagged text.</p>
      <div class="form-row" style="margin-bottom:12px">
        <label>Leading separator</label>
        <select id="cfg-leading-sep">${_sepOpts(cfg.leading_separator ?? 'none')}</select>
        <span class="form-hint">Inserted before the first component</span>
      </div>
      <div id="cfg-components" class="component-list">${componentRowsHTML}</div>
      <div class="form-row" style="margin-top:12px">
        <label>Trailing separator</label>
        <select id="cfg-trailing-sep">${_sepOpts(cfg.trailing_separator ?? 'none')}</select>
        <span class="form-hint">Inserted after the last component</span>
      </div>
      <div class="form-row" style="margin-top:8px">
        <label class="inline-check" style="text-transform:none;font-size:13px">
          <input type="checkbox" id="cfg-final-sep-from-last"
            ${(cfg.final_sep_from_last_component ?? false) ? 'checked' : ''}>
          When last component is omitted, adopt its separator for the final non-empty field
        </label>
      </div>
    </section>

    <h3 class="settings-group-heading">Preview</h3>
    <p class="settings-group-desc">Controls how values appear in this browser view only &mdash; stored locally, never sent to the server.</p>
    <section class="panel">
      <h4 class="panel-subheading">HTML Preview Formatting</h4>
      <div class="settings-form" style="margin-bottom:14px">
        <div class="form-row" style="grid-column:1/-1">
          <label class="inline-check" style="text-transform:none;font-weight:500">
            <input type="checkbox" id="cfg-display-mirror"${dispMirror ? ' checked' : ''}
                   onchange="document.getElementById('display-custom').style.display=this.checked?'none':'grid'">
            Mirror currency &amp; price formatting from export settings
          </label>
          <p class="form-hint" style="margin:4px 0 0;grid-column:1/-1">When checked, the currency symbol, thousands separator and decimal places below are taken from the export settings above. Component order, inclusion, separators and character styles are never reflected in the preview.</p>
        </div>
      </div>
      <div id="display-custom" class="settings-form" style="display:${dispMirror ? 'none' : 'grid'}">
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
      </div>
    </section>

    <div class="form-actions" style="padding-bottom:20px">
      <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
      <span id="settings-status" class="status-msg"></span>
    </div>`;
}

async function saveSettings() {
  const rawTokens = (document.getElementById('cfg-honorific-tokens')?.value ?? '');
  const honorific_tokens = rawTokens.split(',').map(t => t.trim()).filter(Boolean);
  const components = Array.from(
    document.querySelectorAll('#cfg-components .component-row')
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
    honorific_tokens,
    leading_separator:   document.getElementById('cfg-leading-sep')?.value  ?? 'none',
    trailing_separator:  document.getElementById('cfg-trailing-sep')?.value ?? 'none',
    final_sep_from_last_component: document.getElementById('cfg-final-sep-from-last')?.checked ?? false,
    components,
    section_style:       (document.getElementById('cfg-section-style')?.value    ?? '').trim() || 'SectionTitle',
    entry_style:         (document.getElementById('cfg-entry-style')?.value      ?? '').trim() || 'CatalogueEntry',
    currency_symbol:     (document.getElementById('cfg-currency')?.value         ?? '').trim() || '£',
    edition_prefix:      (document.getElementById('cfg-edition-prefix')?.value   ?? '').trim() || 'edition of',
    edition_brackets:    document.getElementById('cfg-edition-brackets')?.checked ?? true,
    cat_no_style:        (document.getElementById('cfg-cat-no-style')?.value     ?? '').trim(),
    artist_style:        (document.getElementById('cfg-artist-style')?.value     ?? '').trim(),
    honorifics_style:    (document.getElementById('cfg-honorifics-style')?.value ?? '').trim(),
    honorifics_lowercase: document.getElementById('cfg-honorifics-lowercase')?.checked ?? false,
    title_style:         (document.getElementById('cfg-title-style')?.value      ?? '').trim(),
    price_style:         (document.getElementById('cfg-price-style')?.value      ?? '').trim(),
    medium_style:        (document.getElementById('cfg-medium-style')?.value     ?? '').trim(),
    artwork_style:       (document.getElementById('cfg-artwork-style')?.value    ?? '').trim(),
    thousands_separator: (document.getElementById('cfg-thousands-sep')?.value    ?? ','),
    decimal_places:      Number(document.getElementById('cfg-decimal-places')?.value ?? '0'),
  };
  const statusEl = document.getElementById('settings-status');
  if (!statusEl) return;
  statusEl.textContent = 'Saving\u2026';
  statusEl.className = 'status-msg';
  try {
    await api('PUT', '/config', body);
    // Save display prefs to localStorage
    const mirror = document.getElementById('cfg-display-mirror')?.checked !== false
                && document.getElementById('cfg-display-mirror') !== null
                ? document.getElementById('cfg-display-mirror').checked
                : true;
    _saveDisplayCfg(
      mirror,
      (document.getElementById('disp-currency')?.value       ?? '').trim() || '£',
      (document.getElementById('disp-thousands-sep')?.value  ?? ','),
      Number(document.getElementById('disp-decimal-places')?.value ?? '0'),
    );
    statusEl.textContent = '\u2713 Saved';
    statusEl.className = 'status-msg success';
  } catch (e) {
    statusEl.textContent = `Error: ${esc(e.message)}`;
    statusEl.className = 'status-msg error';
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
// Import list
// ---------------------------------------------------------------------------

async function renderList() {
  document.getElementById('app').innerHTML = `
    <section class="panel">
      <h3>Import Excel File</h3>
      <form id="upload-form" class="upload-form">
        <input type="file" id="file-input" accept=".xlsx,.xls" required>
        <button type="submit" class="btn btn-primary">Upload</button>
      </form>
      <p id="upload-status" class="status-msg" style="margin-top:8px"></p>
    </section>
    <section class="panel">
      <h3>Imports</h3>
      <div id="imports-list">Loading&hellip;</div>
    </section>`;

  document.getElementById('upload-form').addEventListener('submit', async (e) => {
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
    const rows = imports.map(i => `
      <tr>
        <td><code class="import-id" title="${esc(i.id)}">${esc(i.id.slice(0, 8))}&hellip;</code></td>
        <td><a class="link" href="#/import/${esc(i.id)}">${esc(i.filename)}</a></td>
        <td>${esc(formatDate(i.uploaded_at))}</td>
        <td class="num">${i.sections}</td>
        <td class="num">${i.works}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="navigate('#/import/${esc(i.id)}')">View</button>
          <button class="btn btn-sm btn-danger" onclick="handleDelete('${esc(i.id)}', '${esc(i.filename.replace(/'/g, ''))}')">Delete</button>
        </td>
      </tr>`).join('');
    container.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>ID</th><th>Filename</th><th>Uploaded</th>
          <th class="num">Sections</th><th class="num">Works</th>
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
  statusEl.textContent = 'Uploading\u2026';
  statusEl.className = 'status-msg';
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/import', { method: 'POST', body: form, headers: { 'X-API-Key': _apiKey } });
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
  }
}

async function handleDelete(id, filename) {
  if (!confirm(`Delete import \u201c${filename}\u201d? This cannot be undone.`)) return;
  try {
    await api('DELETE', `/imports/${id}`);
    await loadImportList();
  } catch (err) {
    alert(`Delete failed: ${err.message}`);
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

function _getDisplayCfg(exportCfg) {
  try {
    const raw = localStorage.getItem('ra_display_cfg');
    if (!raw) return exportCfg; // default: mirror
    const d = JSON.parse(raw);
    if (d.mirror !== false) return exportCfg;
    return {
      currency_symbol:    d.currency_symbol    ?? exportCfg?.currency_symbol    ?? '£',
      thousands_separator: d.thousands_separator ?? exportCfg?.thousands_separator ?? ',',
      decimal_places:     d.decimal_places     ?? exportCfg?.decimal_places     ?? 0,
    };
  } catch { return exportCfg; }
}

function _saveDisplayCfg(mirror, currency_symbol, thousands_separator, decimal_places) {
  localStorage.setItem('ra_display_cfg', JSON.stringify(
    mirror ? { mirror: true }
           : { mirror: false, currency_symbol, thousands_separator, decimal_places }
  ));
}

// ---------------------------------------------------------------------------
// Import detail
// ---------------------------------------------------------------------------

let _expandedWorkId = null;

async function renderDetail(importId) {
  _expandedWorkId = null;
  document.getElementById('app').innerHTML = `
    <div class="breadcrumb"><a href="#/">\u2190 All Imports</a></div>
    <h2 class="page-heading" id="detail-heading">Loading\u2026</h2>
    <section class="panel">
      <h3>Export</h3>
      <div class="export-buttons">
        <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','tags','txt')">InDesign Tags (.txt)</button>
        <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','json','json')">JSON</button>
        <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','xml','xml')">XML</button>
        <button class="btn btn-secondary" onclick="downloadExport('${esc(importId)}','csv','csv')">CSV</button>
      </div>
    </section>
    <section class="panel" id="warnings-panel"><p class="loading">Loading warnings\u2026</p></section>
    <section class="panel">
      <h3>Works</h3>
      <div id="sections-container"><p class="loading">Loading\u2026</p></div>
    </section>`;

  const [sections, warnings, exportCfg] = await Promise.all([
    api('GET', `/imports/${importId}/sections`).catch(e => { return { _error: e.message }; }),
    api('GET', `/imports/${importId}/warnings`).catch(() => []),
    api('GET', '/config').catch(() => ({})),
  ]);
  const cfg = _getDisplayCfg(exportCfg);

  // Derive a short heading from the first section filename if available
  const heading = sections._error
    ? importId
    : (sections[0] ? `Import \u2013 ${importId.slice(0, 8)}\u2026` : `Import ${importId.slice(0, 8)}\u2026`);
  document.getElementById('detail-heading').textContent = heading;

  renderWarningsPanel(warnings);

  if (sections._error) {
    document.getElementById('sections-container').innerHTML = `<p class="error">${esc(sections._error)}</p>`;
    return;
  }
  renderSections(importId, sections, cfg);
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
  row.classList.add('row-highlight');
  setTimeout(() => row.classList.remove('row-highlight'), 2000);
}

function renderSections(importId, sections, cfg) {
  const container = document.getElementById('sections-container');
  if (!sections.length) {
    container.innerHTML = '<p class="muted">No sections found.</p>';
    return;
  }
  container.innerHTML = sections.map(section => `
    <details class="section-block" open>
      <summary class="section-summary">
        <span class="section-name">${esc(section.name)}</span>
        <span class="section-meta">${section.works.length} work${section.works.length !== 1 ? 's' : ''}</span>
        <button type="button" class="btn btn-xs btn-secondary section-export-btn"
          onclick="event.preventDefault();downloadExport('${esc(importId)}','tags','txt','${esc(section.id)}')">
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
          <th class="col-status">Include</th>
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
  const honorifics = w.artist_honorifics
    ? ` <span class="honorifics-pill">${esc(w.artist_honorifics)}</span>`
    : '';
  const priceDisplay = formatPrice(w.price_numeric, w.price_text, cfg);

  // Edition: mimic the export renderer format
  const prefix = cfg?.edition_prefix ?? 'edition of';
  const brackets = cfg?.edition_brackets !== false;
  let editionDisplay = '';
  if (w.edition_total && w.edition_price_numeric) {
    const inner = `${prefix} ${w.edition_total} at ${formatPrice(w.edition_price_numeric, null, cfg)}`;
    editionDisplay = brackets ? `(${inner})` : inner;
  } else if (w.edition_total) {
    const inner = `${prefix} ${w.edition_total}`;
    editionDisplay = brackets ? `(${inner})` : inner;
  }

  return `
    <tr id="wr-${esc(w.id)}" class="work-row ${included ? '' : 'row-excluded'}">
      <td class="col-no">${esc(w.raw_cat_no ?? '')}</td>
      <td>${esc(w.artist_name ?? '')}${honorifics}</td>
      <td>${esc(w.title ?? '')}</td>
      <td>${esc(priceDisplay)}</td>
      <td>${esc(editionDisplay)}</td>
      <td>${w.artwork != null ? esc(String(w.artwork)) : ''}</td>
      <td class="col-medium">${esc(w.medium ?? '')}</td>
      <td class="col-status">
        <button id="excl-${esc(w.id)}" class="btn btn-xs ${included ? 'btn-warning' : 'btn-success'}"
          onclick="toggleExclude('${esc(importId)}','${esc(w.id)}',${included})">
          ${included ? 'Exclude' : 'Include'}
        </button>
      </td>
      <td class="col-actions">
        <button id="ov-btn-${esc(w.id)}" class="btn btn-xs btn-secondary"
          onclick="toggleOverrideForm('${esc(importId)}','${esc(w.id)}')">Edit</button>
      </td>
    </tr>
    <tr id="ovr-${esc(w.id)}" class="override-form-row" style="display:none">
      <td colspan="9" id="ovc-${esc(w.id)}"></td>
    </tr>`;
}

// ---------------------------------------------------------------------------
// Exclude / include
// ---------------------------------------------------------------------------

async function toggleExclude(importId, workId, currentlyIncluded) {
  const btn = document.getElementById(`excl-${workId}`);
  if (!btn) return;
  btn.disabled = true;
  try {
    const nowExcluding = currentlyIncluded; // we want to flip
    await api('PATCH', `/imports/${importId}/works/${workId}/exclude?exclude=${nowExcluding}`);
    const nowIncluded = !nowExcluding;
    document.getElementById(`wr-${workId}`).className = `work-row ${nowIncluded ? '' : 'row-excluded'}`;
    btn.textContent = nowIncluded ? 'Exclude' : 'Include';
    btn.className = `btn btn-xs ${nowIncluded ? 'btn-warning' : 'btn-success'}`;
    btn.setAttribute('onclick', `toggleExclude('${importId}','${workId}',${nowIncluded})`);
  } catch (err) {
    alert(`Toggle failed: ${err.message}`);
  } finally {
    btn.disabled = false;
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
    btn.textContent = 'Edit';
    _expandedWorkId = null;
    return;
  }

  // Close any other open override form
  if (_expandedWorkId) {
    const prev    = document.getElementById(`ovr-${_expandedWorkId}`);
    const prevBtn = document.getElementById(`ov-btn-${_expandedWorkId}`);
    if (prev)    prev.style.display = 'none';
    if (prevBtn) prevBtn.textContent = 'Edit';
  }

  _expandedWorkId = workId;
  btn.textContent = 'Close';
  formRow.style.display = '';
  document.getElementById(`ovc-${workId}`).innerHTML = '<p class="loading" style="padding:12px">Loading\u2026</p>';

  let existing = null;
  try {
    existing = await api('GET', `/imports/${importId}/works/${workId}/override`);
  } catch (err) {
    if (!err.message.startsWith('404') && !err.message.includes('404')) {
      document.getElementById(`ovc-${workId}`).innerHTML = `<p class="error" style="padding:12px">${esc(err.message)}</p>`;
      return;
    }
    // 404 = no override yet, existing stays null
  }
  showOverrideForm(importId, workId, existing);
}

function showOverrideForm(importId, workId, existing) {
  const val = (f) => esc(existing?.[f] ?? '');
  const cell = document.getElementById(`ovc-${workId}`);
  cell.innerHTML = `
    <div class="override-form">
      <h5>Override Fields <span class="muted" style="text-transform:none;font-weight:400">&ndash; leave blank to use normalised value</span></h5>
      <div class="override-field-form" id="ovf-${esc(workId)}">
        <div class="form-row"><label>Title</label>
          <input type="text" name="title_override" value="${val('title_override')}" placeholder="Override title"></div>
        <div class="form-row"><label>Artist</label>
          <input type="text" name="artist_name_override" value="${val('artist_name_override')}" placeholder="Override artist"></div>
        <div class="form-row"><label>Honorifics</label>
          <input type="text" name="artist_honorifics_override" value="${val('artist_honorifics_override')}" placeholder="e.g. RA"></div>
        <div class="form-row"><label>Price text</label>
          <input type="text" name="price_text_override" value="${val('price_text_override')}" placeholder="e.g. NFS or 1500"></div>
        <div class="form-row"><label>Price numeric</label>
          <input type="number" step="0.01" min="0" name="price_numeric_override" value="${val('price_numeric_override')}" placeholder="e.g. 1500"></div>
        <div class="form-row"><label>Edition total</label>
          <input type="number" min="0" name="edition_total_override" value="${val('edition_total_override')}" placeholder="e.g. 10"></div>
        <div class="form-row"><label>Edition price</label>
          <input type="number" step="0.01" min="0" name="edition_price_numeric_override" value="${val('edition_price_numeric_override')}" placeholder="e.g. 750"></div>
        <div class="form-row"><label>Medium</label>
          <input type="text" name="medium_override" value="${val('medium_override')}" placeholder="Override medium"></div>
        <div class="form-actions">
          <button class="btn btn-primary" onclick="saveOverride('${esc(importId)}','${esc(workId)}')">Save</button>
          ${existing ? `<button class="btn btn-danger" onclick="deleteOverride('${esc(importId)}','${esc(workId)}')">Delete Override</button>` : ''}
          <span id="ovs-${esc(workId)}" class="status-msg"></span>
        </div>
      </div>
    </div>`;
}

async function saveOverride(importId, workId) {
  const formEl = document.getElementById(`ovf-${workId}`);
  const statusEl = document.getElementById(`ovs-${workId}`);
  statusEl.textContent = 'Saving\u2026';
  statusEl.className = 'status-msg';

  const numFields = new Set(['price_numeric_override','edition_total_override','edition_price_numeric_override']);
  const allFields = ['title_override','artist_name_override','artist_honorifics_override',
    'price_text_override','price_numeric_override','edition_total_override','edition_price_numeric_override','medium_override'];

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
    showOverrideForm(importId, workId, result);
    const s = document.getElementById(`ovs-${workId}`);
    if (s) { s.textContent = '\u2713 Saved'; s.className = 'status-msg success'; }
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
    showOverrideForm(importId, workId, null);
    const s = document.getElementById(`ovs-${workId}`);
    if (s) { s.textContent = '\u2713 Override deleted'; s.className = 'status-msg success'; }
  } catch (err) {
    if (statusEl) { statusEl.textContent = `Error: ${err.message}`; statusEl.className = 'status-msg error'; }
  }
}

// ---------------------------------------------------------------------------
// Export download
// ---------------------------------------------------------------------------

async function downloadExport(importId, format, ext, sectionId = null) {
  try {
    const path = sectionId
      ? `/imports/${importId}/sections/${sectionId}/export-${format}`
      : `/imports/${importId}/export-${format}`;
    const res = await fetch(path, { headers: { 'X-API-Key': _apiKey } });
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
    a.download = `catalogue-${importId.slice(0, 8)}-${ts}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(`Export failed: ${err.message}`);
  }
}
