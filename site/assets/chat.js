// NTStays website assistant: an "Ask us" chat bubble. Talks to the n8n "website assistant" workflow, which answers
// with AI from our facts and live availability, and passes requests to our team when the visitor agrees.
// The first message of a chat carries the Turnstile spam-check token; the server then signs the session.
(() => {
  const CHAT_URL = 'https://n8n.ntstays.com/webhook/ntstays-chat';
  const SITE_KEY = window.ntTurnstile && window.ntTurnstile.siteKey || '';
  const STORE = 'ntstays-chat';
  const SUGGESTIONS = ['Is the Cranston house free in November?', 'Do you work with insurance companies?',
    'Which home is closest to South Shore Hospital?'];
  let state = { messages: [], session: '', sig: '' };
  try { state = { ...state, ...JSON.parse(sessionStorage.getItem(STORE) || '{}') }; } catch (_) {}
  const save = () => { try { sessionStorage.setItem(STORE, JSON.stringify(state)); } catch (_) {} };
  // A signed chat lasts 4 hours (the number after the dot is its expiry). After that, keep the conversation but
  // drop the session, so the next message passes the spam check again and gets a new one.
  const dropExpired = () => {
    if (state.session && Number(state.session.split('.')[1] || 0) * 1000 < Date.now() + 60000) { state.session = ''; state.sig = ''; }
  };
  dropExpired();
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const css = document.createElement('style');
  css.textContent = `
    .ntc-btn { position: fixed; right: 18px; bottom: 18px; z-index: 50; border: 0; border-radius: 999px; padding: 13px 18px;
      background: #3b2a20; color: #fffdf8; font: 700 .95rem Karla, system-ui, sans-serif; cursor: pointer;
      box-shadow: 0 8px 24px rgba(59,42,32,.28); display: flex; align-items: center; gap: 8px; }
    .ntc-btn svg { width: 18px; height: 18px; stroke: currentColor; }
    .ntc-panel { position: fixed; right: 18px; bottom: 18px; z-index: 51; width: min(380px, calc(100vw - 24px));
      height: min(560px, calc(100vh - 36px)); background: #fffdf8; border: 1px solid #e4dbcc; border-radius: 16px;
      box-shadow: 0 16px 40px rgba(59,42,32,.25); display: none; flex-direction: column; overflow: hidden;
      font: 15px/1.5 Karla, system-ui, sans-serif; color: #2b211b; }
    .ntc-panel.open { display: flex; }
    .ntc-head { background: #3b2a20; color: #fffdf8; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; }
    .ntc-head b { font: 650 1.05rem Fraunces, Georgia, serif; }
    .ntc-head small { display: block; color: #e7dccd; font-size: .78rem; }
    .ntc-close { background: transparent; border: 0; color: #fffdf8; font-size: 1.4rem; cursor: pointer; line-height: 1; padding: 4px 8px; }
    .ntc-log { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 8px; background: #f6f1e7; }
    .ntc-msg { max-width: 85%; padding: 9px 12px; border-radius: 14px; white-space: pre-wrap; word-wrap: break-word; }
    .ntc-msg.bot { background: #fffdf8; border: 1px solid #e4dbcc; align-self: flex-start; border-bottom-left-radius: 4px; }
    .ntc-msg.me { background: #3b2a20; color: #fffdf8; align-self: flex-end; border-bottom-right-radius: 4px; }
    .ntc-msg.note { align-self: center; background: #e3e9df; color: #33452e; font-size: .85rem; text-align: center; }
    .ntc-typing { color: #6d6158; font-size: .85rem; padding-left: 4px; }
    .ntc-sugg { display: flex; flex-wrap: wrap; gap: 6px; }
    .ntc-sugg button { border: 1px solid #e4dbcc; background: #fffdf8; color: #5a4232; border-radius: 999px; padding: 6px 10px;
      font: 500 .85rem Karla, sans-serif; cursor: pointer; text-align: left; }
    .ntc-form { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #e4dbcc; background: #fffdf8; }
    .ntc-form textarea { flex: 1; resize: none; border: 1px solid #e4dbcc; border-radius: 10px; padding: 9px 10px;
      font: 15px Karla, sans-serif; color: #2b211b; max-height: 110px; }
    .ntc-form textarea:focus { outline: 2px solid #b08a3e; border-color: #b08a3e; }
    .ntc-form button { border: 0; border-radius: 10px; background: #3b2a20; color: #fffdf8; padding: 0 14px; font: 700 .9rem Karla, sans-serif; cursor: pointer; }
    .ntc-form button:disabled { opacity: .5; cursor: default; }
    .ntc-fine { font-size: .72rem; color: #6d6158; padding: 0 12px 8px; background: #fffdf8; }
    .ntc-ts { background: #fffdf8; padding: 0 10px; }
    .ntc-ts:empty { display: none; }
    .ntc-ts-note { font-size: .8rem; color: #5a4232; padding: 8px 0 4px; }
    @media (max-width: 480px) { .ntc-panel { right: 0; bottom: 0; width: 100vw; height: 100vh; border-radius: 0; } }`;
  document.head.append(css);

  const btn = document.createElement('button');
  btn.className = 'ntc-btn';
  btn.setAttribute('aria-label', 'Open chat: ask us a question');
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Ask us';
  const panel = document.createElement('section');
  panel.className = 'ntc-panel';
  panel.setAttribute('aria-label', 'Chat with the NTStays assistant');
  panel.innerHTML = `
    <div class="ntc-head"><div><b>NTStays assistant</b><small>AI assistant &middot; usually instant</small></div>
      <button class="ntc-close" aria-label="Close chat">&times;</button></div>
    <div class="ntc-log" role="log" aria-live="polite"></div>
    <div class="ntc-ts" aria-live="polite"></div>
    <form class="ntc-form"><textarea rows="1" maxlength="1000" placeholder="Ask about homes, dates, or working with us" aria-label="Your message"></textarea>
      <button type="submit">Send</button></form>
    <div class="ntc-fine">AI answers can be wrong; we confirm bookings and prices by email. Don't share payment details here.
      <a href="privacy.html" style="color:#6d6158">Privacy</a></div>`;
  document.body.append(btn, panel);
  const log = panel.querySelector('.ntc-log'), form = panel.querySelector('form'), input = panel.querySelector('textarea');
  const send = form.querySelector('button');

  function bubble(role, text) {
    const div = document.createElement('div');
    div.className = 'ntc-msg ' + (role === 'user' ? 'me' : role === 'note' ? 'note' : 'bot');
    div.textContent = text;
    log.append(div);
    log.scrollTop = log.scrollHeight;
  }
  function render() {
    log.innerHTML = '';
    bubble('assistant', 'Hi! I\'m the NTStays assistant. Ask me about our homes in Framingham, Cranston and Abington, dates, or working with us.');
    state.messages.forEach(m => bubble(m.role, m.content));
    if (!state.messages.length) {
      const s = document.createElement('div');
      s.className = 'ntc-sugg';
      s.innerHTML = SUGGESTIONS.map(q => `<button type="button">${esc(q)}</button>`).join('');
      s.addEventListener('click', e => { const b = e.target.closest('button'); if (b) { input.value = b.textContent; form.requestSubmit(); } });
      log.append(s);
    }
  }

  // Spam check for the first message of a chat. Invisible unless Cloudflare wants a click; then its box shows up
  // above the typing box (it has to be visible and clickable, as on the request forms).
  let tsToken = '', tsWidget = null, tsError = '';
  const tsBox = panel.querySelector('.ntc-ts');
  function startTurnstile() {
    if (!SITE_KEY || state.session || tsWidget !== null || !window.turnstile) return;
    tsWidget = window.turnstile.render(tsBox, { sitekey: SITE_KEY, appearance: 'interaction-only', size: 'flexible',
      callback: t => { tsToken = t; tsError = ''; tsBox.querySelector('.ntc-ts-note')?.remove(); },
      'expired-callback': () => { tsToken = ''; },
      'before-interactive-callback': () => {
        if (!tsBox.querySelector('.ntc-ts-note'))
          tsBox.insertAdjacentHTML('afterbegin', '<div class="ntc-ts-note">Quick check that you&rsquo;re human, then press Send:</div>');
      },
      'error-callback': code => { tsError = String(code || 'error'); console.warn('Turnstile error', tsError); } });
  }
  // Waits up to 30 s for the token (answering Cloudflare's box, if it asks, counts). '' = no check needed.
  const waitForToken = async () => {
    if (!SITE_KEY || state.session) return '';
    for (let i = 0; i < 120 && !tsToken && !tsError; i++) { startTurnstile(); await new Promise(r => setTimeout(r, 250)); }
    if (tsToken) return tsToken;
    throw new Error(tsError ? `Our spam check couldn't run (code ${tsError}). Please reload the page, or email hello@ntstays.com.`
      : tsBox.querySelector('.ntc-ts-note') ? 'Please answer the quick check above the typing box, then press Send.'
      : 'Our spam check is still loading. Please press Send again in a moment.');
  };

  function open() {
    panel.classList.add('open'); btn.style.display = 'none';
    render(); startTurnstile();
    setTimeout(() => input.focus(), 50);
  }
  function close() { panel.classList.remove('open'); btn.style.display = ''; btn.focus(); }
  btn.addEventListener('click', open);
  panel.querySelector('.ntc-close').addEventListener('click', close);
  panel.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    log.querySelector('.ntc-sugg')?.remove();
    state.messages.push({ role: 'user', content: text.slice(0, 1000) });
    bubble('user', text);
    input.value = '';
    send.disabled = true;
    const typing = document.createElement('div');
    typing.className = 'ntc-typing'; typing.textContent = 'Typing…';
    log.append(typing); log.scrollTop = log.scrollHeight;
    let tokenSent = false;
    dropExpired();
    try {
      const turnstile = await waitForToken();
      tokenSent = Boolean(turnstile);
      const res = await fetch(CHAT_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: state.messages.slice(-12), session: state.session, sig: state.sig, turnstile,
          source: window.ntSource ? window.ntSource.get() : null }) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || 'Sorry, something went wrong. Please email hello@ntstays.com.');
      state.session = body.session || state.session; state.sig = body.sig || state.sig;
      // The spam check is only for a chat's first message: once the chat is signed, take the box away.
      if (state.session && tsWidget !== null && window.turnstile) {
        window.turnstile.remove(tsWidget); tsWidget = null; tsToken = ''; tsBox.replaceChildren();
      }
      state.messages.push({ role: 'assistant', content: body.reply });
      typing.remove();
      bubble('assistant', body.reply);
      if (body.handed_off && !state.sent) { state.sent = true; bubble('note', 'Sent to our team. We\'ll reply by email within one business day.'); }
    } catch (err) {
      typing.remove();
      state.messages.pop();  // let them try again
      bubble('note', err.message || 'Sorry, something went wrong. Please email hello@ntstays.com.');
      if (/reload the page to start/i.test(err.message || '')) { state = { messages: [], session: '', sig: '' }; }
      // The server didn't accept our session (e.g. it expired): the next Send runs the spam check again.
      else if (/spam check/i.test(err.message || '') && state.session) { state.session = ''; state.sig = ''; startTurnstile(); }
    } finally {
      save();
      send.disabled = false;
      if (tsWidget !== null && window.turnstile && !state.session && (tokenSent || tsError)) {
        window.turnstile.reset(tsWidget); tsToken = ''; tsError = '';
      }
      input.focus();
    }
  });
})();
