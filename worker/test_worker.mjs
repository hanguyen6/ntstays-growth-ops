// Tests the sign-in guard for /team/* without Cloudflare:  node worker/test_worker.mjs
// Makes its own RSA key pair, signs tokens the way Cloudflare Access does, and serves the matching public key.
import worker from './index.js';

let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };

const TEAM = 'ntstays.cloudflareaccess.com', AUD = 'aud-tag-123';
const { privateKey, publicKey } = await crypto.subtle.generateKey(
  { name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await crypto.subtle.exportKey('jwk', publicKey)), kid: 'k1', alg: 'RS256', use: 'sig' };
let certFetches = 0;
const n8nCalls = [];
globalThis.fetch = async (url, opts = {}) => {
  if (url === 'https://n8n.example/webhook/ntstays-team') {
    n8nCalls.push({ method: opts.method, headers: opts.headers, body: opts.body });
    return new Response(JSON.stringify({ ok: true, id: 5 }), { status: 200 });
  }
  certFetches++;
  if (url !== `https://${TEAM}/cdn-cgi/access/certs`) return new Response('nope', { status: 404 });
  return new Response(JSON.stringify({ keys: [jwk] }), { headers: { 'content-type': 'application/json' } });
};
const b64 = x => Buffer.from(typeof x === 'string' ? x : new Uint8Array(x)).toString('base64url');
async function token(claims = {}, kid = 'k1') {
  const head = b64(JSON.stringify({ alg: 'RS256', kid, typ: 'JWT' }));
  const body = b64(JSON.stringify({ iss: `https://${TEAM}`, aud: [AUD], exp: Math.floor(Date.now() / 1000) + 3600, email: 'mm@example.com', ...claims }));
  const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', privateKey, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64(sig)}`;
}
const ASSETS = { fetch: async req => new Response('asset ' + new URL(req.url).pathname, { headers: { 'cache-control': 'public, max-age=3600' } }) };
const ENV = { ASSETS, ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD };
const get = async (path, tok, env = ENV) => worker.fetch(new Request('https://ntstays.com' + path,
  { headers: tok ? { 'cf-access-jwt-assertion': tok } : {} }), env);

let r = await get('/travel-nurses');
check('public pages are served as before, no sign-in', r.status === 200 && (await r.text()) === 'asset /travel-nurses');
r = await get('/teamwork');
check('only /team itself is private, not look-alike paths', r.status === 200);
r = await get('/team/marketing', await token(), { ASSETS });
check('refused for everyone until Access is configured', r.status === 403);
r = await get('/team/marketing');
check('refused without a sign-in token', r.status === 403);
r = await get('/team/marketing', await token());
check('served with a valid Access sign-in, never cached publicly', r.status === 200 && (await r.text()) === 'asset /team/marketing'
  && r.headers.get('cache-control') === 'private, no-store' && r.headers.get('x-robots-tag').includes('noindex'));
r = await get('/team/marketing-data.json', await token());
check('the data file is protected the same way', r.status === 200);
r = await get('/team/marketing-data.json');
check('the data file without sign-in is refused', r.status === 403);
check('expired token refused', (await get('/team/marketing', await token({ exp: Math.floor(Date.now() / 1000) - 10 }))).status === 403);
check('token for another application refused', (await get('/team/marketing', await token({ aud: ['other'] }))).status === 403);
check('token from another Access team refused', (await get('/team/marketing', await token({ iss: 'https://evil.cloudflareaccess.com' }))).status === 403);
check('unknown signing key refused', (await get('/team/marketing', await token({}, 'k2'))).status === 403);
const good = await token(), [h, , s] = good.split('.');
const forged = `${h}.${b64(JSON.stringify({ iss: `https://${TEAM}`, aud: [AUD], exp: 9999999999, email: 'x@evil.com' }))}.${s}`;
check('tampered token refused (signature check)', (await get('/team/marketing', forged)).status === 403);
check('garbage token refused', (await get('/team/marketing', 'not.a.token')).status === 403);
check('signing keys are cached', certFetches === 1, certFetches);

