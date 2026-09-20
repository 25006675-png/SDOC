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


  const PROVIDER_MARKS = {
    gmail: '<svg viewBox="0 0 24 24" role="img" aria-label="Gmail"><rect x="1.5" y="4" width="21" height="16" rx="2.5" fill="#fff" stroke="#dadce0"/><path d="M2 6.2 12 13 22 6.2V18a2 2 0 0 1-2 2h-1.6V9.9L12 14.3 5.6 9.9V20H4a2 2 0 0 1-2-2Z" fill="#ea4335"/><path d="M2 6.2A2 2 0 0 1 4 4h.9L12 9 19.1 4h.9a2 2 0 0 1 2 2.2L12 13Z" fill="#c5221f"/></svg>',
    outlook: '<svg viewBox="0 0 24 24" role="img" aria-label="Outlook"><rect x="9" y="4.5" width="13.5" height="15" rx="1.6" fill="#0f6cbd"/><path d="M11 9h9.5v2.2L15.8 14 11 11.2Z" fill="#fff" opacity=".85"/><rect x="1.5" y="6" width="11" height="12" rx="2.2" fill="#0a4f8f"/><ellipse cx="7" cy="12" rx="3.1" ry="3.6" fill="none" stroke="#fff" stroke-width="1.7"/></svg>'
  };

  function relativeTime(value) {
    if (!value) return 'never synced';
    const seconds = Math.max(0, (Date.now() / 1000) - Number(value));
    if (seconds < 90) return 'synced just now';
    if (seconds < 3600) return `synced ${Math.round(seconds / 60)} min ago`;
    if (seconds < 86400) return `synced ${Math.round(seconds / 3600)} hr ago`;
    return `synced ${Math.round(seconds / 86400)} days ago`;
  }

  function providerRow(mailbox) {
    const row = document.createElement('li');
    row.className = 'provider-row';

    const mark = document.createElement('span');
    mark.className = 'provider-mark';
    mark.innerHTML = PROVIDER_MARKS[mailbox.provider] || '';

    const text = document.createElement('div');
    text.className = 'provider-text';
    const name = document.createElement('strong');
    name.textContent = mailbox.label;
    if (mailbox.is_default) {
      const tag = document.createElement('span');
      tag.className = 'default-tag';
      tag.textContent = 'Default';
      name.append(tag);
    }
    const detail = document.createElement('small');
    detail.textContent = mailbox.connected
      ? `${mailbox.account || 'Connected'} · ${relativeTime(mailbox.last_sync_at)}`
      : (mailbox.last_error || mailbox.next_action || 'Not connected');
    text.append(name, detail);

    const state = document.createElement('span');
    const connected = Boolean(mailbox.connected);
    state.className = `provider-state ${connected ? 'is-connected' : mailbox.configured ? 'is-ready' : 'is-off'}`;
    state.textContent = connected ? 'Connected' : mailbox.configured ? 'Ready to connect' : 'Not configured';

    const actions = document.createElement('div');
    actions.className = 'provider-actions';
    if (connected) {
      const sync = document.createElement('button');
      sync.type = 'button';
      sync.className = 'primary-button';
      sync.textContent = 'Sync now';
      sync.addEventListener('click', () => syncProvider(mailbox.provider, sync));
      actions.append(sync);
    }
    const connect = document.createElement('button');
    connect.type = 'button';
    connect.className = 'secondary-button';
    connect.textContent = connected ? 'Reconnect' : 'Connect';
    connect.disabled = !mailbox.configured;
    connect.title = mailbox.configured ? '' : 'Set this provider\'s OAuth credentials first';
    connect.addEventListener('click', () => {
      window.location.href = `/api/mailbox/${mailbox.provider}/connect`;
    });
    actions.append(connect);

    row.append(mark, text, state, actions);
    return row;
  }

  async function syncProvider(provider, button) {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Syncing…';
    try {
      const result = await api(`/api/mailbox/${provider}/sync`, { method: 'POST' });
      setText('mailbox-note', `${provider}: ${result.processed_now || 0} new message(s) processed.`);
    } catch (error) {
      setText('mailbox-note', error.message);
    } finally {
      button.textContent = label;
      button.disabled = false;
      loadMailboxes();
    }
  }

  async function loadMailboxes() {
    const list = document.getElementById('provider-list');
    if (!list) return;
    try {
      const data = await api('/api/mailboxes');
      list.replaceChildren(...data.items.map(providerRow));
      const live = data.items.filter(item => item.connected).length;
      setText('mailbox-note', live
        ? `${live} of ${data.items.length} mailboxes connected. Both providers can run at the same time.`
        : 'No mailbox connected yet. Connect one to start live inbox analysis.');
    } catch (error) {
      list.replaceChildren();
      setText('mailbox-note', error.message);
    }
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
  loadIdentity();
  $('mailbox-refresh').addEventListener('click', loadMailboxes);
  renderMembers();
  wireMemberDemo();
  loadMailboxes();
  load();
})();
