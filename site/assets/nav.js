// Site header: the Menu button on small screens opens and closes the link list; choosing a link or pressing
// Escape closes it again.
(() => {
  const btn = document.querySelector('.nav-toggle'), menu = document.getElementById('site-menu');
  if (!btn || !menu) return;
  const set = open => { menu.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open)); };
  btn.addEventListener('click', () => set(!menu.classList.contains('open')));
  menu.addEventListener('click', e => { if (e.target.closest('a')) set(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menu.classList.contains('open')) { set(false); btn.focus(); } });
})();
