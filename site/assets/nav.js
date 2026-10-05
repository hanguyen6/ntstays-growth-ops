// Site header: the Menu button (small screens) and the Housing / For Owners dropdowns (click, or hover on desktop).
// Choosing a link, clicking elsewhere or pressing Escape closes what's open.
(() => {
  const btn = document.querySelector('.nav-toggle'), menu = document.getElementById('site-menu');
  if (!btn || !menu) return;
  const toggles = [...menu.querySelectorAll('.sub-toggle')];
  const setSub = (t, open) => { t.setAttribute('aria-expanded', String(open)); document.getElementById(t.getAttribute('aria-controls')).classList.toggle('open', open); };
  const closeSubs = except => toggles.forEach(t => t !== except && setSub(t, false));
  const setMenu = open => { menu.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open)); if (!open) closeSubs(); };
  btn.addEventListener('click', () => setMenu(!menu.classList.contains('open')));
  toggles.forEach(t => t.addEventListener('click', () => { closeSubs(t); setSub(t, t.getAttribute('aria-expanded') !== 'true'); }));
  menu.addEventListener('click', e => { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('click', e => { if (!e.target.closest('.has-sub')) closeSubs(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const open = toggles.find(t => t.getAttribute('aria-expanded') === 'true');
    if (open) { setSub(open, false); open.focus(); } else if (menu.classList.contains('open')) { setMenu(false); btn.focus(); }
  });
})();
