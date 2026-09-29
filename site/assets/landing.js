// Request form for the monthly-stay landing pages. Posts to the same n8n webhook as the homepage form, as a
// "stay" inquiry with a guest type (segment), so it lands in the usual review email.
const WEBHOOK_URL = 'https://n8n.ntstays.com/webhook/ntstays-inquiry';
const CONTACT_EMAIL = 'hello@ntstays.com';
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

document.getElementById('year').textContent = new Date().getFullYear();

// "Request this home" buttons pick the home in the form.
document.addEventListener('click', e => {
  const b = e.target.closest('[data-home]');
  if (!b) return;
  const sel = document.querySelector('#request-form [name="property_id"]');
  if (sel) sel.value = b.dataset.home;
});

const form = document.getElementById('request-form');
if (form) form.addEventListener('submit', async e => {
  e.preventDefault();
  const st = document.getElementById('request-status'), btn = form.querySelector('button[type="submit"]');
  const d = Object.fromEntries(new FormData(form));
  const show = (kind, msg) => { st.className = 'status ' + kind; st.textContent = msg; };
  if (!d.first_name?.trim() || !EMAIL_RE.test(d.email || '')) return show('err', 'Please add your first name and a valid email.');
  if (d.check_in && d.check_out && d.check_out <= d.check_in) return show('err', 'Please check the dates: move-out is before move-in.');
  // Extra details (hospital, claim, role) go at the top of the message, so they reach the review email as-is.
  const extras = [...form.querySelectorAll('[data-extra]')].map(el => el.value.trim() ? `${el.dataset.extra}: ${el.value.trim()}` : '').filter(Boolean);
  const message = [extras.join('\n'), (d.message || '').trim()].filter(Boolean).join('\n\n') || 'Please let me know about availability.';
  const payload = { form_type: 'inquiry', inquiry_type: 'stay', segment: form.dataset.segment, first_name: d.first_name, last_name: d.last_name,
    email: d.email, phone: d.phone, property_id: d.property_id, check_in: d.check_in, check_out: d.check_out, guests: d.guests,
    message, website: d.website, marketing_opt_in: false, heard_about: d.heard_about,
    source: window.ntSource ? window.ntSource.get() : null,
    turnstile: window.ntTurnstile ? window.ntTurnstile.token(form) : '', page: location.href, submitted_at: new Date().toISOString() };
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const res = await fetch(WEBHOOK_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    let body = {};
    try { body = await res.json(); } catch (_) {}
    if (!res.ok) throw Object.assign(new Error('request failed'), { body });
    show('ok', `Thanks, ${d.first_name.trim()}! We'll check the dates and reply to ${d.email} within one business day.`);
    form.reset();
  } catch (err) {
    const why = err.body?.errors?.join(', ');
    show('err', why ? `Please check: ${why}.` : `Sorry, something went wrong. Please email us at ${CONTACT_EMAIL}.`);
  } finally {
    btn.disabled = false; btn.textContent = form.dataset.button || 'Send request';
    if (window.ntTurnstile) window.ntTurnstile.reset(form);
  }
});
