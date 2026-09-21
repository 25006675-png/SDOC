(() => {
  'use strict';
  document.documentElement.classList.add('js');
  const baseFields = [
    ['Shipper', 'Bluewater Logistics Sdn Bhd', 'Bluewater Logistics Sdn Bhd'],
    ['Consignee', 'Harborline Trading Pte Ltd', 'Harborline Trading Pte Ltd'],
    ['Notify party', 'Harborline Trading Pte Ltd', 'Harborline Trading Pte Ltd'],
    ['Port of loading', 'Port Klang', 'Port Klang'],
    ['Port of discharge', 'Singapore', 'Singapore'],
    ['Container count', '2', '2'],
    ['Gross weight', '18,500 KG', '16,500 KG']
  ];
  const scenarios = {
    discrepancy: {
      id: 'CASE #SD-0248', kicker: 'COMPARISON COMPLETE', title: '1 discrepancy detected',
      desc: 'Review the highlighted field before approving this draft.', state: 'DISCREPANCY', style: 'discrepancy', icon: 'i-alert',
      evidence: '7 fields checked · Original evidence linked', action: 'View source evidence',
      rows: baseFields.map(([name, si, bl], i) => ({ name, si, bl, result: i === 6 ? 'Mismatch' : 'Match', kind: i === 6 ? 'diff' : 'good' })),
      docs: [
        { label: 'SHIPPING INSTRUCTION', file: 'SI_0492.pdf · Page 2', value: '18,500 KG', quote: 'GROSS WEIGHT: 18,500 KGS' },
        { label: 'DRAFT BILL OF LADING', file: 'Draft_BL_v2.pdf · Page 1', value: '16,500 KG', quote: 'GROSS WEIGHT: 16,500 KGS' }
      ]
    },
    verified: {
      id: 'CASE #SD-0249', kicker: 'COMPARISON COMPLETE', title: 'All 7 fields match',
      desc: 'No discrepancies detected in this illustrative comparison.', state: 'VERIFIED', style: 'verified', icon: 'i-check',
      evidence: '7 fields checked · Original evidence linked', action: 'View source evidence',
      rows: baseFields.map(([name, si], i) => ({ name, si, bl: si, result: 'Match', kind: 'good' })),
      docs: [
        { label: 'SHIPPING INSTRUCTION', file: 'SI_0492.pdf · Page 2', value: '18,500 KG', quote: 'GROSS WEIGHT: 18,500 KGS' },
        { label: 'DRAFT BILL OF LADING', file: 'Draft_BL_v3.pdf · Page 1', value: '18,500 KG', quote: 'GROSS WEIGHT: 18,500 KGS' }
      ]
    },
    review: {
      id: 'CASE #SD-0250', kicker: 'HUMAN ATTENTION REQUIRED', title: '1 field unconfirmed',
      desc: 'Conflicting source values require a reviewer to confirm the correct weight.', state: 'UNCONFIRMED', style: 'review', icon: 'i-eye',
      evidence: 'Source conflict · Decision not automated', action: 'Inspect review context',
      rows: baseFields.map(([name, si, bl], i) => ({ name, si: i === 6 ? '18,500 / 18,800 KG' : si, bl: i === 6 ? '18,500 KG' : bl, result: i === 6 ? 'Unconfirmed' : 'Match', kind: i === 6 ? 'review' : 'good' })),
      docs: [
        { label: 'SHIPPING INSTRUCTION · CONFLICT', file: 'SI_0492.pdf · Pages 2–3', value: '18,500 / 18,800 KG', quote: 'PAGE 2: 18,500 KGS / PAGE 3: 18,800 KGS' },
        { label: 'DRAFT BILL OF LADING', file: 'Draft_BL_v2.pdf · Page 1', value: '18,500 KG', quote: 'GROSS WEIGHT: 18,500 KGS' }
      ]
    }
  };
  const $ = id => document.getElementById(id);
  let active = 'discrepancy';
  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function setScenario(key) {
    if (!Object.hasOwn(scenarios, key)) return;
    const previous = scenarios[active];
    const changed = active !== key;
    active = key;
    const s = scenarios[key];
    $('case-id').textContent = s.id;
    $('result-kicker').textContent = s.kicker;
    $('result-title').textContent = s.title;
    $('result-desc').textContent = s.desc;
    $('result-state').textContent = s.state;
    $('result-state').className = `result-state ${s.style}`;
    $('result-icon').className = `result-icon ${s.style === 'verified' ? 'result-good' : s.style === 'review' ? 'result-review' : 'result-warn'}`;
    $('result-icon').querySelector('use').setAttribute('href', `#${s.icon}`);
    $('result-icon').parentElement.className = `result-summary ${s.style}`;
    $('evidence-copy').textContent = s.evidence;
    $('demo-action').firstChild.textContent = `${s.action} `;
    const rows = $('comparison-rows');
    rows.replaceChildren();
    s.rows.forEach((f, index) => {
      const row = el('div', 'table-row' + (f.kind === 'diff' ? ' has-diff' : f.kind === 'review' ? ' has-review' : ''));
      row.setAttribute('role', 'row');
      const n = el('span', '', f.name), si = el('span', f.kind === 'diff' ? 'value-diff' : f.kind === 'review' ? 'value-review' : '', f.si);
      const bl = el('span', f.kind === 'diff' ? 'value-diff' : '', f.bl);
      const outcome = el('span', 'status-badge');
      const icon = document.createElementNS('http://www.w3.org/2000/svg','svg');
      const use = document.createElementNS('http://www.w3.org/2000/svg','use');
      use.setAttribute('href', f.kind === 'good' ? '#i-check' : f.kind === 'diff' ? '#i-alert' : '#i-eye');
      icon.append(use); outcome.append(icon, document.createTextNode(f.result));
      row.append(n,si,bl,outcome); rows.append(row);
      if (changed && JSON.stringify(f) !== JSON.stringify(previous.rows[index]) && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        row.animate([{ backgroundColor: '#f9dbb8' }, { backgroundColor: getComputedStyle(row).backgroundColor }], { duration: 750, easing: 'ease-out' });
      }
    });
    if (changed && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      $('result-icon').parentElement.animate([{ opacity: .5, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 200, easing: 'ease-out' });
    }
    document.querySelectorAll('[data-scenario]').forEach(tab => {
      const selected = tab.dataset.scenario === key;
      tab.classList.toggle('active',selected);
      tab.setAttribute('aria-selected',String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
  }
  document.querySelectorAll('[data-scenario]').forEach(tab => tab.addEventListener('click', () => setScenario(tab.dataset.scenario)));
  const tabs = [...document.querySelectorAll('[data-scenario]')];
  tabs.forEach((tab, index) => tab.addEventListener('keydown', e => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
    e.preventDefault();
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length-1 : (index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus(); setScenario(tabs[next].dataset.scenario);
  }));
  const dialog = $('evidence-dialog');
  function openEvidence() {
    const s = scenarios[active];
    $('dialog-intro').textContent = s.style === 'review' ? 'Two different weights appear in the same SI. SDOC surfaces the conflict instead of selecting a value without confirmation.' : s.style === 'verified' ? 'The values and source snippets match in this illustrative verification example.' : 'Compare the original field evidence from the Shipping Instruction and draft Bill of Lading.';
    const docs = $('dialog-docs'); docs.replaceChildren();
    s.docs.forEach(doc => {
      const item = el('article','dialog-doc');
      item.append(el('span','',doc.label),el('strong','',doc.value),el('p','',doc.file),el('blockquote','',doc.quote));
      docs.append(item);
    });
    if (typeof dialog.showModal === 'function') dialog.showModal();
  }
  $('demo-action').addEventListener('click',openEvidence);
  $('close-dialog').addEventListener('click',() => dialog.close());
  $('dialog-done').addEventListener('click',() => dialog.close());
  dialog.addEventListener('click',e => {if (e.target === dialog) dialog.close()});
  const toggle = document.querySelector('.menu-toggle');
  const menu = $('mobile-nav');
  toggle.addEventListener('click',() => {
    const open = menu.hasAttribute('hidden');
    menu.toggleAttribute('hidden',!open);
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open ? 'Close menu' : 'Open menu');
    toggle.querySelector('use').setAttribute('href',open ? '#i-x' : '#i-menu');
  });
  menu.querySelectorAll('a').forEach(link => link.addEventListener('click',() => {
    menu.hidden = true; toggle.setAttribute('aria-expanded','false'); toggle.setAttribute('aria-label','Open menu');
    toggle.querySelector('use').setAttribute('href','#i-menu');
  }));
  const revealItems = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) {entry.target.classList.add('is-visible');observer.unobserve(entry.target)}
    }),{threshold:.12,rootMargin:'0px 0px 18px 0px'});
    revealItems.forEach(item => observer.observe(item));
  } else revealItems.forEach(item => item.classList.add('is-visible'));
  // Batch pointer updates into one frame; reset when motion preferences change.
  const stack = $('stack-3d');
  const hero = document.querySelector('.hero');
  const heroMotion = window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
  // Letters split so each can follow the pointer; the heading still reads as one phrase.
  const mark = hero?.querySelector('h1 .mark');
  let markChars = [];
  if (mark) {
    const text = mark.textContent;
    const title = mark.closest('h1');
    title.setAttribute('aria-label', title.textContent.replace(/\s+/g, ' ').trim());
    markChars = [...text].map(char => {
      const span = document.createElement('span');
      span.className = 'mark-char';
      span.setAttribute('aria-hidden', 'true');
      span.textContent = char === ' ' ? '\u00a0' : char;
      return span;
    });
    mark.replaceChildren(...markChars);
  }
  if (stack && hero) {
    let frame = 0;
    const resetHero = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      hero.classList.remove('is-exploring');
      markChars.forEach(char => char.style.removeProperty('--lift'));
      stack.style.removeProperty('--rx');
      stack.style.removeProperty('--ry');
    };
    hero.addEventListener('pointermove', e => {
      if (!heroMotion.matches || e.pointerType === 'touch') return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = 0;
        const box = hero.getBoundingClientRect();
        hero.classList.add('is-exploring');
        stack.style.setProperty('--rx', `${((e.clientX - box.left) / box.width - .5) * 8}deg`);
        stack.style.setProperty('--ry', `${((e.clientY - box.top) / box.height - .5) * -6}deg`);
        if (mark) {
          // Lift the letters nearest the pointer, easing off with distance, so
          // the lift follows the cursor along the phrase. Layout offsets ignore
          // transforms, so a lifted letter never shifts its own measurement.
          const r = mark.getBoundingClientRect();
          const dy = Math.max(r.top - e.clientY, 0, e.clientY - r.bottom);
          const reach = Math.max(0, 1 - dy / 110);
          markChars.forEach(char => {
            const dx = e.clientX - (r.left + char.offsetLeft + char.offsetWidth / 2);
            const lift = reach * Math.exp(-(dx * dx) / (2 * 55 * 55));
            char.style.setProperty('--lift', lift.toFixed(3));
          });
        }
      });
    });
    hero.addEventListener('pointerleave', resetHero);
    hero.addEventListener('pointercancel', resetHero);
    heroMotion.addEventListener('change', resetHero);
    window.addEventListener('blur', resetHero);
  }
  setScenario(active);
})();
