// Spam protection (Cloudflare Turnstile). Adds an invisible "are you human" check to every form marked
// data-turnstile; it only shows a checkbox if something looks suspicious. The form's token goes to our server,
// which verifies it with Cloudflare before anything reaches the CRM, the AI or our inbox.
// Set SITE_KEY to the public site key from Cloudflare (Turnstile > Add widget). Empty = no check on the site
// (and leave TURNSTILE_SECRET empty on the server too, or every form will be refused).
(() => {
  const SITE_KEY = '0x4AAAAAAFFvf2Gh4DUKs8Pj';
  window.ntTurnstile = {
    siteKey: SITE_KEY,  // also used by the chat assistant (assets/chat.js)
    // The one-time token of a form ('' when the check is off or not finished yet).
    token: form => (form.querySelector('[name="cf-turnstile-response"]') || {}).value || '',
    // Tokens are single-use: get a fresh one after each submit.
    reset: form => { const w = form.querySelector('.cf-turnstile'); if (w && window.turnstile) window.turnstile.reset(w); },
  };
  if (!SITE_KEY) return;
  document.querySelectorAll('form[data-turnstile]').forEach(form => {
    const box = document.createElement('div');
    box.className = 'cf-turnstile';
    box.dataset.sitekey = SITE_KEY;
    box.dataset.appearance = 'interaction-only';  // invisible unless Cloudflare needs a click
    box.dataset.size = 'flexible';
    box.style.margin = '0 0 12px';
    const submit = form.querySelector('[type="submit"]');
    (submit ? submit.parentNode : form).insertBefore(box, submit || null);
  });
  const s = document.createElement('script');
  s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
  s.async = true; s.defer = true;
  document.head.append(s);
})();
