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

  function renderMailbox(mailbox) {
    state.mailbox = mailbox;
    const ready = mailbox.configured && mailbox.connected;
    $('mailbox-dot').classList.toggle('is-online', ready);
    $('mailbox-dot').classList.toggle('is-warning', mailbox.configured && !mailbox.connected);
    $('mailbox-title').textContent = ready
      ? `Gmail connected${mailbox.account ? `: ${mailbox.account}` : ''}`
      : mailbox.configured ? 'Gmail ready to connect' : 'Gmail needs OAuth settings';
    $('mailbox-detail').textContent = mailbox.last_error || mailbox.next_action;
    $('mailbox-query').textContent = mailbox.query ? `Query: ${mailbox.query}` : 'No query active';
    $('mailbox-sync').textContent = mailbox.last_sync_at
      ? `Last sync ${formatTime(mailbox.last_sync_at)}. ${mailbox.processed || 0} processed.`
      : `${mailbox.processed || 0} processed. Not synced yet.`;
    $('mailbox-connect').disabled = !mailbox.configured;
    $('mailbox-sync-button').disabled = !ready;
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
      button.disabled = !(state.mailbox?.configured && state.mailbox?.connected);
    }
  }

  async function loadWorkspace({ preserveSelection = true } = {}) {
    $('refresh-button').classList.add('is-loading');
    try {
      const [health, metrics, cases] = await Promise.all([
        api('/health'), api('/api/metrics'), api('/api/cases')
      ]);
      setConnection(true, health.store);
      state.cases = cases.items;
      $('metric-action').textContent = ['DISCREPANCY', 'NEEDS_REVIEW', 'BLOCKED']
        .reduce((sum, key) => sum + (metrics.states[key] || 0), 0);
      $('metric-verified').textContent = metrics.states.VERIFIED || 0;
      $('metric-waiting').textContent = metrics.states.WAITING || 0;
      $('metric-routed').textContent = metrics.routed_messages || 0;
      $('nav-action-count').textContent = metrics.open_review_tasks || 0;
      if (state.view === 'routed') {
        await loadRoutedView();
        return;
      }
      applyFilters();
      if (preserveSelection && state.selectedId && state.cases.some(c => c.case_id === state.selectedId)) {
        await openCase(state.selectedId);
      } else if (state.filtered.length) {
        await openCase(state.filtered[0].case_id);
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

  function evidenceViewerUrl(field, side, source, fallbackPath) {
    const path = source?.document || fallbackPath;
    if (!path) return '';
    const params = new URLSearchParams({ path, field: FIELD_LABELS[field] || field, side });
    if (source?.page) params.set('page', source.page);
    if (source?.bbox) params.set('bbox', source.bbox.join(','));
    if (source?.source_text) params.set('text', source.source_text);
    if (source?.page_width && source?.page_height) {
      params.set('pw', source.page_width);
      params.set('ph', source.page_height);
    }
    if (source?.line) params.set('line', source.line);
    return `/app/evidence.html?${params.toString()}`;
  }

  function evidenceActions(field, fieldEvidence = {}, comparisonEvidence = {}) {
    const actions = element('div', 'evidence-actions');
    [
      ['SI evidence', 'SI', fieldEvidence.si_source, comparisonEvidence.si_doc],
      ['BL evidence', 'BL', fieldEvidence.bl_source, comparisonEvidence.bl_doc]
    ].forEach(([label, side, source, fallbackPath]) => {
      const href = evidenceViewerUrl(field, side, source, fallbackPath);
      if (!href) return;
      const link = element('a', 'evidence-link', label);
      link.href = href;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.title = source?.bbox ? 'Open exact source evidence.' : 'Open source document. Exact box is not available for this extraction.';
      actions.append(link);
    });
    return actions;
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
      const preview = element('a', 'secondary-link compact-link', 'Preview');
      preview.href = attachmentUrl('preview', path);
      preview.target = '_blank';
      preview.rel = 'noreferrer';
      const download = element('a', 'secondary-link compact-link', 'Download');
      download.href = attachmentUrl('download', path);
      download.setAttribute('download', '');
      actions.append(preview, download);
      row.append(label, actions);
      list.append(row);
    });
    box.append(list);
    return box;
  }

  async function openCase(caseId) {
    state.selectedId = caseId;
    renderCases();
    const detail = $('case-detail');
    detail.replaceChildren($('loading-template').content.cloneNode(true));
    try {
      renderDetail(await api(`/api/cases/${encodeURIComponent(caseId)}`));
    } catch (error) {
      const box = element('div', 'error-state');
      box.append(element('h2', '', 'Could not load this case'), element('p', '', error.message));
      detail.replaceChildren(box);
    }
  }

  function renderDetail(data) {
    const detail = $('case-detail');
    const head = element('header', 'detail-head');
    const title = element('div');
    title.append(element('h2', '', data.shipment_reference), element('p', '', actionCopy(data.state)));
    head.append(title, stateBadge(data.state));
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
        const anchor = element('a', 'secondary-link', 'Open in Gmail');
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

  function correctionRow(caseId, field, evidence) {
    const row = element('tr', 'correction-row');
    row.hidden = true;
    const cell = element('td');
    cell.colSpan = 5;
    const form = element('form', 'correction-form');
    const side = document.createElement('select');
    [['si', 'Shipping instruction'], ['bl', 'Draft bill of lading']].forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = label;
      side.append(option);
    });
    const value = element('input');
    value.required = true;
    value.placeholder = 'Corrected value, exactly as printed';
    value.value = evidence.si ?? '';
    side.addEventListener('change', () => { value.value = (side.value === 'si' ? evidence.si : evidence.bl) ?? ''; });
    const actor = element('input');
    actor.type = 'email'; actor.required = true; actor.placeholder = 'Your email';
    const note = element('input');
    note.placeholder = 'Why the original was wrong (optional)';
    const submit = element('button', 'primary-button', 'Save and re-compare');
    submit.type = 'submit';
    const message = element('p', 'inline-message', '');
    form.append(side, value, actor, note, submit);
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
    cell.append(form, message);
    row.append(cell);
    return row;
  }

  function renderComparison(comparison, caseState, caseId) {
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
            element('td', '', FIELD_LABELS[field]),
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
    if (caseState === 'VERIFIED') {
      section.append(element('p', 'comparison-summary is-ok', 'All 7 required fields match.'));
    }
    const table = element('table');
    const thead = element('thead');
    const header = element('tr');
    ['Field', 'Shipping instruction', 'Draft bill of lading', 'Result', 'Source evidence'].forEach(label => header.append(element('th', '', label)));
    thead.append(header);
    const tbody = element('tbody');
    FIELD_ORDER.forEach(field => {
      const evidence = comparison.evidence.fields[field] || {};
      const row = element('tr', evidence.match === false ? 'is-different' : '');
      const result = element('td', 'result-word', evidence.match === true ? 'Match' : evidence.match === false ? 'Different' : 'Review');
      if (evidence.corrected) {
        result.append(element('span', 'corrected-tag', `Corrected from ${evidence.corrected.from || 'blank'}`));
      }
      const actions = element('td');
      actions.append(evidenceActions(field, evidence, comparison.evidence));
      const correct = element('button', 'link-button', 'Correct');
      correct.type = 'button';
      actions.append(correct);
      row.append(
        element('td', '', FIELD_LABELS[field]),
        element('td', '', evidence.si ?? 'Unavailable'),
        element('td', '', evidence.bl ?? 'Unavailable'),
        result,
        actions
      );
      tbody.append(row);
      const editor = correctionRow(caseId, field, evidence);
      tbody.append(editor);
      correct.addEventListener('click', () => { editor.hidden = !editor.hidden; });
    });
    table.append(thead, tbody);
    section.append(table);
    const verification = comparison.evidence.verification;
    if (verification) {
      section.append(element('p', 'evidence-note', verification.status === 'AGREED'
        ? 'Independent document read agreed with the first extraction.'
        : `Independent verification: ${stateLabel(verification.status)}.`));
    }
    return section;
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
    try {
      const data = await api('/api/routed-messages');
      const items = data.items || [];
      const list = $('case-list'); list.replaceChildren();
      $('queue-status').textContent = `${items.length} ${items.length === 1 ? 'message' : 'messages'}`;
      if (!items.length) {
        list.append(element('div', 'empty-list', 'No mail has been routed outside document comparison.'));
        emptyDetail('No routed mail', 'Unrelated Gmail messages will appear here with sender, subject, category, and source link.');
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
      const anchor = element('a', 'primary-link', 'Open original email in Gmail');
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
    $('queue-title').textContent = state.view === 'all' ? 'All cases' : 'Action queue';
    $('queue-description').textContent = state.view === 'all' ? 'Every shipment case.' : 'Cases requiring a person.';
    $('state-filter').value = state.view === 'all' ? 'ALL' : 'ACTION';
    applyFilters();
  }));

  $('state-filter').addEventListener('change', applyFilters);
  $('search-input').addEventListener('input', event => { state.search = event.target.value.trim(); applyFilters(); });
  $('refresh-button').addEventListener('click', () => loadWorkspace());
  $('mailbox-connect').addEventListener('click', () => { window.location.href = '/api/mailbox/connect'; });
  $('mailbox-sync-button').addEventListener('click', syncMailbox);
  setInterval(async () => {
    await loadMailbox();
    await loadRoutedPreview();
    if (state.mailbox?.connected) await loadWorkspace({ preserveSelection: true });
  }, 30000);
  loadMailbox();
  loadRoutedPreview();
  loadWorkspace({ preserveSelection: false });
})();
