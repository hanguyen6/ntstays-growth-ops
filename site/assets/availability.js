// Availability from our calendars (Airbnb, Vrbo, Booking.com), synced by the n8n "availability" workflow.
// - Any element with data-availability="home-2" (and data-name) opens a two-month calendar.
// - Forms with data-avail-form get a note when the chosen dates look booked or open.
// Only booked date ranges are published; if the calendar can't load, everything here stays hidden.
(() => {
  const AVAIL_URL = 'https://n8n.ntstays.com/webhook/ntstays-availability';
  const DAY = 86400000;
  let data = null;
  const load = () => data || (data = fetch(AVAIL_URL).then(r => (r.ok ? r.json() : null)).catch(() => null));
  const utc = s => Date.parse(s + 'T00:00:00Z');
  const busyDays = (st, home) => (st?.homes?.[home] || []).map(([a, b]) => [utc(a), utc(b)]);
  const isBusyDay = (ranges, t) => ranges.some(([a, b]) => t >= a && t < b);
  const overlaps = (ranges, ci, co) => ranges.some(([a, b]) => ci < b && co > a);

  const css = document.createElement('style');
  css.textContent = `
    dialog.avail { border: 0; border-radius: 14px; padding: 20px; width: min(720px, calc(100vw - 24px)); background: #fffdf8; color: #2b211b; }
    dialog.avail::backdrop { background: rgba(43, 33, 27, .6); }
    .avail h3 { margin: 0 0 4px; font: 650 1.25rem Fraunces, Georgia, serif; color: #3b2a20; }
    .avail .sub { margin: 0 0 14px; color: #6d6158; font-size: .9rem; }
    .avail .months { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    @media (max-width: 600px) { .avail .months { grid-template-columns: 1fr; } .avail .m2 { display: none; } }
    .avail .mhead { display: flex; justify-content: space-between; align-items: center; min-height: 32px; margin-bottom: 6px; font-weight: 700; color: #3b2a20; }
    .avail .nav button { border: 1px solid #e4dbcc; background: #f6f1e7; border-radius: 999px; width: 30px; height: 30px; cursor: pointer; font-size: 1rem; color: #3b2a20; }
    .avail .nav button:disabled { opacity: .35; cursor: default; }
    .avail .grid7 { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; font-size: .82rem; text-align: center; }
    .avail .dow { color: #6d6158; font-size: .72rem; padding: 2px 0; }
    .avail .d { padding: 6px 0; border-radius: 6px; background: #e3e9df; color: #33452e; }
    .avail .d.busy { background: #ece5d8; color: #a89d90; text-decoration: line-through; }
    .avail .d.past { background: transparent; color: #cfc6b8; text-decoration: none; }
    .avail .d.blank { background: transparent; }
    .avail .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; font-size: .82rem; color: #6d6158; }
    .avail .legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
    .avail .note { font-size: .85rem; color: #6d6158; margin: 12px 0 0; }
    .avail .actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; flex-wrap: wrap; }
    .avail .actions button { border: 0; border-radius: 999px; padding: 10px 18px; font: 700 .92rem Karla, sans-serif; cursor: pointer; }
    .avail .primary { background: #3b2a20; color: #fffdf8; }
    .avail .ghost { background: transparent; color: #3b2a20; box-shadow: inset 0 0 0 1.5px #3b2a20; }
    .avail-note { font-size: .9rem; border-radius: 10px; padding: 9px 12px; margin: -4px 0 14px; display: none; }
    .avail-note.open { display: block; background: #e3e9df; color: #33452e; }
    .avail-note.busy { display: block; background: #fbeed3; color: #5a4232; }`;
  document.head.append(css);

  const dlg = document.createElement('dialog');
  dlg.className = 'avail';
  document.body.append(dlg);
  let state = null;  // { home, name, ranges, offset }

  function month(y, m, ranges) {
    const first = new Date(Date.UTC(y, m, 1)), days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const today = Date.UTC(new Date().getFullYear(), new Date().getMonth(), new Date().getDate());
    const lead = (first.getUTCDay() + 6) % 7;  // weeks start on Monday
    let cells = 'MTWTFSS'.split('').map(d => `<div class="dow">${d}</div>`).join('') + '<div class="d blank"></div>'.repeat(lead);
    for (let i = 1; i <= days; i++) {
      const t = Date.UTC(y, m, i);
      const cls = t < today ? 'past' : isBusyDay(ranges, t) ? 'busy' : '';
      cells += `<div class="d ${cls}" aria-label="${new Date(t).toDateString()}${cls === 'busy' ? ', booked' : ''}">${i}</div>`;
    }
    return `<div class="grid7">${cells}</div>`;
  }
  function render() {
    const now = new Date(), base = new Date(Date.UTC(now.getFullYear(), now.getMonth() + state.offset, 1));
    const m2 = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 1));
    const label = d => d.toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
    dlg.innerHTML = `
      <h3>${state.name}: availability</h3>
      <p class="sub">Updated from our Airbnb, Vrbo and Booking.com calendars.</p>
      <div class="months">
        <div><div class="mhead"><span>${label(base)}</span><span class="nav">
          <button data-step="-1" aria-label="Earlier months" ${state.offset <= 0 ? 'disabled' : ''}>&#8249;</button>
          <button data-step="1" aria-label="Later months" ${state.offset >= 16 ? 'disabled' : ''}>&#8250;</button></span></div>
          ${month(base.getUTCFullYear(), base.getUTCMonth(), state.ranges)}</div>
        <div class="m2"><div class="mhead"><span>${label(m2)}</span></div>${month(m2.getUTCFullYear(), m2.getUTCMonth(), state.ranges)}</div>
      </div>
      <div class="legend"><span><i style="background:#e3e9df"></i>Open</span><span><i style="background:#ece5d8"></i>Booked or unavailable</span></div>
      <p class="note">For monthly stays, ask us even if some dates look booked: we're flexible and may have options.</p>
      <div class="actions"><button class="ghost" data-close>Close</button><button class="primary" data-request>Request dates</button></div>`;
  }
  dlg.addEventListener('click', e => {
    const step = e.target.closest('[data-step]');
    if (step) { state.offset += +step.dataset.step; render(); return; }
    if (e.target.closest('[data-close]') || e.target === dlg) { dlg.close(); return; }
    if (e.target.closest('[data-request]')) {
      dlg.close();
      const form = document.querySelector('[data-avail-form]');
      if (!form) return;
      const type = form.querySelector('[name="inquiry_type"]');
      if (type) { type.value = 'stay'; type.dispatchEvent(new Event('change', { bubbles: true })); }
      const sel = form.querySelector('[name="property_id"]');
      if (sel && [...sel.options].some(o => o.value === state.home)) sel.value = state.home;
      form.scrollIntoView({ behavior: 'smooth' });
      setTimeout(() => form.querySelector('[name="check_in"]')?.focus({ preventScroll: true }), 500);
    }
  });

  // Show the availability buttons only once the calendar has loaded.
  load().then(st => {
    if (!st || !st.homes) return;
    document.querySelectorAll('[data-availability]').forEach(b => { if (st.homes[b.dataset.availability]) b.hidden = false; });
  });
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-availability]');
    if (!b) return;
    e.preventDefault();
    const st = await load();
    if (!st) return;
    state = { home: b.dataset.availability, name: b.dataset.name || 'This home', ranges: busyDays(st, b.dataset.availability), offset: 0 };
    render();
    dlg.showModal();
  });

  // Date check on request forms.
  document.querySelectorAll('[data-avail-form]').forEach(form => {
    const note = document.createElement('div');
    note.className = 'avail-note';
    note.setAttribute('role', 'status');
    const out = form.querySelector('[name="check_out"]');
    (out?.closest('.row') || out?.closest('label') || form.firstElementChild).after(note);
    const update = async () => {
      const home = form.querySelector('[name="property_id"]')?.value, ci = form.check_in?.value, co = form.check_out?.value;
      const type = form.querySelector('[name="inquiry_type"]')?.value;
      note.className = 'avail-note';
      if (!ci || !co || co <= ci || (type && type !== 'stay')) return;
      const st = await load();
      if (!st) return;
      const homes = home && home !== 'any' && home !== 'several' ? [home] : Object.keys(st.homes);
      const withData = homes.filter(h => st.homes[h]);
      if (!withData.length) return;
      const open = withData.filter(h => !overlaps(busyDays(st, h), utc(ci), utc(co)));
      if (open.length === withData.length) {
        note.className = 'avail-note open';
        note.textContent = 'Good news: those dates look open. Send your request and we\'ll confirm.';
      } else {
        note.className = 'avail-note busy';
        note.textContent = withData.length > 1 && open.length
          ? 'Some of our homes look booked on those dates, but not all. Send your request and we\'ll suggest the best fit.'
          : 'Those dates look booked on our calendar. Send your request anyway: we\'re flexible and may have options.';
      }
    };
    form.addEventListener('change', e => { if (['check_in', 'check_out', 'property_id', 'inquiry_type'].includes(e.target.name)) update(); });
    form.addEventListener('reset', () => { note.className = 'avail-note'; });
  });
})();
