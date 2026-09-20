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
  async function get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
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
      setText('waiting-cases', metrics.waiting_cases);
      setText('overdue-cases', metrics.overdue_cases);
      renderBars(metrics); renderFields(metrics.discrepancy_fields);
      setText('data-note', 'Metrics reflect the current persisted case store. Rates describe workflow outcomes, not estimated financial savings.');
    } catch (error) {
      setConnection(false, ''); setText('data-note', error.message);
    } finally { $('admin-refresh').classList.remove('is-loading'); }
  }

  $('admin-refresh').addEventListener('click', load);
  load();
})();
