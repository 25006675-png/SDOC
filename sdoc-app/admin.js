(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const STATE_ORDER = ['VERIFIED', 'DISCREPANCY', 'NEEDS_REVIEW', 'WAITING', 'BLOCKED'];
  const LABELS = {
    VERIFIED: 'Verified', DISCREPANCY: 'Discrepancy', NEEDS_REVIEW: 'Unconfirmed',
    WAITING: 'Waiting', BLOCKED: 'Stalled', gross_weight_kg: 'Gross weight',
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

  function notify(message, undo) {
    const notice = $('admin-notice');
    notice.replaceChildren(document.createTextNode(message));
    notice.hidden = false;
    if (undo) {
      const button = document.createElement('button');
      button.className = 'link-button'; button.type = 'button'; button.textContent = 'Undo';
      button.addEventListener('click', () => { undo(); notify('Demo member restored.'); });
      notice.append(button);
    }
  }

  function renderMembers() {
    const body = $('member-rows');
    const query = $('member-search').value.trim().toLowerCase();
    const visible = MEMBERS.filter(member => `${member.name} ${member.username}`.toLowerCase().includes(query));
    setText('member-count', MEMBERS.length);
    setText('member-summary', `${MEMBERS.length} members / ${MEMBERS.filter(m => m.role === 'Admin').length} administrators`);
    $('members-empty').hidden = visible.length > 0;
    body.replaceChildren(...visible.map(member => {
      const row = document.createElement('tr');
      const cell = (text, cls) => {
        const td = document.createElement('td');
        if (cls) td.className = cls;
        td.textContent = text; return td;
      };
      const name = cell('', 'member-identity');
      const avatar = document.createElement('span'); avatar.className = 'member-avatar';
      avatar.textContent = member.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('');
      avatar.setAttribute('aria-hidden', 'true');
      name.append(avatar, document.createTextNode(member.name));
      const actions = cell('');
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'link-button'; remove.textContent = 'Remove';
      remove.setAttribute('aria-label', `Remove ${member.name}`);
      remove.addEventListener('click', () => {
        const index = MEMBERS.indexOf(member);
        MEMBERS.splice(index, 1); renderMembers();
        notify(`${member.name} removed from the demo team.`, () => { MEMBERS.splice(index, 0, member); renderMembers(); });
        $('member-search').focus({ preventScroll: true });
      });
      actions.append(remove);
      row.append(name, cell(member.username), cell(member.role, member.role === 'Admin' ? 'role-admin' : 'role-worker'),
        cell(member.status, member.status === 'Active' ? 'status-active' : 'status-invited'), actions);
      return row;
    }));
  }

  function wireMemberDemo() {
    const form = $('member-form');
    const close = () => {
      form.hidden = true; form.reset(); $('member-error').hidden = true;
      $('invite-member').setAttribute('aria-expanded', 'false'); $('invite-member').focus();
    };
    $('invite-member').addEventListener('click', () => {
      if (!form.hidden) { close(); return; }
      form.hidden = false; $('invite-member').setAttribute('aria-expanded', 'true'); $('member-name').focus();
    });
    $('cancel-member').addEventListener('click', close);
    form.addEventListener('submit', event => {
      event.preventDefault();
      const name = $('member-name').value.trim();
      const email = $('member-email').value.trim().toLowerCase();
      if (!name || MEMBERS.some(member => member.username.toLowerCase() === email)) {
        setText('member-error', !name ? 'Enter a member name.' : 'This email is already on the demo team.');
        $('member-error').hidden = false; return;
      }
      MEMBERS.push({ name, username: email, role: $('member-role').value, status: 'Invited' });
      $('member-search').value = ''; close(); renderMembers(); notify(`${name} added to the demo team. No invitation was sent.`);
    });
    $('member-search').addEventListener('input', renderMembers);
  }

  function wireAdminTabs() {
    const tabs = [...document.querySelectorAll('[data-admin-tab]')];
    const descriptions = {
      overview: ['Operations overview', 'A clear view of your queue, review workload and document quality.'],
      members: ['Team members', 'Give your operations team the right access to the workspace.'],
      connections: ['Mailbox connections', 'Manage the inboxes that feed your shipment review queue.'],
      settings: ['Workspace settings', 'Organisation details, review preferences and access defaults.']
    };
    function activate(key, updateHash = true) {
      if (!descriptions[key]) key = 'overview';
      tabs.forEach(tab => {
        const selected = tab.dataset.adminTab === key;
        tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
        $(tab.getAttribute('aria-controls')).hidden = !selected;
      });
      setText('admin-title', descriptions[key][0]); setText('admin-description', descriptions[key][1]);
      $('admin-refresh').hidden = key !== 'overview'; $('admin-notice').hidden = true;
      if (updateHash) history.replaceState(null, '', `#${key}`);
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activate(tab.dataset.adminTab));
      tab.addEventListener('keydown', event => {
        if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[next].focus(); activate(tabs[next].dataset.adminTab);
      });
    });
    window.addEventListener('hashchange', () => activate(location.hash.slice(1), false));
    activate(location.hash.slice(1), false);
  }

  function wireSettingsDemo() {
    const form = $('settings-form');
    const controls = [...form.querySelectorAll('input, select')];
    const snapshot = () => controls.map(control => control.type === 'checkbox' ? control.checked : control.value);
    let saved = snapshot();
    const dirtyState = () => {
      const dirty = JSON.stringify(snapshot()) !== JSON.stringify(saved);
      $('settings-save').disabled = !dirty; $('settings-reset').disabled = !dirty;
      setText('settings-status', dirty ? 'Unsaved demo changes' : 'No unsaved changes');
    };
    form.addEventListener('input', dirtyState); form.addEventListener('change', dirtyState);
    $('settings-reset').addEventListener('click', () => {
      controls.forEach((control, index) => { if (control.type === 'checkbox') control.checked = saved[index]; else control.value = saved[index]; });
      dirtyState(); notify('Unsaved demo changes discarded.');
    });
    form.addEventListener('submit', event => {
      event.preventDefault(); saved = snapshot(); dirtyState();
      setText('settings-status', 'Demo settings saved for this visit');
      notify('Demo preferences saved until reload. Live workspace settings are unchanged.');
    });
  }

  const PROVIDER_MARKS = {
    gmail: '<img src="/assets/icons/gmail.webp" alt="Gmail">',
    outlook: '<img src="/assets/icons/outlook.webp" alt="Outlook">'
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
  function setText(id, value) {
    const node = $(id);
    const changed = node.textContent !== String(value);
    const hadValue = node.dataset.loaded === 'true';
    node.textContent = value; node.dataset.loaded = 'true';
    if (changed && hadValue && node.matches('.admin-summary strong, .metric-list dd, .reliability-score strong') && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      node.animate([{ backgroundColor: '#fdf0e3' }, { backgroundColor: 'transparent' }], { duration: 700 });
    }
  }
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
    STATE_ORDER.forEach(state => {
      const count = metrics.states[state] || 0;
      let row = root.querySelector(`[data-state="${state}"]`);
      if (!row) {
        row = document.createElement('div'); row.className = 'bar-row'; row.dataset.state = state;
        const label = document.createElement('span'); label.textContent = LABELS[state];
        const track = document.createElement('div'); track.className = 'bar-track'; track.setAttribute('aria-hidden', 'true');
        const fill = document.createElement('i'); fill.className = `bar-fill bar-${state.toLowerCase()}`;
        track.append(fill); row.append(label, track, document.createElement('strong')); root.append(row);
      }
      row.querySelector('.bar-fill').style.transform = `scaleX(${metrics.cases ? Math.min(1, count / metrics.cases) : 0})`;
      row.querySelector('strong').textContent = count;
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
    $('admin-refresh').disabled = true;
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
    } finally { $('admin-refresh').classList.remove('is-loading'); $('admin-refresh').disabled = false; }
  }

  $('admin-refresh').addEventListener('click', load);
  loadIdentity();
  $('mailbox-refresh').addEventListener('click', loadMailboxes);
  wireAdminTabs();
  wireSettingsDemo();
  renderMembers();
  wireMemberDemo();
  loadMailboxes();
  load();
})();
