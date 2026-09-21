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

  function stateBadge(value) {
    return element('span', `state state-${value.toLowerCase()}`, stateLabel(value));
  }

  function gmailUrl(payload, account) {
    if (!payload) return '';
    const id = payload.gmail_thread_id || payload.thread_id || payload.gmail_message_id;
    if (!id) return payload.message_url || '';
    const user = payload.gmail_account || account || state.mailbox?.account;
    if (user) return `https://mail.google.com/mail/?authuser=${encodeURIComponent(user)}#all/${id}`;
    return `https://mail.google.com/mail/u/0/#all/${id}`;
  }

  function emptyDetail(title, copy) {
    const box = element('div', 'empty-state');
    box.append(
      element('span', 'empty-symbol', '◇'),
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

  function renderMailbox(mailbox) {
    const providerName = mailbox.provider === 'outlook' ? 'Outlook' : mailbox.provider === 'gmail' ? 'Gmail' : 'Mailbox';
    state.mailbox = mailbox;
    const ready = mailbox.configured && mailbox.connected;
    $('mailbox-dot').classList.toggle('is-online', ready);
    $('mailbox-dot').classList.toggle('is-warning', mailbox.configured && !mailbox.connected);
    $('mailbox-title').textContent = ready
      ? `${providerName} connected${mailbox.account ? `: ${mailbox.account}` : ''}`
      : mailbox.configured ? `${providerName} ready to connect` : `${providerName} needs OAuth settings`;
    const detail = $('mailbox-detail');
    const error = mailbox.last_error ? summariseError(mailbox.last_error) : '';
    detail.textContent = error || mailbox.next_action || '';
    detail.title = mailbox.last_error || '';
    detail.closest('.mailbox-strip')?.classList.toggle('has-error', Boolean(error));
    $('mailbox-query').textContent = mailbox.query ? `Query: ${mailbox.query}` : 'No query active';
    $('mailbox-sync').textContent = mailbox.last_sync_at
      ? `Last sync ${formatTime(mailbox.last_sync_at)}. ${mailbox.processed || 0} processed.`
      : `${mailbox.processed || 0} processed. Not synced yet.`;
    if ($('mailbox-connect')) $('mailbox-connect').disabled = !mailbox.configured;
    if ($('mailbox-sync-button')) $('mailbox-sync-button').disabled = !ready;
  }

  async function loadMailbox() {
    try {
      renderMailbox(await api('/api/mailbox/status'));
    } catch (error) {
      renderMailbox({
        configured: false,
        connected: false,
        query: '',
        processed: 0,
        last_error: error.message,
        next_action: 'Mailbox status unavailable.'
      });
    }
  }

  async function loadRoutedPreview() {
    try {
      const data = await api('/api/routed-messages');
      const items = data.items || [];
      $('routed-preview-count').textContent = items.length;
      const list = $('routed-preview-list');
      list.replaceChildren();
      if (!items.length) {
        list.append(element('p', '', 'No unrelated mail has been routed yet.'));
        return;
      }
      items.slice(0, 5).forEach(item => {
        const row = element('div', 'routed-preview-row');
        const text = element('div');
        text.append(
          element('strong', '', item.subject || 'No subject'),
          element('span', '', item.sender || 'Unknown sender')
        );
        row.append(text, element('span', 'state state-waiting', classificationLabel(item.payload_json || item)));
        list.append(row);
      });
    } catch (error) {
      $('routed-preview-list').replaceChildren(element('p', '', error.message));
    }
  }

  async function syncMailbox() {
    const button = $('mailbox-sync-button');
    button.disabled = true;
    button.textContent = 'Syncing';
    try {
      renderMailbox(await api('/api/mailbox/sync', { method: 'POST' }));
      await loadRoutedPreview();
      await loadWorkspace({ preserveSelection: true });
    } catch (error) {
      $('mailbox-detail').textContent = error.message;
    } finally {
      button.textContent = 'Sync now';
      if (button) button.disabled = !(state.mailbox?.configured && state.mailbox?.connected);
    }
  }

  function detailIsBusy() {
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
      $('metric-action').textContent = actionCount;
      $('metric-verified').textContent = byState.VERIFIED || 0;
      $('metric-waiting').textContent = byState.WAITING || 0;
      $('metric-routed').textContent = routed;
      $('nav-action-count').textContent = actionCount;
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
    renderCases();
  }

  function renderCases() {
    const list = $('case-list');
    list.replaceChildren();
    $('queue-status').textContent = `${state.filtered.length} ${state.filtered.length === 1 ? 'case' : 'cases'}`;
    if (!state.filtered.length) {
      list.append(element('div', 'empty-list', 'No cases match this view. Try another state or search term.'));
      return;
    }
    state.filtered.forEach(item => {
      const button = element('button', 'case-item');
      button.type = 'button';
      button.classList.toggle('is-selected', item.case_id === state.selectedId);
      button.setAttribute('aria-pressed', String(item.case_id === state.selectedId));
      const top = element('div', 'case-item-top');
      top.append(element('strong', '', item.shipment_reference), stateBadge(item.state));
      const reason = item.state_reason ? stateLabel(item.state_reason) : 'Seven-field verification complete';
      const bottom = element('div', 'case-item-bottom');
      bottom.append(element('span', '', reason), element('time', '', formatTime(item.updated_at)));
      button.append(top, element('p', '', actionCopy(item.state)), bottom);
      button.addEventListener('click', () => openCase(item.case_id));
      list.append(button);
    });
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
        element('strong', '', displayDocumentName({ source_path: path })),
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

  async function openCase(caseId, { quiet = false } = {}) {
    const sameCase = quiet && state.selectedId === caseId;
    state.selectedId = caseId;
    renderCases();
    const detail = $('case-detail');
    if (!sameCase) detail.replaceChildren($('loading-template').content.cloneNode(true));
    try {
      renderDetail(await api(`/api/cases/${encodeURIComponent(caseId)}`));
    } catch (error) {
      const box = element('div', 'error-state');
      box.append(element('h2', '', 'Could not load this case'), element('p', '', error.message));
      detail.replaceChildren(box);
    }
  }

  function prefersReducedMotion() {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  }

  function nextAction(data) {
    const openTask = data.review_tasks?.find(task => task.status === 'OPEN');
    if (openTask) return { label: 'Resolve review', target: '.review-box' };
    if (canPrepareExternalMessage(data.state)) {
      return { label: data.state === 'VERIFIED' ? 'Prepare confirmation' : 'Prepare message', target: '.draft-box' };
    }
    return null;
  }

  function renderDetail(data) {
    const detail = $('case-detail');
    const head = element('header', 'detail-head');
    const title = element('div', 'detail-title');
    const heading = element('div', 'detail-heading');
    heading.append(element('h2', '', data.shipment_reference), stateBadge(data.state));
    title.append(heading, element('p', '', actionCopy(data.state)));
    head.append(title);
    const next = nextAction(data);
    if (next) {
      const button = element('button', 'btn btn-primary', next.label);
      button.type = 'button';
      button.addEventListener('click', () => {
        const target = detail.querySelector(next.target);
        if (!target) return;
        target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
        target.querySelector('input, textarea, select, button')?.focus({ preventScroll: true });
      });
      head.append(button);
    }
    const body = element('div', 'detail-body');
    const latest = data.comparisons?.at(-1);
    body.append(renderComparison(latest, data.state, data.case_id));
    if (latest?.evidence?.classification) body.append(renderClassification(latest.evidence.classification));
    if (data.emails?.length) body.append(renderSourceEmails(data.emails, latest?.evidence));
    if (data.documents?.length) body.append(renderDocuments(data.documents));
    const openTask = data.review_tasks?.find(task => task.status === 'OPEN');
    if (openTask) body.append(renderReview(openTask, data.case_id));
    if (!openTask && canPrepareExternalMessage(data.state)) body.append(renderDrafting(data.case_id, data.state));
    if (data.audit_events?.length) body.append(renderTimeline(data.audit_events));
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
      const link = gmailUrl(payload, state.mailbox?.account);
      if (link) {
        const anchor = element('a', 'secondary-link', 'Open email');
        anchor.href = link;
        anchor.target = '_blank';
        anchor.rel = 'noreferrer';
        row.append(content, anchor);
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
    if (evidence.match === false) return { word: 'Different', glyph: '≠', tone: 'diff' };
    return { word: 'Review', glyph: '?', tone: 'review' };
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

  function highlightBox(left, top, width, height) {
    const mark = element('span', 'doc-highlight');
    mark.setAttribute('aria-hidden', 'true');
    Object.assign(mark.style, { left: pct(left), top: pct(top), width: pct(width), height: pct(height) });
    return mark;
  }

  function documentVisual(source, mode, label) {
    // Positions are PDF points with a top-left origin; expressing them as a
    // share of the rendered region keeps the highlight exact at any width.
    const wrap = element('div', 'doc-visual');
    const path = source?.document;
    if (!path) {
      wrap.append(element('p', 'doc-empty', 'No source location was recorded for this value.'));
      return wrap;
    }
    if (!/\.pdf$/i.test(path)) {
      wrap.append(source.source_text
        ? element('blockquote', 'doc-snippet', source.source_text)
        : element('p', 'doc-empty', 'Page images are available for PDF documents only.'));
      return wrap;
    }
    const width = Number(source.page_width), height = Number(source.page_height);
    const box = Array.isArray(source.bbox) && source.bbox.length === 4 ? source.bbox.map(Number) : null;
    const placeable = Boolean(box) && width > 0 && height > 0;
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
    if (crop) {
      const [x0, y0, x1, y1] = cropRegion(mark, width, height);
      const rw = x1 - x0, rh = y1 - y0;
      frame.style.aspectRatio = `${rw} / ${rh}`;
      Object.assign(img.style, { width: pct(width / rw), left: pct(-x0 / rw), top: pct(-y0 / rh) });
      frame.append(img, highlightBox((mark[0] - x0) / rw, (mark[1] - y0) / rh,
        (mark[2] - mark[0]) / rw, (mark[3] - mark[1]) / rh));
    } else {
      if (width > 0 && height > 0) frame.style.aspectRatio = `${width} / ${height}`;
      frame.append(img);
      if (mark) {
        frame.append(highlightBox(mark[0] / width, mark[1] / height,
          (mark[2] - mark[0]) / width, (mark[3] - mark[1]) / height));
      }
    }
    img.src = pageImageUrl(path, source.page);
    wrap.append(frame);
    return wrap;
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
      block.append(sideHead, value, documentVisual(source, context.mode, label));
      sides.append(block);
    });

    const parts = [head, sides];
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
    parts.push(foot, form);
    pane.replaceChildren(...parts);
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
      element('p', differing || pending ? 'review-summary' : 'review-summary is-ok',
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
      list.append(row);
      return row;
    });

    function select(field) {
      rows.forEach(row => row.setAttribute('aria-current', String(row.dataset.field === field)));
      context.field = field;
      context.evidence = fields[field] || {};
      renderEvidencePane(pane, context);
    }

    list.addEventListener('keydown', event => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const index = rows.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? rows.length - 1
          : Math.min(rows.length - 1, Math.max(0, index + (event.key === 'ArrowDown' ? 1 : -1)));
      rows[next].focus();
      select(rows[next].dataset.field);
    });

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
          BLOCKED: 'Field comparison is blocked until the unresolved document issue is cleared.',
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
        element('span', '', displayDocumentName(doc)),
        element('span', 'active-tag', doc.is_active ? `Active · v${doc.version_index}` : `v${doc.version_index}`)
      );
      list.append(row);
    });
    section.append(list);
    return section;
  }

  function renderReview(task, caseId) {
    const section = element('section', 'detail-section review-box');
    section.append(element('h3', '', 'Resolve review task'));
    const form = element('form', 'review-form');
    const actor = element('input');
    actor.name = 'actor'; actor.type = 'email'; actor.required = true; actor.placeholder = 'Reviewer email';
    const note = element('input');
    note.name = 'note'; note.required = true; note.placeholder = 'Decision or resolution note';
    const submit = element('button', 'primary-button', 'Record resolution');
    submit.type = 'submit';
    const message = element('p', 'inline-message', `${stateLabel(task.kind)} · ${task.reason ? stateLabel(task.reason) : 'Review required'}`);
    form.append(actor, note, submit);
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; submit.textContent = 'Recording…';
      try {
        await api(`/api/review-tasks/${task.task_id}/resolve`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ actor: actor.value, note: note.value })
        });
        await loadWorkspace({ preserveSelection: true });
      } catch (error) {
        message.textContent = error.message; submit.disabled = false; submit.textContent = 'Record resolution';
      }
    });
    section.append(form, message);
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
      const list = $('case-list'); list.replaceChildren();
      $('queue-status').textContent = `${items.length} ${items.length === 1 ? 'message' : 'messages'}`;
      if (!items.length) {
        list.append(element('div', 'empty-list', 'No mail has been routed outside document comparison.'));
        emptyDetail('No routed mail', 'Unrelated mailbox messages will appear here with sender, subject, category, and source link.');
        return;
      }
      items.forEach(item => {
        const button = element('button', 'case-item');
        button.type = 'button';
        const top = element('div', 'case-item-top');
        top.append(element('strong', '', item.subject || 'No subject'), element('span', 'state state-waiting', classificationLabel(item.payload_json || item)));
        button.append(top, element('p', '', item.sender || 'Unknown sender'), element('div', 'case-item-bottom', formatTime(item.created_at)));
        button.addEventListener('click', () => renderRoutedDetail(item));
        list.append(button);
      });
      renderRoutedDetail(items[0]);
    } catch (error) {
      $('queue-status').textContent = error.message;
      emptyDetail('Could not load routed mail', error.message);
    }
  }

  function renderRoutedDetail(item) {
    const payload = item.payload_json || {};
    const detail = $('case-detail');
    const head = element('header', 'detail-head');
    const title = element('div');
    title.append(element('h2', '', item.subject || 'No subject'), element('p', '', item.sender || 'Unknown sender'));
    head.append(title, element('span', 'state state-waiting', classificationLabel(payload || item)));
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
    const link = gmailUrl(payload, state.mailbox?.account);
    if (link) {
      const anchor = element('a', 'primary-link', 'Open original email');
      anchor.href = link;
      anchor.target = '_blank';
      anchor.rel = 'noreferrer';
      section.append(anchor);
    }
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
    $('queue-title').textContent = state.view === 'all' ? 'All cases' : 'Action queue';
    $('queue-description').textContent = state.view === 'all' ? 'Every shipment case.' : 'Cases requiring a person.';
    $('state-filter').value = state.view === 'all' ? 'ALL' : 'ACTION';
    applyFilters();
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
    await loadRoutedPreview();
    if (state.mailbox?.connected) await loadWorkspace({ preserveSelection: true, background: true });
  }, 30000);
  loadIdentity();
  loadMailbox();
  loadRoutedPreview();
  loadWorkspace({ preserveSelection: false });
})();