// The "Log numbers" page: entries go to n8n with the shared key and the signed-in email.
const API_ENV = { ...ENV, TEAM_API_KEY: 'k'.repeat(32), N8N_TEAM_URL: 'https://n8n.example/webhook/ntstays-team' };
const api = async (method, tok, body, env = API_ENV) => worker.fetch(new Request('https://ntstays.com/team/api/entries',
  { method, body, headers: { 'content-type': 'application/json', ...(tok ? { 'cf-access-jwt-assertion': tok } : {}) } }), env);
r = await api('POST', await token(), JSON.stringify({ kind: 'ff_stats', as_of: '2026-10-01', views: 12 }));
const call = n8nCalls.at(-1);
check('entry passed on to n8n with the key and who entered it', r.status === 200 && call.method === 'POST'
  && call.headers['x-ntstays-key'] === 'k'.repeat(32) && call.headers['x-ntstays-user'] === 'mm@example.com'
  && JSON.parse(call.body).views === 12, call);
await worker.fetch(new Request('https://ntstays.com/team/api/entries', { method: 'POST', body: '{}',
  headers: { 'cf-access-jwt-assertion': await token(), 'x-ntstays-user': 'boss@evil.com', 'x-ntstays-key': 'guess' } }), API_ENV);
check("a visitor can't choose who they are or the key", n8nCalls.at(-1).headers['x-ntstays-user'] === 'mm@example.com'
  && n8nCalls.at(-1).headers['x-ntstays-key'] === 'k'.repeat(32), n8nCalls.at(-1).headers);
r = await api('GET', await token());
check('entries can be read (for the dashboard)', r.status === 200 && n8nCalls.at(-1).method === 'GET' && !n8nCalls.at(-1).body);
const before = n8nCalls.length;
r = await api('POST', null, '{}');
check('no sign-in, nothing reaches n8n', r.status === 403 && n8nCalls.length === before);
r = await api('POST', await token(), '{}', ENV);
check('says so when the key is not set up yet', r.status === 503 && (await r.json()).errors[0].includes('not set up'));
r = await api('DELETE', await token());
check('only GET and POST', r.status === 405);
r = await api('POST', await token(), 'x'.repeat(20001));
check('oversized entries refused', r.status === 413 && n8nCalls.length === before + 0);

// Who may open what (TEAM_LOG_EMAILS, TEAM_DASHBOARD_EMAILS)
const ROLE_ENV = { ...API_ENV, TEAM_LOG_EMAILS: 'mm@example.com, owner@example.com', TEAM_DASHBOARD_EMAILS: '@example.com' };
const as = async (path, email, method = 'GET', body) => worker.fetch(new Request('https://ntstays.com' + path,
  { method, body, headers: { 'cf-access-jwt-assertion': await token({ email }), 'content-type': 'application/json' } }), ROLE_ENV);
check('no lists set: everyone signed in may open both pages', (await get('/team/log', await token())).status === 200
  && (await get('/team/marketing', await token())).status === 200);
check('a logger opens Log numbers and saves entries', (await as('/team/log', 'mm@example.com')).status === 200
  && (await as('/team/api/entries', 'mm@example.com', 'POST', '{}')).status === 200);
check('a dashboard-only viewer opens the dashboard and reads entries, but not Log numbers or saving',
  (await as('/team/marketing', 'viewer@example.com')).status === 200 && (await as('/team/marketing-data.json', 'viewer@example.com')).status === 200
  && (await as('/team/api/entries', 'viewer@example.com')).status === 200
  && (await as('/team/log', 'viewer@example.com')).status === 403 && (await as('/team/log.html', 'viewer@example.com')).status === 403
  && (await as('/team/api/entries', 'viewer@example.com', 'POST', '{}')).status === 403);
r = await as('/team/marketing', 'someone@else.org');
check('someone on neither list gets a clear "no access" page', r.status === 403 && (await r.text()).includes('someone@else.org'));
check('the team home is open to everyone signed in', (await as('/team', 'someone@else.org')).status === 200);
r = await as('/team/api/me', 'viewer@example.com');
check('the team home can ask what this person may open', r.status === 200
  && JSON.stringify(await r.json()) === JSON.stringify({ email: 'viewer@example.com', roles: { log: false, dashboard: true } }));
check('emails compare without case', (await as('/team/log', 'MM@Example.com')).status === 200);

console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
