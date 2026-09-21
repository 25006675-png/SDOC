(() => {
  'use strict';

  const state = { cases: [], filtered: [], selectedId: null, view: 'action', search: '', mailbox: null };
  const ACTION_STATES = new Set(['DISCREPANCY', 'NEEDS_REVIEW', 'BLOCKED']);
  const FIELD_ORDER = [
    'shipper', 'consignee', 'notify_party', 'port_of_loading',
    'port_of_discharge', 'container_count', 'gross_weight_kg'
  ];
  const FIELD_LABELS = {
    shipper: 'Shipper', consignee: 'Consignee', notify_party: 'Notify party',
    port_of_loading: 'Port of loading', port_of_discharge: 'Port of discharge',
    container_count: 'Container count', gross_weight_kg: 'Gross weight'
  };
  const $ = id => document.getElementById(id);

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }


  async function loadIdentity() {
    let identity = null;
    try { identity = await (await fetch('/api/auth/status')).json(); } catch (_) { return; }
    if (!identity || !identity.auth_enabled || !identity.username) return;
    state.identity = identity;
    // Workers cannot open analytics; a link they would bounce off is noise.
    if ($('nav-admin')) $('nav-admin').hidden = identity.role !== 'admin';
    const box = document.getElementById('sidebar-user');
    if (!box) return;
    box.hidden = false;
    document.getElementById('user-name').textContent = identity.display_name || identity.username;
    document.getElementById('user-role').textContent =
      identity.role === 'admin' ? 'Administrator' : 'Worker';
    document.getElementById('user-initial').textContent =
      (identity.display_name || identity.username).trim().charAt(0).toUpperCase();
  }

  function stateLabel(value) {
    return value.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
  }

  function categoryLabel(value) {
    return {
      BL_COMPARISON: 'Document comparison',
      SI_REQUEST: 'New SI request',
      INVOICE_QUERY: 'Invoice query',
      GENERAL: 'General operations',
      SPAM: 'Spam'
    }[value] || stateLabel(value);
  }

  function classificationLabel(payload) {
    const status = payload?.classification?.classification_status;
    return status === 'needs_review' ? 'Needs review' : categoryLabel(payload?.classification?.category || payload?.category);
  }

  // One shape per state, so the state never rests on colour alone:
  // dashed ring waits, half-filled ring is with a person, filled disc is final.
  const STATE_ICONS = {
    WAITING: '<circle cx="8" cy="8" r="5.75" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.4 2"/>',
    NEEDS_REVIEW: '<circle cx="8" cy="8" r="5.75" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5a3.5 3.5 0 0 1 0 7Z" fill="currentColor"/>',
    DISCREPANCY: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M8 4.75v3.75" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="10.9" r=".9" fill="#fff"/>',
    BLOCKED: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M5.25 8h5.5" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>',
    VERIFIED: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="m5.4 8.1 1.8 1.8 3.5-3.6" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
  };

  // Visible names only; the backend state names are unchanged. Every state
  // in the action queue needs a person, so the names say what is wrong:
  // a person makes a judgment (Needs review) or fixes a prerequisite (Blocked).
  const STATE_LABELS = { WAITING: 'Waiting for documents', NEEDS_REVIEW: 'Needs review', BLOCKED: 'Blocked' };

  function stateBadge(value) {
    const badge = element('span', `state state-${value.toLowerCase()}`);
    if (STATE_ICONS[value]) {
      badge.insertAdjacentHTML('afterbegin',
        `<svg class="state-icon" viewBox="0 0 16 16" aria-hidden="true">${STATE_ICONS[value]}</svg>`);
    }
    badge.append(element('span', 'state-label', STATE_LABELS[value] || stateLabel(value)));
    return badge;
  }

  function missingDocument(documents) {
    // Which of the SI and draft BL is absent, when the case record says.
    if (!documents?.length) return '';
    const roles = new Set(documents.map(doc => doc.role));
    const missing = [['SI', 'SI'], ['BL', 'Draft BL']].filter(([role]) => !roles.has(role));
    return missing.length === 1 ? missing[0][1] : '';
  }

  function stateReason(caseState, reason, documents) {
    // A state name alone does not say what happened or what to do next,
    // BLOCKED least of all: it covers a rejected file and a wait that ran out.
    if (caseState === 'WAITING') {
      const missing = missingDocument(documents);
      return { text: missing ? `${missing} has not arrived.` : 'The SI or draft BL has not arrived.' };
    }
    if (caseState === 'BLOCKED') {
      return {
        missing_document_timeout: { text: 'Document wait time exceeded', action: 'Ask the sender for the missing document.' },
        unreadable: { text: 'An attachment failed the safety check', action: 'Ask the sender for a readable copy.' }
      }[reason] || { text: 'Processing cannot continue', action: 'Check the documents, then resolve the review.' };
    }
    if (caseState === 'NEEDS_REVIEW') {
      return {
        verifier_disagreement: { text: 'Two reads disagree. A reviewer must confirm this value.' },
        unreadable: { text: 'A document could not be read. A reviewer must check it.' }
      }[reason] || { text: 'A reviewer must confirm this value.' };
    }
    return { text: { DISCREPANCY: 'Fields differ', VERIFIED: 'All fields match' }[caseState] || '' };
  }

  function tag(text) {
    return element('span', 'tag', text);
  }

  function gmailUrl(payload, account) {
    if (!payload) return '';
    const id = payload.gmail_thread_id || payload.thread_id || payload.gmail_message_id;
    if (!id) return payload.message_url || '';
    const user = payload.gmail_account || account || gmailAccount();
    if (user) return `https://mail.google.com/mail/?authuser=${encodeURIComponent(user)}#all/${id}`;
    return `https://mail.google.com/mail/u/0/#all/${id}`;
  }

  function emptyDetail(title, copy) {
    const box = element('div', 'empty-state');
    box.append(
      element('h2', '', title),
      element('p', '', copy)
    );
    $('case-detail').replaceChildren(box);
  }

  function formatTime(value) {
    if (value === null || value === undefined) return 'Time unavailable';
    const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    if (response.status === 401 || response.status === 403) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      throw new Error('Sign in required');
    }
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    return response.json();
  }

  function setConnection(ok, store) {
    $('connection-dot').classList.toggle('is-online', ok);
    $('connection-label').textContent = ok ? 'Backend online' : 'Backend unavailable';
    $('store-label').textContent = ok ? store : 'Retry with refresh';
  }

  function summariseError(text) {
    // Provider errors arrive as full request URLs; a worker needs the gist.
    const raw = String(text);
    const code = raw.match(/\b([45]\d\d)\b/);
    const reason = raw.match(/Bad Request|Unauthorized|Forbidden|Not Found|Too Many Requests|Server Error/);
    if (code) {
      return `Last sync failed (${code[1]}${reason ? ' ' + reason[0] : ''}). An administrator can reconnect the mailbox.`;
    }
    return raw.split(/\r?\n/)[0].slice(0, 140);
  }

  const PROVIDER_NAMES = { gmail: 'Gmail', outlook: 'Outlook' };
  const providerName = key => PROVIDER_NAMES[key] || 'Mailbox';
  const isReady = mailbox => mailbox.configured && mailbox.connected;

  function gmailAccount() {
    return state.mailboxes?.find(item => item.provider === 'gmail')?.account;
  }

  function renderMailbox(items) {
    // Every mailbox that is set up, side by side: SDOC reads them all at once.
    const shown = items.filter(item => item.configured || item.connected);
    const mailboxes = shown.length ? shown : items.slice(0, 1);
    state.mailboxes = items;
    state.mailbox = mailboxes.find(isReady) || mailboxes[0] || null;

    $('mailbox-providers').replaceChildren(...mailboxes.map(item => {
      const chip = element('span', 'mailbox-provider');
      chip.title = `${providerName(item.provider)}: ${isReady(item) ? item.account || 'connected'
        : item.configured ? 'not connected' : 'not set up'}`;
      if (PROVIDER_NAMES[item.provider]) {
        const icon = element('img', 'mailbox-icon');
        icon.src = `/assets/icons/${item.provider}.webp`;
        icon.alt = '';
        chip.append(icon);
      }
      const dot = element('span', 'mailbox-dot');
      dot.classList.toggle('is-online', isReady(item));
      dot.classList.toggle('is-warning', item.configured && !item.connected);
      chip.append(dot);
      return chip;
    }));

    const ready = mailboxes.filter(isReady);
    const down = mailboxes.filter(item => !isReady(item));
    $('mailbox-title').textContent = down.length
      ? `${down.map(item => providerName(item.provider)).join(' and ')} ${down.some(item => item.configured) ? 'not connected' : 'not set up'}`
      : ready.length > 1 ? `${ready.length} mailboxes` : providerName(ready[0]?.provider);
    const failed = mailboxes.find(item => item.last_error);
    const error = failed ? `${providerName(failed.provider)}: ${summariseError(failed.last_error)}` : '';
    // Only a failure earns visible space in the header; routine guidance
    // stays in the tooltip.
    const detail = $('mailbox-detail');
    detail.textContent = error;
    const strip = detail.closest('.mailbox-strip');
    strip?.classList.toggle('has-error', Boolean(error));
    $('mailbox-query').textContent = mailboxes.map(item => item.query ? `${providerName(item.provider)} query: ${item.query}` : '').filter(Boolean).join('. ');
    const lastSync = Math.max(0, ...ready.map(item => item.last_sync_at || 0));
    $('mailbox-sync').textContent = lastSync ? `Synced ${formatTime(lastSync)}` : ready.length ? 'Not synced yet' : '';
    if (strip) {
      strip.title = mailboxes.map(item => [
        `${providerName(item.provider)}: ${isReady(item) ? `connected${item.account ? ` as ${item.account}` : ''}` : item.configured ? 'not connected' : 'not set up'}`,
        item.last_sync_at ? `  Last sync ${formatTime(item.last_sync_at)}, ${item.processed || 0} processed` : '',
        item.last_error ? `  ${item.last_error}` : ''
      ].filter(Boolean).join('\n')).join('\n');
    }
  }

  async function loadMailbox() {
    try {
      renderMailbox((await api('/api/mailboxes')).items);
    } catch (error) {
      renderMailbox([{
        configured: false,
        connected: false,
        query: '',
        processed: 0,
        last_error: error.message,
        next_action: 'Mailbox status unavailable.'
      }]);
    }
  }

  async function syncMailbox() {
    const button = $('mailbox-sync-button');
    button.disabled = true;
    button.textContent = 'Syncing';
    try {
      await api('/api/mailbox/sync', { method: 'POST' });
      await loadMailbox();
      await loadWorkspace({ preserveSelection: true });
    } catch (error) {
      $('mailbox-detail').textContent = error.message;
    } finally {
      button.textContent = 'Sync now';
      if (button) button.disabled = !(state.mailbox?.configured && state.mailbox?.connected);
    }
  }

  function detailIsBusy() {
    if (document.querySelector('.evidence-inspector[open]')) return true;
    // A background refresh replaces the whole detail panel, which would throw
    // away a half-typed correction or review note. Visible, editable, non-empty
    // fields (or the caret being in there) mean someone is mid-task.
    const detail = $('case-detail');
    if (detail.contains(document.activeElement)) return true;
    return Array.from(detail.querySelectorAll('input, textarea')).some(
      field => !field.readOnly && field.offsetParent !== null && field.value.trim() !== '');
  }

  async function countRouted() {
    try {
      return ((await api('/api/routed-messages')).items || []).length;
    } catch (_) {
      return 0;
    }
  }

  async function loadWorkspace({ preserveSelection = true, background = false } = {}) {
    $('refresh-button').classList.add('is-loading');
    try {
      // The queue counts come from the case list, not /api/metrics: that
      // endpoint is admin-only, and a worker must not have a dead dashboard
      // because one tile needs a permission they do not have.
      const [health, cases, routed] = await Promise.all([
        api('/health'), api('/api/cases'), countRouted()
      ]);
      setConnection(true, health.store);
      state.cases = cases.items;
      const byState = state.cases.reduce((counts, item) => {
        counts[item.state] = (counts[item.state] || 0) + 1;
        return counts;
      }, {});
      const actionCount = [...ACTION_STATES]
        .reduce((sum, key) => sum + (byState[key] || 0), 0);
      $('nav-action-count').textContent = actionCount;
      $('nav-all-count').textContent = state.cases.length;
      $('nav-routed-count').textContent = routed;
      if (state.view === 'routed') {
        await loadRoutedView();
        return;
      }
      applyFilters();
      const keepSelection = preserveSelection && state.selectedId
        && state.cases.some(item => item.case_id === state.selectedId);
      if (background && keepSelection && detailIsBusy()) return;
      if (keepSelection) {
        await openCase(state.selectedId, { quiet: background });
      } else if (state.filtered.length) {
        await openCase(state.filtered[0].case_id, { quiet: background });
      }
    } catch (error) {
      setConnection(false, '');
      $('queue-status').textContent = error.message;
      $('case-list').replaceChildren(element('div', 'empty-list', 'Start the SDOC API, then refresh this workspace.'));
    } finally {
      $('refresh-button').classList.remove('is-loading');
    }
  }

  function applyFilters() {
    const filter = $('state-filter').value;
    state.filtered = state.cases.filter(item => {
      const hasExplicitState = !['ACTION', 'ALL'].includes(filter);
      const matchesView = state.view === 'all' || hasExplicitState || ACTION_STATES.has(item.state);
      const matchesState = filter === 'ALL' ||
        (filter === 'ACTION' ? ACTION_STATES.has(item.state) : item.state === filter);
      const needle = state.search.toLowerCase();
      const matchesSearch = !needle || item.shipment_reference.toLowerCase().includes(needle);
      return matchesView && matchesState && matchesSearch;
    });
    // Most urgent first; the sort is stable, so each group keeps the
    // backend's recency order. The first case opened is the first shown.
    state.filtered.sort((a, b) => statePriority(a.state) - statePriority(b.state));
    renderCases();
  }

  const STATE_PRIORITY = ['DISCREPANCY', 'NEEDS_REVIEW', 'BLOCKED', 'WAITING', 'VERIFIED'];
  function statePriority(value) {
    const index = STATE_PRIORITY.indexOf(value);
    return index < 0 ? STATE_PRIORITY.length : index;
  }

  function renderCases() {
    const list = $('case-list');
    const scrollTop = list.scrollTop;
    list.replaceChildren();
    list.classList.remove('is-grouped');
    $('queue-status').textContent = String(state.filtered.length);
    if (!state.filtered.length) {
      list.append(element('div', 'empty-list', state.view === 'action' && !state.search
        ? 'Nothing needs action. New discrepancies and uncertain reads will appear here.'
        : 'No cases match this view. Try another state or search term.'));
      return;
    }
    list.classList.add('is-grouped');
    let group = null;
    state.filtered.forEach(item => {
      if (item.state !== group?.state) {
        const count = state.filtered.filter(other => other.state === item.state).length;
        group = element('div', 'case-group');
        group.state = item.state;
        group.setAttribute('role', 'heading');
        group.setAttribute('aria-level', '2');
        group.append(stateBadge(item.state), element('span', 'case-group-count', String(count)));
        list.append(group);
      }
      const reason = stateReason(item.state, item.state_reason).text;
      list.append(caseRow(item.shipment_reference, formatTime(item.updated_at), stateBadge(item.state), reason,
        item.case_id === state.selectedId, () => openCase(item.case_id), item.source_provider));
    });
    list.scrollTop = scrollTop;
  }

  function providerIcon(provider, className = 'provider-icon') {
    // The mailbox a case arrived through; the name rides along for screen readers.
    if (!PROVIDER_NAMES[provider]) return null;
    const icon = element('img', className);
    icon.src = `/assets/icons/${provider}.webp`;
    icon.alt = PROVIDER_NAMES[provider];
    icon.title = `From ${PROVIDER_NAMES[provider]}`;
    return icon;
  }

  function importedIcon() {
    // Cases loaded from files never passed through a mailbox; say so rather
    // than borrow a provider's logo.
    const icon = element('span', 'provider-icon is-imported');
    icon.title = 'Imported from files';
    icon.setAttribute('role', 'img');
    icon.setAttribute('aria-label', 'Imported from files');
    icon.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v7M5 6.5 8 9.5l3-3M2.5 9.5v4h11v-4"/></svg>';
    return icon;
  }

  function emailSource(payload) {
    // -> { provider, url } for opening the original message, or null.
    const url = gmailUrl(payload, gmailAccount());
    if (!url) return null;
    const provider = payload.gmail_message_id || payload.gmail_thread_id ? 'gmail'
      : payload.outlook_message_id ? 'outlook' : payload.provider;
    return { provider, url };
  }

  function openEmailLink(source, className) {
    const anchor = element('a', className);
    anchor.href = source.url;
    anchor.target = '_blank';
    anchor.rel = 'noreferrer';
    const icon = providerIcon(source.provider, 'provider-icon');
    if (icon) { icon.alt = ''; icon.removeAttribute('title'); anchor.append(icon); }
    anchor.append(document.createTextNode(`Open in ${PROVIDER_NAMES[source.provider] || 'mailbox'}`));
    anchor.insertAdjacentHTML('beforeend',
      '<svg class="external-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 3.5h-3v9h9v-3M9.5 2.5h4v4M13.5 2.5 7.5 8.5"/></svg>');
    anchor.setAttribute('aria-label', `Open the original email in ${PROVIDER_NAMES[source.provider] || 'the mailbox'} (new tab)`);
    return anchor;
  }

  function caseRow(title, time, badge, meta, selected, onClick, provider) {
    // Two lines, like a mail list: what it is and when, then its state and why.
    const button = element('button', 'case-item');
    button.type = 'button';
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', String(selected));
    const top = element('div', 'case-item-top');
    const when = element('span', 'case-item-when');
    when.append(providerIcon(provider) || importedIcon());
    when.append(element('time', '', time));
    top.append(element('strong', '', title), when);
    const bottom = element('div', 'case-item-bottom');
    bottom.append(badge, element('span', 'case-item-meta', meta));
    button.append(top, bottom);
    button.addEventListener('click', onClick);
    return button;
  }

  function actionCopy(caseState) {
    return {
      DISCREPANCY: 'Verified values differ across the SI and draft BL.',
      NEEDS_REVIEW: 'A reading or source value needs confirmation.',
      BLOCKED: 'A required document remains unresolved.',
      WAITING: 'Waiting for the required document set.',
      VERIFIED: 'All required fields passed verification.'
    }[caseState] || 'Shipment document case';
  }

  function canPrepareExternalMessage(caseState) {
    return ['VERIFIED', 'DISCREPANCY', 'WAITING', 'BLOCKED'].includes(caseState);
  }

  function documentRoleLabel(role) {
    return role === 'BL' ? 'Draft BL' : role;
  }

  function displayDocumentName(doc) {
    const raw = doc.source_path || doc.filename || 'Document';
    const filename = raw.split('/').pop().split('\\').pop();
    const extension = filename.includes('.') ? `.${filename.split('.').pop()}` : '';
    const stem = extension ? filename.slice(0, -extension.length) : filename;
    const stripped = stem
      .replace(/^email_\d+_/i, '')
      .replace(/^demo_\d+_/i, '')
      .replace(/^GMAIL-STD-\d+_/i, '')
      .replace(/^[A-Z]+-\w+-\d+_/i, '');
    if (/^(draft[_\s-]*)?bl$/i.test(stripped)) return `Draft BL${extension}`;
    if (/^si$/i.test(stripped)) return `SI${extension}`;
    return `${stripped.replaceAll('_', ' ')}${extension}`;
  }


  // Brand icons live with the public landing assets so both surfaces share them.
  const FILE_ICONS = {
    pdf: '/assets/icons/pdf.png',
    doc: '/assets/icons/word.png', docx: '/assets/icons/word.png',
    xls: '/assets/icons/excel.webp', xlsx: '/assets/icons/excel.webp', csv: '/assets/icons/excel.webp'
  };

  function fileIcon(name) {
    const src = FILE_ICONS[String(name || '').split('.').pop().toLowerCase()];
    if (!src) return null;
    const img = element('img', 'file-icon');
    img.src = src;
    img.alt = '';
    return img;
  }

  function withFileIcon(tag, className, name) {
    const node = element(tag, className);
    const icon = fileIcon(name);
    if (icon) node.append(icon);
    node.append(name);
    return node;
  }

  function attachmentUrl(kind, path) {
    return `/api/attachments/${kind}?path=${encodeURIComponent(path)}`;
  }

  function attachmentRole(path, evidence = {}) {
    if (path === evidence.si_doc) return 'SI';
    if (path === evidence.bl_doc) return 'Draft BL';
    const role = evidence.doc_kinds?.[path];
    if (role) return documentRoleLabel(role);
    const name = path.split('/').pop().toUpperCase();
    if (name.includes('_SI')) return 'SI';
    if (name.includes('_BL')) return 'Draft BL';
    return 'Attachment';
  }

  function fieldLabel(field) {
    return FIELD_LABELS[field] || stateLabel(field);
  }

  function sourceLocation(source) {
    // Only what the reader actually recorded: a PDF row knows its page, a
    // docx row knows its table, and neither should be stated as the other.
    if (!source) return '';
    if (source.page && source.line) return `Page ${source.page}, line ${source.line}`;
    if (source.page) return `Page ${source.page}`;
    if (source.line) return `Line ${source.line}`;
    if (source.table && source.row) return `Table ${source.table}, row ${source.row}`;
    if (source.sheet && source.row) return `Sheet ${source.sheet}, row ${source.row}`;
    if (source.row) return `Row ${source.row}`;
    return '';
  }

  function ensurePreviewSheet() {
    let sheet = document.getElementById('doc-preview');
    if (sheet) return sheet;
    sheet = element('dialog', 'doc-preview');
    sheet.id = 'doc-preview';
    sheet.setAttribute('aria-labelledby', 'doc-preview-title');
    const head = element('header', 'doc-preview-head');
    const title = element('h2', 'doc-preview-title');
    title.id = 'doc-preview-title';
    const actions = element('div', 'doc-preview-actions');
    const download = element('a', 'btn btn-secondary btn-sm doc-preview-download', 'Download');
    download.setAttribute('download', '');
    const close = element('button', 'btn btn-ghost btn-sm btn-icon', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close preview');
    close.addEventListener('click', () => sheet.close());
    actions.append(download, close);
    head.append(title, actions);
    sheet.append(head, element('div', 'doc-preview-body'));
    // A click on the backdrop lands on the dialog element itself.
    sheet.addEventListener('click', event => { if (event.target === sheet) sheet.close(); });
    document.body.append(sheet);
    return sheet;
  }

  async function previewDocument(path) {
    const sheet = ensurePreviewSheet();
    const name = displayDocumentName({ source_path: path });
    sheet.querySelector('.doc-preview-title').textContent = name;
    sheet.querySelector('.doc-preview-download').href = attachmentUrl('download', path);
    const body = sheet.querySelector('.doc-preview-body');
    if (/\.pdf$/i.test(path)) {
      body.replaceChildren(documentVisual({ document: path, page: 1 }, 'page', name));
    } else if (/\.(txt|text|csv|md)$/i.test(path)) {
      body.replaceChildren(element('p', 'doc-empty', 'Loading…'));
      try {
        const response = await fetch(attachmentUrl('preview', path));
        if (!response.ok) throw new Error(`Preview failed (${response.status})`);
        body.replaceChildren(element('pre', 'doc-text', (await response.text()).slice(0, 20000)));
      } catch (error) {
        body.replaceChildren(element('p', 'doc-empty', error.message));
      }
    } else {
      body.replaceChildren(element('p', 'doc-empty', 'This file type cannot be previewed here. Download it to open.'));
    }
    if (!sheet.open) sheet.showModal();
  }

  function renderAttachmentList(paths, evidence = {}) {
    const box = element('div', 'email-attachments');
    box.append(element('h4', '', 'Attachments'));
    const list = element('div', 'attachment-list');
    paths.forEach(path => {
      const row = element('div', 'attachment-row');
      const label = element('div', 'attachment-name');
      label.append(
        withFileIcon('strong', '', displayDocumentName({ source_path: path })),
        element('span', '', attachmentRole(path, evidence))
      );
      const actions = element('div', 'attachment-actions');
      const preview = element('button', 'btn btn-ghost btn-sm', 'Preview');
      preview.type = 'button';
      preview.addEventListener('click', () => previewDocument(path));
      const download = element('a', 'btn btn-ghost btn-sm', 'Download');
      download.href = attachmentUrl('download', path);
      download.setAttribute('download', '');
      actions.append(preview, download);
      row.append(label, actions);
      list.append(row);
    });
    box.append(list);
    return box;
  }

  let caseRequest = 0;
  async function openCase(caseId, { quiet = false } = {}) {
    const request = ++caseRequest;
    const changedCase = state.selectedId !== caseId;
    const sameCase = quiet && state.selectedId === caseId;
    // A background refresh keeps the tab the reviewer is on; a new case
    // opens on the review.
    if (state.selectedId !== caseId) state.tab = 'review';
    state.selectedId = caseId;
    renderCases();
    const detail = $('case-detail');
    const scrollTop = detail.scrollTop;
    const previousStatus = detail.querySelector('.detail-heading .state')?.textContent;
    if (!sameCase) detail.replaceChildren($('loading-template').content.cloneNode(true));
    try {
      const data = await api(`/api/cases/${encodeURIComponent(caseId)}`);
      if (request !== caseRequest || state.view === 'routed') return;
      renderDetail(data);
      detail.scrollTop = changedCase ? 0 : scrollTop;
      if (!prefersReducedMotion()) {
        if (changedCase) detail.animate([{ opacity: .65, transform: 'translateY(5px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'ease-out' });
        const badge = detail.querySelector('.detail-heading .state');
        if (badge && previousStatus && badge.textContent !== previousStatus && !changedCase) {
          badge.animate([{ outline: '3px solid #e8892a' }, { outline: '3px solid transparent' }], { duration: 650 });
        }
      }
    } catch (error) {
      if (request !== caseRequest || state.view === 'routed') return;
      const box = element('div', 'error-state');
      box.append(element('h2', '', 'Could not load this case'), element('p', '', error.message));
      detail.replaceChildren(box);
    }
  }

  function prefersReducedMotion() {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  }

  let feedbackTimer;
  function showFeedback(text) {
    let notice = $('workspace-feedback');
    if (!notice) {
      notice = element('div', 'workspace-feedback'); notice.id = 'workspace-feedback';
      notice.setAttribute('role', 'status'); document.body.append(notice);
    }
    clearTimeout(feedbackTimer); notice.hidden = false; notice.textContent = text;
    feedbackTimer = setTimeout(() => { notice.hidden = true; }, 6000);
  }

  function nextAction(data) {
    const openTask = data.review_tasks?.find(task => task.status === 'OPEN');
    if (openTask) return { label: 'Resolve review', target: '.review-box' };
    if (canPrepareExternalMessage(data.state)) {
      return { label: data.state === 'VERIFIED' ? 'Prepare confirmation' : 'Prepare message', target: '.draft-box' };
    }
    return null;
  }

  function sideName(side) {
    return side === 'si' ? 'shipping instruction' : 'draft BL';
  }

  function listFields(fields) {
    const names = fields.map(fieldLabel);
    if (names.length < 3) return names.join(' and ');
    return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
  }

  const GATE_TITLES = {
    attachment_encrypted: name => `${name} is password-protected`,
    attachment_type_mismatch: name => `${name} is not the file type its name claims`,
    attachment_too_large: name => `${name} is larger than SDOC accepts`,
    attachment_too_many_pages: name => `${name} has too many pages to process`,
    attachment_malformed: name => `${name} is damaged or empty`,
    attachment_expansion_limit: name => `${name} expands to an unsafe size`,
    too_many_attachments: () => 'The email has too many attachments to process'
  };

  function guidance(data, comparison, openTask) {
    // Answers the reviewer's first question: what is wrong here, and what am
    // I expected to do about it. Built from the same evidence as the table.
    const fields = comparison?.evidence?.fields || {};
    const order = comparedFields(fields);
    const differing = order.filter(field => fields[field]?.match === false);
    const pending = order.filter(field => fields[field]?.match == null && fields[field]);
    if (data.state === 'DISCREPANCY' || differing.length) {
      const n = differing.length;
      return {
        tone: 'diff',
        title: n ? `${listFields(differing)} ${n === 1 ? 'differs' : 'differ'} between the SI and draft BL`
          : 'The SI and draft BL disagree',
        body: 'Check the highlighted evidence for each document. If SDOC misread a value, correct it and the case is compared again. If the documents really disagree, prepare a message asking for an amended draft BL.'
      };
    }
    // Stopped by the preflight gate: nothing was read, so say which file and why
    // rather than the missing-document timeout text below.
    const gate = comparison?.evidence?.preflight;
    if (data.state === 'BLOCKED' && gate && !gate.ok) {
      const path = gate.rejected?.[0]?.document;
      const file = path ? displayDocumentName({ source_path: path }) : 'An attachment';
      return {
        tone: 'diff',
        title: (GATE_TITLES[gate.reason] || (name => `${name} was stopped by the safety check`))(file),
        body: 'SDOC did not open this file or send it to a model. Ask the sender for a readable copy; the case is compared again when it arrives.'
      };
    }
    if (pending.length) {
      const first = fields[pending[0]];
      const missing = SIDES.map(([side]) => side).filter(side => first[side] == null);
      const where = missing.length === 1 ? ` on the ${sideName(missing[0])}` : '';
      return {
        tone: 'review',
        title: pending.length === 1 ? `${fieldLabel(pending[0])} could not be confirmed${where}`
          : `${listFields(pending)} could not be confirmed`,
        body: 'Look at the source document below. If the value is printed there, correct it so SDOC can compare again. If it is genuinely missing, resolve the review and record what you decided.'
      };
    }
    if (openTask && data.state !== 'BLOCKED') {
      return {
        tone: 'review',
        title: `${stateLabel(openTask.reason || openTask.kind)} needs a decision`,
        body: 'Check the email and documents, then resolve the review and record what you decided.'
      };
    }
    return {
      WAITING: { tone: 'neutral', title: 'Waiting for the full document set', body: 'SDOC compares the fields when both the SI and the draft BL have arrived. Nothing to do yet.' },
      BLOCKED: { tone: 'diff', title: 'Document wait time exceeded', body: 'A required document did not arrive in time. Ask the sender for the missing document; the case is compared again when it arrives.' },
      VERIFIED: { tone: 'ok', title: 'All fields match', body: 'No action needed. Prepare a confirmation only if your process requires a reply.' }
    }[data.state] || null;
  }

  function renderGuidance(info) {
    const box = element('section', `guidance is-${info.tone}`);
    box.setAttribute('aria-label', 'What needs your decision');
    const glyph = element('span', 'guidance-glyph', { diff: '!', review: '?', ok: '✓', neutral: '…' }[info.tone]);
    glyph.setAttribute('aria-hidden', 'true');
    const text = element('div');
    text.append(element('h3', '', info.title), element('p', '', info.body));
    box.append(glyph, text);
    return box;
  }

  function renderTabs(panels) {
    // Review first; supporting context and the audit trail one click away
    // instead of stacked below it.
    const wrap = element('div', 'tabs');
    const list = element('div', 'tab-list');
    list.setAttribute('role', 'tablist');
    const buttons = [];
    const shown = panels.filter(panel => panel.content.length);
    if (!shown.some(panel => panel.id === state.tab)) state.tab = shown[0]?.id;
    const views = shown.map(panel => {
      const view = element('div', 'tab-panel');
      view.id = `tab-${panel.id}`;
      view.setAttribute('role', 'tabpanel');
      view.append(...panel.content);
      const button = element('button', 'tab', panel.label);
      button.type = 'button';
      button.id = `tab-button-${panel.id}`;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', view.id);
      view.setAttribute('aria-labelledby', button.id);
      if (panel.count) button.append(element('span', 'tab-count', String(panel.count)));
      button.addEventListener('click', () => activate(panel.id));
      buttons.push(button);
      list.append(button);
      return view;
    });
    function activate(id, focus) {
      state.tab = id;
      shown.forEach((panel, i) => {
        const on = panel.id === id;
        buttons[i].setAttribute('aria-selected', String(on));
        buttons[i].tabIndex = on ? 0 : -1;
        views[i].hidden = !on;
        if (on && focus) buttons[i].focus();
      });
    }
    list.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      const index = shown.findIndex(panel => panel.id === state.tab);
      const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + shown.length) % shown.length;
      activate(shown[next].id, true);
    });
    activate(state.tab);
    wrap.append(...views);
    wrap.list = list;
    wrap.activate = activate;
    return wrap;
  }

  function renderDetail(data) {
    const detail = $('case-detail');
    const head = element('header', 'detail-head');
    const headRow = element('div', 'detail-head-row');
    const title = element('div', 'detail-title');
    const heading = element('div', 'detail-heading');
    heading.append(element('h2', '', data.shipment_reference), stateBadge(data.state));
    const why = stateReason(data.state, data.state_reason, data.documents);
    if (why.text) heading.append(element('span', 'state-reason', [why.text, why.action].filter(Boolean).join(' · ')));
    const email = data.emails?.[0];
    const meta = email
      ? `${email.sender || 'Unknown sender'} · Received ${formatTime(email.received_at || email.created_at)}`
      : actionCopy(data.state);
    const metaLine = element('p', 'detail-meta', meta);
    // The worker's next step is often a reply, which starts in the mailbox.
    const source = email && emailSource(email.payload_json || {});
    if (source) metaLine.append(openEmailLink(source, 'source-link'));
    title.append(heading, metaLine);
    headRow.append(title);
    head.append(headRow);

    const latest = data.comparisons?.at(-1);
    const openTask = data.review_tasks?.find(task => task.status === 'OPEN');
    const review = [];
    const info = guidance(data, latest, openTask);
    if (info) review.push(renderGuidance(info));
    review.push(renderComparison(latest, data.state, data.case_id));
    if (openTask) review.push(renderReview(openTask, data.case_id, data.state));
    if (!openTask && canPrepareExternalMessage(data.state)) review.push(renderDrafting(data.case_id, data.state));

    const context = [];
    if (data.emails?.length) context.push(renderSourceEmails(data.emails, latest?.evidence));
    if (data.documents?.length) context.push(renderDocuments(data.documents));
    if (latest?.evidence?.classification) context.push(renderClassification(latest.evidence.classification));

    const history = data.audit_events?.length ? [renderTimeline(data.audit_events)] : [];
    const tabs = renderTabs([
      { id: 'review', label: 'Review', content: review },
      { id: 'context', label: 'Email and documents', content: context },
      { id: 'history', label: 'History', content: history, count: data.audit_events?.length }
    ]);

    const next = nextAction(data);
    if (next) {
      const button = element('button', 'btn btn-primary', next.label);
      button.type = 'button';
      button.addEventListener('click', () => {
        tabs.activate('review');
        const target = detail.querySelector(next.target);
        if (!target) return;
        target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
        target.querySelector('input, textarea, select, button')?.focus({ preventScroll: true });
      });
      headRow.append(button);
    }
    head.append(tabs.list);
    const body = element('div', 'detail-body');
    body.append(tabs);
    detail.replaceChildren(head, body);
  }

  function renderClassification(classification) {
    const section = element('section', 'detail-section classification-box');
    section.append(element('h3', '', 'Email screening'));
    const facts = element('dl', 'message-facts');
    [
      ['Category', categoryLabel(classification.category)],
      ['Status', classification.classification_status === 'needs_review' ? 'Needs review' : 'Resolved'],
      ['Decision source', stateLabel(classification.decision_source || classification.decision || 'unknown')],
      ['Reason', classification.reason || 'No reason recorded']
    ].forEach(([label, value]) => {
      const row = element('div');
      row.append(element('dt', '', label), element('dd', '', value));
      facts.append(row);
    });
    section.append(facts);
    return section;
  }

  function renderSourceEmails(emails, evidence = {}) {
    const section = element('section', 'detail-section');
    section.append(element('h3', '', 'Source email'));
    const list = element('div', 'source-email-list');
    emails.forEach(email => {
      const payload = email.payload_json || {};
      const row = element('div', 'source-email-row');
      const content = element('div');
      content.append(
        element('strong', '', email.subject || 'No subject'),
        element('span', '', `${email.sender || 'Unknown sender'} · ${formatTime(email.received_at || email.created_at)}`)
      );
      const source = emailSource(payload);
      if (source) {
        row.append(content, openEmailLink(source, 'secondary-link'));
      } else {
        row.append(content, element('span', 'source-email-id', email.email_id));
      }
      const card = element('div', 'source-email-card');
      card.append(row);
      if ((payload.attachments || []).length) card.append(renderAttachmentList(payload.attachments, evidence));
      list.append(card);
    });
    section.append(list);
    return section;
  }

  function comparedFields(fields) {
    // COMPARE_FIELDS + config extras: keep the known order, then anything a
    // deployment added, so a discrepancy can never be invisible here.
    return FIELD_ORDER.concat(Object.keys(fields).filter(f => !FIELD_ORDER.includes(f)));
  }

  function matchNote(evidence) {
    // 'Match' on two visibly different values needs a reason, or it reads as
    // a bug: the backend matched within tolerance or above the fuzzy cutoff.
    if (evidence.match !== true) return '';
    if (evidence.within_tolerance) return 'Within tolerance';
    if (evidence.si_norm !== evidence.bl_norm) {
      const sim = typeof evidence.sim === 'number' ? ` · ${Math.round(evidence.sim * 100)}% similar` : '';
      return `Near match${sim}`;
    }
    return '';
  }

  function correctionForm(caseId, field, evidence) {
    const form = element('form', 'correction-form');
    const side = document.createElement('select');
    side.setAttribute('aria-label', 'Document to correct');
    SIDES.forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = label;
      side.append(option);
    });
    // Start on the side most likely to be wrong: the one that differs from
    // the other, or whichever value is missing.
    if (evidence.si != null && evidence.bl == null) side.value = 'bl';
    const value = element('input');
    value.required = true;
    value.setAttribute('aria-label', 'Corrected value');
    value.placeholder = 'Value exactly as printed';
    value.value = (side.value === 'si' ? evidence.si : evidence.bl) ?? '';
    side.addEventListener('change', () => { value.value = (side.value === 'si' ? evidence.si : evidence.bl) ?? ''; });
    const actor = element('input');
    actor.required = true;
    actor.setAttribute('aria-label', 'Corrected by');
    actor.placeholder = 'Your name';
    actor.value = state.identity?.display_name || state.identity?.username || '';
    if (actor.value) actor.type = 'hidden';
    const note = element('input');
    note.setAttribute('aria-label', 'Reason for correction');
    note.placeholder = 'Reason (optional)';
    const submit = element('button', 'btn btn-primary btn-sm', 'Save and re-compare');
    submit.type = 'submit';
    const message = element('p', 'inline-message', '');
    message.setAttribute('role', 'status');
    form.append(side, value, actor, note, submit, message);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      submit.disabled = true; submit.textContent = 'Saving…';
      try {
        await api(`/api/cases/${caseId}/correct`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            field, side: side.value, value: value.value,
            actor: actor.value, note: note.value || null
          })
        });
        await loadWorkspace({ preserveSelection: true });
        showFeedback('Correction saved. The documents have been compared again.');
      } catch (error) {
        message.textContent = error.message;
        submit.disabled = false; submit.textContent = 'Save and re-compare';
      }
    });
    return form;
  }

  const SIDES = [['si', 'Shipping instruction'], ['bl', 'Draft bill of lading']];

  function fieldStatus(evidence) {
    if (evidence.match === true) return { word: 'Match', glyph: '✓', tone: 'match' };
    if (evidence.match === false) return { word: 'Different', glyph: '!', tone: 'diff' };
    return { word: 'Needs review', glyph: '?', tone: 'review' };
  }

  function statusChip(evidence) {
    // Glyph plus word: the state never rests on colour alone.
    const status = fieldStatus(evidence);
    const chip = element('span', `field-status is-${status.tone}`);
    const glyph = element('span', 'field-status-glyph', status.glyph);
    glyph.setAttribute('aria-hidden', 'true');
    chip.append(glyph, document.createTextNode(status.word));
    return chip;
  }

  function pct(value) { return `${(value * 100).toFixed(3)}%`; }

  function pageImageUrl(path, page) {
    return `/api/attachments/page?${new URLSearchParams({ path, page: String(page || 1), scale: '3' })}`;
  }

  function cropRegion(box, width, height) {
    // Tight enough that the value is the largest thing in the frame, with a
    // minimum width so a short value is not magnified into a blur.
    const padX = 10, padY = 12, minWidth = Math.min(width, 200);
    let x0 = box[0] - padX, x1 = box[2] + padX;
    if (x1 - x0 < minWidth) {
      const centre = (box[0] + box[2]) / 2;
      x0 = centre - minWidth / 2; x1 = centre + minWidth / 2;
    }
    if (x0 < 0) { x1 -= x0; x0 = 0; }
    if (x1 > width) { x0 = Math.max(0, x0 - (x1 - width)); x1 = width; }
    return [x0, Math.max(0, box[1] - padY), x1, Math.min(height, box[3] + padY)];
  }

  function padBox(box, width, height, pad = 2.5) {
    return [Math.max(0, box[0] - pad), Math.max(0, box[1] - pad),
            Math.min(width, box[2] + pad), Math.min(height, box[3] + pad)];
  }

  const HIGHLIGHT_RGB = { match: '38, 115, 74', diff: '217, 118, 26', review: '105, 80, 156' };

  function highlightBox(left, top, width, height, status, labelled) {
    // Coloured by the field's comparison result, the same on both documents:
    // a difference does not say which source is wrong.
    const mark = element('span', `doc-highlight is-${status?.tone || 'diff'}`);
    mark.setAttribute('aria-hidden', 'true');
    Object.assign(mark.style, { left: pct(left), top: pct(top), width: pct(width), height: pct(height) });
    if (labelled && status) mark.append(element('span', 'doc-highlight-label', `${status.glyph} ${status.word}`));
    return mark;
  }

  function sourceGeometry(source) {
    const width = Number(source?.page_width), height = Number(source?.page_height);
    const box = Array.isArray(source?.bbox) && source.bbox.length === 4 ? source.bbox.map(Number) : null;
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 ||
        !box || !box.every(Number.isFinite) || box[0] < 0 || box[1] < 0 ||
        box[2] > width || box[3] > height || box[2] <= box[0] || box[3] <= box[1]) return null;
    return { width, height, box };
  }

  function documentVisual(source, mode, label, status) {
    // Positions are PDF points with a top-left origin; expressing them as a
    // share of the rendered region keeps the highlight exact at any width.
    const wrap = element('div', 'doc-visual');
    const path = source?.document;
    if (!path) {
      wrap.append(element('p', 'doc-empty', 'Source location unavailable.'));
      return wrap;
    }
    if (!/\.pdf$/i.test(path)) {
      wrap.append(source.source_text
        ? element('blockquote', 'doc-snippet', source.source_text)
        : element('p', 'doc-empty', 'Page images are available for PDF documents only.'));
      return wrap;
    }
    const geometry = sourceGeometry(source);
    const width = Number(source.page_width), height = Number(source.page_height);
    const box = geometry?.box;
    const placeable = Boolean(geometry);
    const crop = mode === 'field' && placeable;
    const frame = element('div', `doc-frame ${crop ? 'is-crop' : 'is-page'} is-loading`);
    const img = new Image();
    img.decoding = 'async';
    img.alt = `${label}, page ${source.page || 1}`;
    img.addEventListener('load', () => frame.classList.remove('is-loading'));
    img.addEventListener('error', () => {
      frame.className = 'doc-frame';
      frame.style.aspectRatio = '';
      frame.replaceChildren(element('p', 'doc-empty', 'This page could not be rendered.'));
    });
    const mark = placeable ? padBox(box, width, height) : null;
    if (mode === 'inspect' && placeable) {
      frame.classList.add('inspection-stage');
      const plane = element('div', 'inspection-page');
      plane.style.aspectRatio = `${width} / ${height}`;
      plane.geometry = { width, height, box: mark };
      plane.append(img, highlightBox(mark[0] / width, mark[1] / height,
        (mark[2] - mark[0]) / width, (mark[3] - mark[1]) / height, status, true));
      frame.append(plane);
    } else if (crop) {
      const [x0, y0, x1, y1] = cropRegion(mark, width, height);
      const rw = x1 - x0, rh = y1 - y0;
      frame.style.aspectRatio = `${rw} / ${rh}`;
      Object.assign(img.style, { width: pct(width / rw), left: pct(-x0 / rw), top: pct(-y0 / rh) });
      // Too tight a frame for a label; the result chip sits just above it.
      frame.append(img, highlightBox((mark[0] - x0) / rw, (mark[1] - y0) / rh,
        (mark[2] - mark[0]) / rw, (mark[3] - mark[1]) / rh, status, false));
    } else {
      if (width > 0 && height > 0) frame.style.aspectRatio = `${width} / ${height}`;
      frame.append(img);
      if (mark) {
        frame.append(highlightBox(mark[0] / width, mark[1] / height,
          (mark[2] - mark[0]) / width, (mark[3] - mark[1]) / height, status, true));
      }
    }
    img.src = pageImageUrl(path, source.page);
    wrap.append(frame);
    if (status && !placeable) wrap.append(element('p', 'doc-empty', 'Source location unavailable. Showing the recorded page.'));
    return wrap;
  }

  function inspectEvidence(context, trigger) {
    const dialog = element('dialog', 'evidence-inspector');
    dialog.setAttribute('aria-labelledby', 'inspector-title');
    const header = element('header', 'inspector-header');
    const heading = element('div');
    const title = element('h2', '', 'Inspect evidence'); title.id = 'inspector-title';
    heading.append(title, element('p', '', 'Recorded source locations in the original documents.'));
    const close = element('button', 'btn btn-secondary', 'Close'); close.type = 'button';
    close.addEventListener('click', () => dialog.close()); header.append(heading, close);
    const pane = element('div', 'evidence-pane');
    const footer = element('footer', 'inspector-footer');
    const message = element('p', '', 'Loading source pages...'); message.setAttribute('role', 'status');
    const replay = element('button', 'btn btn-secondary', 'Replay evidence'); replay.type = 'button';
    footer.append(message, replay);

    // Every compared field, in the dashboard's order, so a match and a
    // difference can be shown one after the other without closing.
    const fields = context.fields || { [context.field]: context.evidence };
    const order = context.order || [context.field];
    const nav = element('nav', 'inspector-fields');
    nav.setAttribute('aria-label', 'Compared fields. Use the arrow keys to move between fields.');
    const picker = element('select', 'inspector-field-select');
    picker.setAttribute('aria-label', 'Field');
    const items = order.map(field => {
      const evidence = fields[field] || {};
      const item = element('button', 'inspector-field'); item.type = 'button';
      item.dataset.field = field;
      const result = element('span', 'field-result');
      result.append(statusChip(evidence));
      const note = matchNote(evidence);
      if (note) result.append(element('span', 'match-note', note));
      item.append(element('span', 'inspector-field-name', fieldLabel(field)), result);
      item.addEventListener('click', () => show(field));
      nav.append(item);
      const option = element('option', '', `${fieldLabel(field)} · ${fieldStatus(evidence).word}`);
      option.value = field; picker.append(option);
      return item;
    });
    picker.addEventListener('change', () => show(picker.value));
    arrowNavigation(nav, items, item => show(item.dataset.field));
    const main = element('div', 'inspector-main');
    main.append(picker, pane);
    const body = element('div', 'inspector-body');
    body.append(nav, main);
    dialog.append(header, body, footer);
    let generation = 0;
    let animations = [];
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    const cancel = () => {
      generation++; animations.forEach(animation => animation.cancel()); animations = [];
      pane.querySelectorAll('.evidence-value, .evidence-pane-title .field-status, .doc-highlight-label').forEach(value => value.style.removeProperty('opacity'));
    };
    const inspection = { ...context, mode: 'field', inspect: true, play };

    function mark(field) {
      items.forEach(item => item.setAttribute('aria-current', String(item.dataset.field === field)));
      picker.value = field;
    }

    function show(field) {
      // The chosen Field / Full page mode carries over to the next field.
      if (field === inspection.field) return;
      inspection.field = field;
      inspection.evidence = fields[field] || {};
      mark(field);
      renderEvidencePane(pane, inspection);
    }

    function transforms(plane) {
      const { width, height, box } = plane.geometry;
      const stage = plane.parentElement;
      const fit = Math.min(stage.clientWidth / width, stage.clientHeight / height);
      const pageWidth = width * fit, pageHeight = height * fit;
      plane.style.width = `${pageWidth}px`;
      const [x0, y0, x1, y1] = cropRegion(box, width, height);
      const zoom = Math.max(1, Math.min(4.5, stage.clientWidth * .88 / ((x1 - x0) * fit), stage.clientHeight * .7 / ((y1 - y0) * fit)));
      const full = `translate(${(stage.clientWidth - pageWidth) / 2}px, ${(stage.clientHeight - pageHeight) / 2}px) scale(1)`;
      const focused = `translate(${stage.clientWidth / 2 - (x0 + x1) / 2 * fit * zoom}px, ${stage.clientHeight / 2 - (y0 + y1) / 2 * fit * zoom}px) scale(${zoom})`;
      plane.style.transform = focused;
      plane.style.setProperty('--zoom', zoom);
      return { full, focused };
    }

    async function play() {
      cancel();
      const current = generation;
      replay.disabled = true;
      const images = [...pane.querySelectorAll('img')];
      const values = [...pane.querySelectorAll('.evidence-value, .evidence-pane-title .field-status, .doc-highlight-label')];
      if (!motion.matches && inspection.mode === 'field' && pane.querySelectorAll('.inspection-page').length === 2) {
        values.forEach(value => { value.style.opacity = '0'; });
      }
      message.textContent = 'Loading source pages...';
      await Promise.all(images.map(img => img.decode().catch(() => {})));
      if (current !== generation || !dialog.open) return;
      replay.disabled = false;
      values.forEach(value => value.style.removeProperty('opacity'));
      if (inspection.mode === 'page') { message.textContent = 'Full pages. Select Field to focus the recorded locations.'; return; }
      const planes = [...pane.querySelectorAll('.inspection-page')];
      const positions = planes.map(transforms);
      if (planes.length !== 2 || images.some(img => !img.naturalWidth)) {
        message.textContent = 'Some source evidence is unavailable. Only recorded locations are highlighted.';
        return;
      }
      message.textContent = motion.matches ? 'Recorded source locations.' : 'Locating the field in both documents...';
      if (motion.matches) return;
      const start = document.timeline.currentTime;
      const animate = (node, frames, options) => {
        const animation = node.animate(frames, options); animation.startTime = start; animations.push(animation);
        return animation;
      };
      planes.forEach((plane, index) => {
        const { full, focused } = positions[index];
        animate(plane, [{ transform: full }, { transform: focused }], { duration: 650, delay: 650, fill: 'backwards', easing: 'cubic-bezier(.22, 1, .36, 1)' });
        const mark = plane.querySelector('.doc-highlight');
        animate(mark, [{ opacity: 0, clipPath: 'inset(0 100% 0 0)' }, { opacity: 1, clipPath: 'inset(0 0 0 0)' }], { duration: 300, delay: 250, fill: 'backwards', easing: 'ease-out' });
        const rgb = HIGHLIGHT_RGB[fieldStatus(inspection.evidence || {}).tone];
        animate(mark, [{ backgroundColor: `rgba(${rgb}, .3)` }, { backgroundColor: `rgba(${rgb}, .13)` }], { duration: 400, delay: 1300 });
      });
      values.forEach(value => animate(value, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 1300, fill: 'backwards', easing: 'ease-out' }));
      await Promise.all(animations.map(animation => animation.finished.catch(() => {})));
      if (current === generation && dialog.open) message.textContent = 'Recorded source locations. Compare the values above each document.';
    }

    replay.addEventListener('click', () => { inspection.mode = 'field'; renderEvidencePane(pane, inspection); });
    const settle = () => {
      cancel(); pane.querySelectorAll('.inspection-page').forEach(transforms);
      replay.disabled = false; message.textContent = 'Recorded source locations.';
    };
    motion.addEventListener('change', settle);
    window.addEventListener('resize', settle);
    let lastWidth = 0;
    const resize = new ResizeObserver(entries => {
      const width = entries[0].contentRect.width;
      if (lastWidth && Math.abs(width - lastWidth) > 1) settle();
      lastWidth = width;
    });
    dialog.addEventListener('close', () => {
      cancel(); resize.disconnect(); motion.removeEventListener('change', settle);
      window.removeEventListener('resize', settle);
      dialog.remove();
      // Leave the dashboard on the last field inspected. Selecting it redraws
      // the pane, so focus returns to its new Inspect button or to the row.
      if (context.select && inspection.field !== context.field) context.select(inspection.field);
      const target = trigger.isConnected ? trigger
        : document.querySelector('.evidence-pane-foot .inspect-trigger') || document.querySelector('.field-row[aria-current="true"]');
      target?.focus({ preventScroll: true });
    }, { once: true });
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    document.body.append(dialog); dialog.showModal(); resize.observe(dialog);
    mark(inspection.field);
    renderEvidencePane(pane, inspection);
  }

  function sourceFor(evidence, side, comparisonEvidence) {
    const recorded = evidence[`${side}_source`] || {};
    const fallback = comparisonEvidence[`${side}_doc`];
    return recorded.document || !fallback ? recorded : { ...recorded, document: fallback };
  }

  function renderEvidencePane(pane, context) {
    const { field, evidence, comparisonEvidence, caseId } = context;
    const head = element('header', 'evidence-pane-head');
    const title = element('div', 'evidence-pane-title');
    title.append(element('h3', '', fieldLabel(field)), statusChip(evidence));
    const note = matchNote(evidence);
    if (note) title.append(element('span', 'match-note', note));
    head.append(title);

    const hasPdf = SIDES.some(([side]) => /\.pdf$/i.test(sourceFor(evidence, side, comparisonEvidence).document || ''));
    if (hasPdf) {
      const toggle = element('div', 'segmented');
      toggle.setAttribute('role', 'group');
      toggle.setAttribute('aria-label', 'Evidence view');
      [['field', 'Field'], ['page', 'Full page']].forEach(([mode, label]) => {
        const button = element('button', '', label);
        button.type = 'button';
        button.setAttribute('aria-pressed', String(context.mode === mode));
        button.addEventListener('click', () => {
          if (context.mode === mode) return;
          context.mode = mode;
          renderEvidencePane(pane, context);
          pane.querySelector(`.segmented button[aria-pressed="true"]`)?.focus({ preventScroll: true });
        });
        toggle.append(button);
      });
      head.append(toggle);
    }

    const sides = element('div', 'evidence-sides');
    SIDES.forEach(([side, label]) => {
      const source = sourceFor(evidence, side, comparisonEvidence);
      const block = element('section', 'evidence-side');
      const sideHead = element('div', 'evidence-side-head');
      sideHead.append(element('strong', '', label));
      const where = sourceLocation(source);
      if (where) sideHead.append(element('span', '', where));
      const value = element('p', 'evidence-value', evidence[side] ?? 'Not found in this document');
      if (evidence[side] == null) value.classList.add('is-missing');
      block.append(sideHead);
      if (context.inspect && source.document) {
        const filename = element('p', 'inspection-filename', source.document.split(/[\\/]/).pop());
        filename.title = source.document; block.append(filename);
      }
      block.append(value);
      if (evidence[side] == null && context.mode === 'field' && /\.pdf$/i.test(source.document || '')) {
        // Nothing to crop to. The whole page is the evidence of absence, but
        // it is a page-sized image: offer it rather than push everything down.
        const empty = element('div', 'doc-empty doc-empty-action');
        empty.append(element('span', '', 'SDOC found no value for this field on the page.'));
        const show = element('button', 'btn btn-secondary btn-sm', 'Show full page');
        show.type = 'button';
        show.addEventListener('click', () => { context.mode = 'page'; renderEvidencePane(pane, context); });
        empty.append(show);
        block.append(empty);
      } else {
        const visual = documentVisual(source, context.inspect && context.mode === 'field' ? 'inspect' : context.mode, label, fieldStatus(evidence));
        const crop = visual.querySelector('.is-crop');
        if (crop) {
          const expand = element('button', 'crop-expand'); expand.type = 'button';
          expand.setAttribute('aria-label', `Show full page for ${label}`);
          expand.title = 'Show full page';
          crop.replaceWith(expand); expand.append(crop);
          expand.addEventListener('click', () => {
            context.mode = 'page'; renderEvidencePane(pane, context);
            pane.querySelector('.segmented button[aria-pressed="true"]')?.focus({ preventScroll: true });
          });
        }
        block.append(visual);
      }
      sides.append(block);
    });

    const parts = [head, sides];
    if (context.inspect) { pane.replaceChildren(...parts); context.play(); return; }
    if (evidence.corrected) {
      parts.push(element('p', 'evidence-correction',
        `Corrected from "${evidence.corrected.from || 'blank'}" by ${evidence.corrected.actor || 'a reviewer'}.`));
    }
    const foot = element('footer', 'evidence-pane-foot');
    const correct = element('button', 'btn btn-secondary btn-sm', 'Correct value');
    correct.type = 'button';
    correct.setAttribute('aria-expanded', 'false');
    const form = correctionForm(caseId, field, evidence);
    form.hidden = true;
    correct.addEventListener('click', () => {
      form.hidden = !form.hidden;
      correct.setAttribute('aria-expanded', String(!form.hidden));
      if (!form.hidden) form.querySelector('input')?.focus();
    });
    foot.append(correct);
    if (hasPdf) {
      const inspect = element('button', 'btn btn-secondary btn-sm inspect-trigger', 'Inspect evidence'); inspect.type = 'button';
      inspect.addEventListener('click', () => inspectEvidence(context, inspect)); foot.prepend(inspect);
    }
    parts.push(foot, form);
    pane.replaceChildren(...parts);
  }

  function arrowNavigation(container, items, onMove) {
    container.addEventListener('keydown', event => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const index = items.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? items.length - 1
          : Math.min(items.length - 1, Math.max(0, index + (event.key === 'ArrowDown' ? 1 : -1)));
      items[next].focus();
      onMove(items[next]);
    });
  }

  function renderFieldReview(comparison, caseId) {
    const fields = comparison.evidence.fields;
    const order = comparedFields(fields);
    const section = element('section', 'detail-section review');

    const differing = order.filter(field => fields[field]?.match === false).length;
    const pending = order.filter(field => fields[field]?.match == null).length;
    const heading = element('div', 'review-heading');
    heading.append(
      element('h3', '', 'Field comparison'),
      element('p', differing ? 'review-summary' : pending ? 'review-summary is-review' : 'review-summary is-ok',
        differing ? `${differing} of ${order.length} fields differ`
          : pending ? `${pending} of ${order.length} fields need review`
            : `All ${order.length} fields match`)
    );
    section.append(heading);

    const grid = element('div', 'review-grid');
    const list = element('div', 'field-list');
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', 'Compared fields. Use the arrow keys to move between fields.');
    const listHead = element('div', 'field-list-head');
    listHead.setAttribute('aria-hidden', 'true');
    ['Field', 'Shipping instruction', 'Draft bill of lading', 'Result']
      .forEach(label => listHead.append(element('span', '', label)));
    list.append(listHead);

    const pane = element('aside', 'evidence-pane');
    pane.setAttribute('aria-label', 'Source evidence');
    const context = { mode: 'field', comparisonEvidence: comparison.evidence, caseId };

    const rows = order.map(field => {
      const evidence = fields[field] || {};
      const row = element('button', 'field-row');
      row.type = 'button';
      row.dataset.field = field;
      if (evidence.match === false) row.classList.add('is-diff');
      const si = element('span', 'field-value', evidence.si ?? 'Not found');
      const bl = element('span', 'field-value', evidence.bl ?? 'Not found');
      si.title = evidence.si ?? '';
      bl.title = evidence.bl ?? '';
      if (evidence.si == null) si.classList.add('is-missing');
      if (evidence.bl == null) bl.classList.add('is-missing');
      const result = element('span', 'field-result');
      result.append(statusChip(evidence));
      const note = matchNote(evidence);
      if (note) result.append(element('span', 'match-note', note));
      if (evidence.corrected) result.append(element('span', 'corrected-tag', 'Corrected'));
      row.append(element('span', 'field-name', fieldLabel(field)), si, bl, result);
      row.addEventListener('click', () => select(field));
      // The way into the full comparison, one click from every row; the
      // pane's own button is easy to miss below the documents.
      // The row's colour is its result, the same tone as its chip and its evidence boxes.
      const line = element('div', `field-line is-${fieldStatus(evidence).tone}`);
      const hasPdf = SIDES.some(([side]) => /\.pdf$/i.test(sourceFor(evidence, side, comparison.evidence).document || ''));
      if (hasPdf) {
        const expand = element('button', 'field-expand');
        expand.type = 'button';
        expand.title = 'Inspect evidence';
        expand.setAttribute('aria-label', `Inspect evidence for ${fieldLabel(field)}`);
        expand.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9"/></svg>';
        expand.addEventListener('click', () => { select(field); inspectEvidence(context, expand); });
        line.append(expand);
      } else {
        line.append(element('span', 'field-expand-gap'));
      }
      line.append(row);
      list.append(line);
      return row;
    });

    function select(field) {
      rows.forEach(row => row.setAttribute('aria-current', String(row.dataset.field === field)));
      context.field = field;
      context.evidence = fields[field] || {};
      renderEvidencePane(pane, context);
    }

    arrowNavigation(list, rows, row => select(row.dataset.field));
    Object.assign(context, { fields, order, select });

    grid.append(list, pane);
    section.append(grid);

    const verification = comparison.evidence.verification;
    if (verification) {
      section.append(element('p', 'evidence-note', verification.status === 'AGREED'
        ? 'An independent second read of both documents agreed with this extraction.'
        : `Independent verification: ${stateLabel(verification.status)}.`));
    }

    // Open on the field that needs a decision, so evidence is on screen
    // before anything is clicked.
    const first = order.find(field => fields[field]?.match === false)
      || order.find(field => fields[field]?.match == null) || order[0];
    if (first) select(first);
    return section;
  }

  function renderComparison(comparison, caseState, caseId) {
    if (comparison?.evidence?.fields) return renderFieldReview(comparison, caseId);
    const section = element('section', 'detail-section comparison');
    section.append(element('h3', '', 'Field comparison'));
    if (!comparison?.evidence?.fields) {
      if (caseState === 'VERIFIED') {
        section.append(element('p', 'comparison-summary is-ok', 'All 7 required fields match.'));
        const table = element('table', 'result-only-table');
        const tbody = element('tbody');
        FIELD_ORDER.forEach(field => {
          const row = element('tr');
          row.append(
            element('td', '', fieldLabel(field)),
            element('td', 'result-word', 'Match')
          );
          tbody.append(row);
        });
        table.append(tbody);
        section.append(table);
      } else {
        const copy = {
          WAITING: 'Field comparison will appear once the required SI and draft BL are available.',
          BLOCKED: 'Field comparison is on hold until the document issue is cleared.',
          NEEDS_REVIEW: 'Field evidence is incomplete and needs a reviewer decision.',
          DISCREPANCY: 'Field evidence is not available for this discrepancy record.'
        }[caseState] || 'Field evidence is not available for this case.';
        section.append(element('p', 'evidence-note', copy));
      }
      return section;
    }
  }

  function renderDocuments(documents) {
    const section = element('section', 'detail-section');
    section.append(element('h3', '', 'Document versions'));
    const list = element('div', 'document-list');
    const flattened = documents.flatMap(item => item.document_versions
      ? item.document_versions.map(version => ({ ...version, role: item.role })) : [item]);
    flattened.forEach(doc => {
      const row = element('div', 'document-row');
      row.append(
        element('span', 'document-role', documentRoleLabel(doc.role)),
        withFileIcon('span', 'document-name', displayDocumentName(doc)),
        element('span', 'active-tag', doc.is_active ? `Active · v${doc.version_index}` : `v${doc.version_index}`)
      );
      list.append(row);
    });
    section.append(list);
    return section;
  }

  const VALUE_DECISIONS = [
    ['confirmed', 'Value confirmed from the source document', 'The document supports the value SDOC has on record.'],
    ['accept-bl', 'Accept the draft BL value', 'The SI is incomplete; the BL value is correct for this shipment.'],
    ['request', 'Request a corrected document', 'The sender has to send an amended SI or draft BL.'],
    ['other', 'Other', 'Explain the decision in the note.']
  ];
  // A missing document is a different decision from a misread value.
  const DOCUMENT_DECISIONS = [
    ['requested', 'Missing document requested', 'You asked the sender for the SI or draft BL.'],
    ['received', 'Document received another way', 'It arrived outside the mailbox; note where it is filed.'],
    ['not-shipment', 'Not a shipment case', 'The email does not need a document comparison.'],
    ['other', 'Other', 'Explain the decision in the note.']
  ];

  function renderReview(task, caseId, caseState) {
    const reason = String(task.reason || '');
    const DECISIONS = caseState === 'BLOCKED' || caseState === 'WAITING' || /attachment|timeout|document/i.test(reason)
      ? DOCUMENT_DECISIONS : VALUE_DECISIONS;
    const section = element('section', 'detail-section review-box');
    const head = element('div', 'review-box-head');
    head.append(element('h3', '', 'Resolve review'),
      element('p', '', `${stateLabel(task.kind)} · ${task.reason ? stateLabel(task.reason) : 'Review required'}`));
    section.append(head);
    const form = element('form', 'review-form');

    const choices = element('fieldset', 'decision-list');
    choices.append(element('legend', '', 'Decision'));
    DECISIONS.forEach(([value, label, hint], index) => {
      const option = element('label', 'decision');
      const radio = element('input');
      radio.type = 'radio'; radio.name = 'decision'; radio.value = value; radio.required = true;
      if (index === 0) radio.checked = true;
      const text = element('span', 'decision-text');
      text.append(element('strong', '', label), element('span', '', hint));
      option.append(radio, text);
      choices.append(option);
    });

    const noteLabel = element('label', 'field-label', 'Note');
    const note = element('textarea');
    note.name = 'note'; note.rows = 2;
    note.placeholder = 'Optional. What you checked, or who you contacted.';
    noteLabel.append(note);

    // A signed-in reviewer is already known; only ask when there is no session.
    const signedIn = state.identity?.display_name || state.identity?.username;
    const actor = element('input');
    actor.name = 'actor'; actor.required = true;
    const foot = element('div', 'review-form-foot');
    if (signedIn) {
      actor.type = 'hidden'; actor.value = signedIn;
      foot.append(element('span', 'review-actor', `Recorded as ${signedIn}`));
    } else {
      actor.placeholder = 'Your name or email';
      actor.setAttribute('aria-label', 'Reviewer');
      foot.append(actor);
    }
    const submit = element('button', 'btn btn-primary', 'Resolve review');
    submit.type = 'submit';
    foot.append(submit);
    const message = element('p', 'inline-message is-error', '');
    message.setAttribute('role', 'status');

    choices.addEventListener('change', () => {
      note.required = form.elements.decision.value === 'other';
      note.placeholder = note.required ? 'Required. Describe the decision.' : 'Optional. What you checked, or who you contacted.';
    });
    form.append(choices, noteLabel, actor, foot, message);
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; submit.textContent = 'Resolving…';
      const decision = DECISIONS.find(([value]) => value === form.elements.decision.value);
      const text = note.value.trim();
      const summary = decision[0] === 'other' ? text : text ? `${decision[1]}. ${text}` : decision[1];
      try {
        await api(`/api/review-tasks/${task.task_id}/resolve`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ actor: actor.value, note: summary })
        });
        await loadWorkspace({ preserveSelection: true });
        showFeedback('Review resolved. Your decision has been recorded.');
      } catch (error) {
        message.textContent = error.message; submit.disabled = false; submit.textContent = 'Resolve review';
      }
    });
    section.append(form);
    return section;
  }

  function renderDrafting(caseId, caseState) {
    const section = element('section', 'detail-section draft-box');
    const heading = element('div', 'draft-heading');
    const copy = element('div');
    if (caseState === 'VERIFIED') {
      copy.append(element('h3', '', 'Confirmation'), element('p', '', 'No mismatch detected. Prepare a confirmation only if your workflow requires a reply.'));
    } else {
      copy.append(element('h3', '', 'External message draft'), element('p', '', 'Prepare text for the next manual step. SDOC does not send it.'));
    }
    const button = element('button', 'secondary-button', caseState === 'VERIFIED' ? 'Prepare confirmation' : 'Prepare draft');
    button.type = 'button';
    heading.append(copy, button); section.append(heading);
    button.addEventListener('click', async () => {
      button.disabled = true; button.textContent = 'Preparing…';
      try {
        const draft = await api(`/api/cases/${encodeURIComponent(caseId)}/draft`);
        const form = element('div', 'draft-content');
        const subject = element('input'); subject.value = draft.subject; subject.readOnly = true;
        subject.setAttribute('aria-label', 'Draft subject');
        const body = element('textarea'); body.value = draft.body; body.readOnly = true; body.rows = 9;
        body.setAttribute('aria-label', 'Draft message');
        const copyButton = element('button', 'secondary-button', 'Copy message'); copyButton.type = 'button';
        const note = element('span', 'draft-note', 'Review and edit in your approved mail client.');
        copyButton.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`);
            copyButton.textContent = 'Copied';
          } catch (_) { body.select(); copyButton.textContent = 'Select and copy'; }
        });
        const actions = element('div', 'draft-actions'); actions.append(copyButton, note);
        form.append(subject, body, actions); section.append(form); button.remove();
      } catch (error) {
        button.disabled = false; button.textContent = 'Try again';
        section.append(element('p', 'inline-message', error.message));
      }
    });
    return section;
  }

  function renderTimeline(events) {
    const section = element('section', 'detail-section');
    section.append(element('h3', '', 'Case history'));
    const list = element('div', 'timeline');
    events.slice().reverse().forEach(event => {
      const row = element('div', 'timeline-row');
      const content = element('div');
      content.append(element('strong', '', stateLabel(event.event_type)));
      const detail = event.detail || event.detail_json || {};
      const summary = typeof detail === 'string' ? detail : detail.reason || detail.source_path || detail.email_id || event.actor;
      content.append(element('p', '', summary || event.actor));
      row.append(element('time', '', formatTime(event.created_at)), content);
      list.append(row);
    });
    section.append(list);
    return section;
  }

  async function loadRoutedView() {
    $('queue-title').textContent = 'Routed mail';
    $('queue-description').textContent = 'Classified outside document comparison.';
    $('state-filter').hidden = true;
    $('search-input').disabled = true;
    try {
      const data = await api('/api/routed-messages');
      const items = data.items || [];
      const list = $('case-list'); list.replaceChildren(); list.classList.remove('is-grouped');
      $('queue-status').textContent = String(items.length);
      if (!items.length) {
        list.append(element('div', 'empty-list', 'No mail has been routed outside document comparison.'));
        emptyDetail('No routed mail', 'Unrelated mailbox messages will appear here with sender, subject, category, and source link.');
        return;
      }
      const rows = items.map(item => {
        const row = caseRow(item.subject || 'No subject', formatTime(item.created_at),
          tag(classificationLabel({ category: item.category, ...item.payload_json })),
          item.sender || 'Unknown sender', false, () => {
            rows.forEach(other => {
              other.classList.toggle('is-selected', other === row);
              other.setAttribute('aria-pressed', String(other === row));
            });
            renderRoutedDetail(item);
          }, emailSource(item.payload_json || {})?.provider);
        list.append(row);
        return row;
      });
      rows[0].click();
    } catch (error) {
      $('queue-status').textContent = error.message;
      emptyDetail('Could not load routed mail', error.message);
    }
  }

  function renderRoutedDetail(item) {
    const payload = item.payload_json || {};
    const detail = $('case-detail');
    const head = element('header', 'detail-head');
    const row = element('div', 'detail-head-row');
    const title = element('div', 'detail-title');
    const heading = element('div', 'detail-heading');
    heading.append(element('h2', '', item.subject || 'No subject'),
      tag(classificationLabel({ category: item.category, ...payload })));
    title.append(heading, element('p', '', item.sender || 'Unknown sender'));
    row.append(title);
    head.append(row);
    const body = element('div', 'detail-body');
    const section = element('section', 'detail-section routed-detail');
    section.append(element('h3', '', 'Routed message'));
    const facts = element('dl', 'message-facts');
    [
      ['Category', categoryLabel(item.category)],
      ['Classification status', payload.classification?.classification_status === 'needs_review' ? 'Needs review' : 'Resolved'],
      ['Decision source', stateLabel(payload.classification?.decision_source || 'unknown')],
      ['Reason', payload.classification?.reason || 'No reason recorded'],
      ['Received', formatTime(payload.received_at || item.created_at)],
      ['Email ID', item.email_id],
      ['Attachments', (payload.attachments || []).length ? payload.attachments.join(', ') : 'None']
    ].forEach(([label, value]) => {
      const row = element('div');
      row.append(element('dt', '', label), element('dd', '', value));
      facts.append(row);
    });
    section.append(facts);
    const source = emailSource(payload);
    if (source) section.append(openEmailLink(source, 'primary-link'));
    body.append(section);
    detail.replaceChildren(head, body);
  }

  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
    document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('is-active', item === button));
    state.view = button.dataset.view;
    if (state.view === 'routed') {
      await loadRoutedView();
      return;
    }
    $('state-filter').hidden = false;
    $('search-input').disabled = false;
    $('queue-title').textContent = state.view === 'all' ? 'All cases' : 'Needs action';
    $('queue-description').textContent = state.view === 'all' ? 'Every shipment case.' : 'Cases requiring a person.';
    $('state-filter').value = state.view === 'all' ? 'ALL' : 'ACTION';
    applyFilters();
    // The reader may still show routed mail, or a case this view excludes.
    const target = state.filtered.find(item => item.case_id === state.selectedId) || state.filtered[0];
    if (target) await openCase(target.case_id);
    else emptyDetail('No case selected', 'No cases match this view. Try another state or search term.');
  }));

  $('state-filter').addEventListener('change', applyFilters);
  $('search-input').addEventListener('input', event => {
    state.search = event.target.value.trim();
    if (state.view === 'routed') return;
    applyFilters();
  });
  $('refresh-button').addEventListener('click', () => loadWorkspace());
  if ($('mailbox-connect')) $('mailbox-connect').addEventListener('click', () => { window.location.href = '/api/mailbox/connect'; });
  if ($('mailbox-sync-button')) $('mailbox-sync-button').addEventListener('click', syncMailbox);
  setInterval(async () => {
    await loadMailbox();
    if (state.mailbox?.connected) await loadWorkspace({ preserveSelection: true, background: true });
  }, 30000);
  loadIdentity();
  loadMailbox();
  loadWorkspace({ preserveSelection: false });
})();
