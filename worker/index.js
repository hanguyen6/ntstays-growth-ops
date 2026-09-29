// The website's Worker. Everything is served from ./site as before, except /team/*, the sign-in-only pages
// (the marketing manager's dashboard). Those are served only with a valid Cloudflare Access login: Access puts a
// signed token (JWT) on every request it lets through, and this checks its signature, audience and expiry.
// Until ACCESS_TEAM_DOMAIN and ACCESS_AUD are set in wrangler.jsonc, /team/* is refused for everyone, on every
// address (ntstays.com and the workers.dev address alike). Setup: SETUP.md, "Marketing dashboard (sign-in)".
// /team/api/entries is passed on to the n8n "team data" workflow (the "Log numbers" page), with the shared
// TEAM_API_KEY (a Worker secret) and the signed-in person's email.
// Who may open what: Cloudflare Access decides who can sign in at all; then two lists (Worker secrets, comma-separated
// emails, "@example.com" for a whole domain) split the pages. Empty list = everyone signed in.
//   TEAM_LOG_EMAILS        Log numbers page, and saving entries
//   TEAM_DASHBOARD_EMAILS  Marketing dashboard
// Reading entries is allowed for both (the dashboard and the log page's recent entries need it).

const PRIVATE = /^\/team(\/|$)/;

// The roles a signed-in email has. An empty list means the page is open to everyone signed in.
export function rolesFor(email, env) {
  const e = (email || '').trim().toLowerCase();
  const inList = raw => {
    const list = (raw || '').split(/[,\s]+/).map(x => x.trim().toLowerCase()).filter(Boolean);
    return !list.length || list.some(x => x.startsWith('@') ? e.endsWith(x) : x === e);
  };
  return { log: Boolean(e) && inList(env.TEAM_LOG_EMAILS), dashboard: Boolean(e) && inList(env.TEAM_DASHBOARD_EMAILS) };
}
// Which role a request needs ('' = any signed-in person).
function needs(path, method) {
  if (path === '/team/api/entries') return method === 'GET' ? 'log|dashboard' : 'log';
  if (/^\/team\/log(\.html)?$/.test(path)) return 'log';
  if (/^\/team\/marketing(\.html|-data\.json)?$/.test(path)) return 'dashboard';
  return '';
}
const noAccess = (email, what) => new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>No access</title><body style="font:16px system-ui;max-width:560px;margin:60px auto;padding:0 16px;color:#2b211b">
<h1 style="font:600 1.4rem Georgia,serif">No access to ${what}</h1>
<p>You're signed in as <b>${email.replace(/[<>&"]/g, '')}</b>, which doesn't have access to this page. Ask the owner to add you.</p>
<p><a href="/team">Team home</a></p></body>`, { status: 403, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
let certCache = { url: '', keys: null, at: 0 };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!PRIVATE.test(url.pathname)) return env.ASSETS.fetch(request);
    const login = await accessLogin(request, env);
    if (!login) {
      return new Response('Please sign in through ntstays.com/team/marketing.', {
        status: 403, headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' } });
    }
    const roles = rolesFor(login.email, env), need = needs(url.pathname, request.method);
    if (need && !need.split('|').some(r => roles[r])) {
      if (url.pathname.startsWith('/team/api/') || url.pathname.endsWith('.json')) {
        return new Response(JSON.stringify({ ok: false, errors: ['your account doesn\'t have access to this'] }),
          { status: 403, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
      }
      return noAccess(login.email || '', need === 'log' ? 'Log numbers' : 'the Marketing dashboard');
    }
    const res = url.pathname === '/team/api/me'
      ? new Response(JSON.stringify({ email: login.email || '', roles }), { headers: { 'content-type': 'application/json' } })
      : url.pathname === '/team/api/entries' ? await toTeamData(request, env, login)
      : await env.ASSETS.fetch(request);
    const headers = new Headers(res.headers);
    headers.set('cache-control', 'private, no-store');
    headers.set('x-robots-tag', 'noindex, nofollow');
    return new Response(res.body, { status: res.status, headers });
  },
};

// The "Log numbers" page and the dashboard read and write entries through here (GET and POST).
async function toTeamData(request, env, login) {
  const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  if (!env.TEAM_API_KEY || !env.N8N_TEAM_URL) return reply(503, { ok: false, errors: ['the Log numbers page is not set up yet'] });
  if (!['GET', 'POST'].includes(request.method)) return reply(405, { ok: false, errors: ['GET or POST only'] });
  const body = request.method === 'POST' ? await request.text() : undefined;
  if (body && body.length > 20000) return reply(413, { ok: false, errors: ['too much data'] });
  try {
    const res = await fetch(env.N8N_TEAM_URL, { method: request.method, body,
      headers: { 'content-type': 'application/json', 'x-ntstays-key': env.TEAM_API_KEY, 'x-ntstays-user': login.email || '' } });
    return new Response(await res.text(), { status: res.status, headers: { 'content-type': 'application/json' } });
  } catch {
    return reply(502, { ok: false, errors: ['the automation server did not answer; try again in a minute'] });
  }
}

const b64url = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4)), c => c.charCodeAt(0));
const json = s => JSON.parse(new TextDecoder().decode(b64url(s)));

// The signed-in person's token claims (email etc.) when the Access login is valid, else null.
export async function accessLogin(request, env, now = Date.now()) {
  return (await hasAccessLogin(request, env, now)) ? json(request.headers.get('cf-access-jwt-assertion').split('.')[1]) : null;
}

export async function hasAccessLogin(request, env, now = Date.now()) {
  const team = (env.ACCESS_TEAM_DOMAIN || '').trim(), aud = (env.ACCESS_AUD || '').trim();
  if (!team || !aud) return false;
  const token = request.headers.get('cf-access-jwt-assertion') || '';
  const parts = token.split('.');
  if (parts.length !== 3) return false;
  let header, claims;
  try { header = json(parts[0]); claims = json(parts[1]); } catch { return false; }
  if (header.alg !== 'RS256' || claims.iss !== `https://${team}`) return false;
  if (!(Array.isArray(claims.aud) ? claims.aud : [claims.aud]).includes(aud)) return false;
  if (!claims.exp || claims.exp * 1000 < now) return false;
  const jwk = (await accessKeys(team, now)).find(k => k.kid === header.kid);
  if (!jwk) return false;
  try {
    const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  } catch { return false; }
}

// Access's public signing keys, cached for an hour.
async function accessKeys(team, now) {
  const url = `https://${team}/cdn-cgi/access/certs`;
  if (certCache.url === url && certCache.keys && now - certCache.at < 3600e3) return certCache.keys;
  try {
    const res = await fetch(url);
    const keys = res.ok ? (await res.json()).keys || [] : [];
    if (keys.length) certCache = { url, keys, at: now };  // a failed fetch isn't remembered
    return keys;
  } catch { return []; }
}
