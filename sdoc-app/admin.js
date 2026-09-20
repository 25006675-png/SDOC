(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const STATE_ORDER = ['VERIFIED', 'DISCREPANCY', 'NEEDS_REVIEW', 'WAITING', 'BLOCKED'];
  const LABELS = {
    VERIFIED: 'Verified', DISCREPANCY: 'Discrepancy', NEEDS_REVIEW: 'Needs review',
    WAITING: 'Waiting', BLOCKED: 'Blocked', gross_weight_kg: 'Gross weight',
    container_count: 'Container count', port_of_loading: 'Port of loading',
    port_of_discharge: 'Port of discharge', notify_party: 'Notify party',
    shipper: 'Shipper', consignee: 'Consignee'
  };


  async function loadIdentity() {
    let identity = null;
    try { identity = await (await fetch('/api/auth/status')).json(); } catch (_) { return; }
    if (!identity || !identity.auth_enabled || !identity.username) return;
    const box = document.getElementById('sidebar-user');
    if (!box) return;
    box.hidden = false;
    document.getElementById('user-name').textContent = identity.display_name || identity.username;
    document.getElementById('user-role').textContent =
      identity.role === 'admin' ? 'Administrator' : 'Worker';
    document.getElementById('user-initial').textContent =
      (identity.display_name || identity.username).trim().charAt(0).toUpperCase();
  }

  const MEMBERS = [
    { name: 'Operations Manager', username: 'admin', role: 'Admin', status: 'Active' },
    { name: 'Documentation Officer', username: 'worker', role: 'Worker', status: 'Active' },
    { name: 'Lim Wei Sheng', username: 'w.lim', role: 'Worker', status: 'Active' },
    { name: 'Nurul Aisyah', username: 'n.aisyah', role: 'Worker', status: 'Invited' }
  ];

  function renderMembers() {
    const body = document.getElementById('member-rows');
    if (!body) return;
    body.replaceChildren(...MEMBERS.map(member => {
      const row = document.createElement('tr');
      const cell = (text, cls) => {
        const td = document.createElement('td');
        if (cls) td.className = cls;
        td.textContent = text;
        return td;
      };
      const actions = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'link-button';
      remove.textContent = 'Remove';
      remove.addEventListener('click', () => row.remove());
      actions.append(remove);
      row.append(
        cell(member.name),
        cell(member.username, 'mono'),
        cell(member.role, member.role === 'Admin' ? 'role-admin' : 'role-worker'),
        cell(member.status, member.status === 'Active' ? 'status-active' : 'status-invited'),
        actions
      );
      return row;
    }));
  }

  function wireMemberDemo() {
    const invite = document.getElementById('invite-member');
    if (!invite) return;
    invite.addEventListener('click', () => {
      setText('data-note', 'Member management is a demo surface in this build; invitations are not sent.');
    });
  }

  function percent(value) { return `${Math.round((value || 0) * 100)}%`; }
  function duration(seconds) {
    if (seconds === null || seconds === undefined) return 'Not available';
    if (seconds < 60) return `${Math.round(seconds)} sec`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} hr`;
    return `${(seconds / 86400).toFixed(1)} days`;
  }
  function setText(id, value) { $(id).textContent = value; }
  function setConnection(ok, store) {
    $('connection-dot').classList.toggle('is-online', ok);
    setText('connection-label', ok ? 'Backend online' : 'Backend unavailable');
    setText('store-label', ok ? store : 'Retry with refresh');
  }
  async function api(path, options) {
    const response = await fetch(path, options);
    if (response.status === 401 || response.status === 403) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      throw new Error('Sign in required');
    }
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }
  const get = path => api(path);


  function formatTime(value) {
    if (value === null || value === undefined) return 'Time unavailable';
    const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function renderMailbox(mailbox) {
    const providerName = mailbox.provider === 'outlook' ? 'Outlook' : mailbox.provider === 'gmail' ? 'Gmail' : 'Mailbox';
    const ready = mailbox.configured && mailbox.connected;
    $('admin-mailbox-dot').classList.toggle('is-online', ready);
    $('admin-mailbox-dot').classList.toggle('is-warning', mailbox.configured && !mailbox.connected);
    setText('admin-mailbox-title', ready
      ? `Mailbox connected${mailbox.account ? `: ${mailbox.account}` : ''}`
      : mailbox.configured ? 'Mailbox ready to connect' : 'Mailbox needs OAuth settings');
    setText('admin-mailbox-detail', mailbox.last_error || mailbox.next_action);
    setText('admin-mailbox-query', mailbox.query ? `Query: ${mailbox.query}` : 'No query active');
    setText('admin-mailbox-sync', mailbox.last_sync_at
      ? `Last sync ${formatTime(mailbox.last_sync_at)}. ${mailbox.processed || 0} processed.`
      : `${mailbox.processed || 0} processed. Not synced yet.`);
    $('admin-mailbox-connect').disabled = !mailbox.configured;
    $('admin-mailbox-sync-button').disabled = !ready;
  }

  async function loadMailbox() {
    try {
      renderMailbox(await api('/api/mailbox/status'));
    } catch (error) {
      setText('admin-mailbox-detail', error.message);
    }
  }

  async function syncMailbox() {
    const button = $('admin-mailbox-sync-button');
    button.disabled = true; button.textContent = 'Syncing?';
    try {
      renderMailbox(await api('/api/mailbox/sync', { method: 'POST' }));
      await load();
    } catch (error) {
      setText('admin-mailbox-detail', error.message);
    } finally {
      button.textContent = 'Sync now';
    }
  }

  function renderBars(metrics) {
    const root = $('state-bars');
    root.replaceChildren();
    STATE_ORDER.forEach(state => {
      const count = metrics.states[state] || 0;
      const row = document.createElement('div'); row.className = 'bar-row';
      const label = document.createElement('span'); label.textContent = LABELS[state];
      const track = document.createElement('div'); track.className = 'bar-track';
      const fill = document.createElement('i'); fill.className = `bar-fill bar-${state.toLowerCase()}`;
      fill.style.width = `${metrics.cases ? Math.max(2, count / metrics.cases * 100) : 0}%`;
      track.append(fill);
      const value = document.createElement('strong'); value.textContent = count;
      row.append(label, track, value); root.append(row);
    });
  }

  function renderFields(fields) {
    const root = $('field-ranking'); root.replaceChildren();
    const entries = Object.entries(fields || {});
    if (!entries.length) {
      const empty = document.createElement('p'); empty.className = 'definition-note';
      empty.textContent = 'No discrepancy fields have been recorded.'; root.append(empty); return;
    }
    entries.forEach(([field, count], index) => {
      const row = document.createElement('div');
      const rank = document.createElement('span'); rank.textContent = index + 1;
      const label = document.createElement('strong'); label.textContent = LABELS[field] || field.replaceAll('_', ' ');
      const value = document.createElement('b'); value.textContent = count;
      row.append(rank, label, value); root.append(row);
    });
  }

  async function load() {
    $('admin-refresh').classList.add('is-loading');
    try {
      const [health, metrics] = await Promise.all([get('/health'), get('/api/metrics')]);
      setConnection(true, health.store);
      setText('processed-messages', metrics.processed_messages);
      setText('automation-rate', percent(metrics.automated_resolution_rate));
      setText('review-rate', percent(metrics.manual_review_rate));
      setText('active-backlog', metrics.active_backlog);
      setText('total-cases', metrics.cases);
      setText('open-tasks', metrics.open_review_tasks);
      setText('classification-review', metrics.classification_review_messages || 0);
      setText('resolved-tasks', metrics.resolved_review_tasks);
      setText('oldest-action', duration(metrics.oldest_action_age_seconds));
      setText('average-resolution', duration(metrics.average_review_resolution_seconds));
      setText('agreement-rate', metrics.verifier_checks ? percent(metrics.verifier_agreement_rate) : 'No checks');
      setText('verifier-checks', metrics.verifier_checks);
      setText('verifier-disagreements', metrics.verifier_disagreements);
      setText('verifier-failures', metrics.verifier_failures);
      const reads = metrics.extraction_reads || 0;
      setText('extraction-reads', reads);
      setText('first-pass-rate', reads ? percent(metrics.first_pass_validated_rate) : 'No reads');
      setText('recovered-rate', reads ? percent(metrics.recovered_rate) : '—');
      setText('extraction-review', (metrics.extraction_statuses || {}).NEEDS_REVIEW || 0);
      setText('waiting-cases', metrics.waiting_cases);
      setText('overdue-cases', metrics.overdue_cases);
      renderBars(metrics); renderFields(metrics.discrepancy_fields);
      setText('data-note', 'Metrics reflect the current persisted case store. Rates describe workflow outcomes, not estimated financial savings.');
    } catch (error) {
      setConnection(false, ''); setText('data-note', error.message);
    } finally { $('admin-refresh').classList.remove('is-loading'); }
  }

  $('admin-refresh').addEventListener('click', load);
  $('admin-mailbox-connect').addEventListener('click', () => { window.location.href = '/api/mailbox/connect'; });
  $('admin-mailbox-sync-button').addEventListener('click', syncMailbox);
  loadIdentity();
  renderMembers();
  wireMemberDemo();
  loadMailbox();
  load();
})();
