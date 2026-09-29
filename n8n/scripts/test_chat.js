// Tests the website assistant (workflow/ntstays-chat.json) without n8n, Docker, Claude or Cloudflare:
//   node scripts/test_chat.js
// Runs the workflow's own code with stand-ins for n8n's $input, $, $env and $getWorkflowStaticData.
const fs = require('fs');
const path = require('path');
const load = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', f), 'utf8'));
const wf = load('ntstays-chat.json'), inq = load('ntstays-inquiry.json');
const code = (w, name) => w.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const env = { CLAUDE_MODEL: 'claude-haiku-4-5', UNSUBSCRIBE_SECRET: 'k3y', TURNSTILE_SECRET: 's3' };
const store = {};
const read = (body, e = env) => new Function('$input', '$env', '$getWorkflowStaticData', code(wf, 'Read chat'))(
  { first: () => ({ json: { body } }) }, e, () => store)[0].json;
const sign = j => ({ ...j, sig: 'SIG:' + (j.session || '') });  // stand-in for the Crypto HMAC node
const session = (signed, human) => new Function('$input', '$', '$env', '$getWorkflowStaticData', code(wf, 'Check chat session'))(
  { first: () => ({ json: signed }) },
  name => name === 'Sign chat session' ? { first: () => ({ json: signed }) }
    : { isExecuted: human !== undefined, first: () => ({ json: { success: human } }) }, env, () => store)[0].json;

// Sessions and limits
let r = read({ messages: [{ role: 'user', content: 'Hi' }] });
check('new chat gets a session and needs the spam check', r.ok && r.is_new && r.check_human && /^[a-z0-9]{12}\.\d{10}$/.test(r.session), r);
check('new chat without passing the spam check is refused', session(sign(r), false).ok === false && session(sign(r)).ok === false);
let s = session(sign(r), true);
check('new chat that passes the spam check is allowed', s.ok === true && s.sig === 'SIG:' + r.session);
const r2 = read({ messages: [{ role: 'user', content: 'Hi' }, { role: 'assistant', content: 'Hello' }, { role: 'user', content: 'Dates?' }],
  session: r.session, sig: 'SIG:' + r.session });
check('returning chat with our signature: no second spam check', !r2.is_new && !r2.check_human && session(sign(r2)).ok === true);
check('forged signature is refused', session({ ...sign(r2), given_sig: 'fake' }).ok === false);
check('expired session starts a new one', read({ messages: [{ role: 'user', content: 'x' }], session: 'abcdefghijkl.1000000000', sig: 'x' }).is_new);
const long = read({ messages: Array.from({ length: 30 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: 'm' + i + 'x'.repeat(2000) })).concat([{ role: 'user', content: 'last' }]) });
check('only the last 12 messages, each capped at 1,000 characters, starting with the visitor', long.messages.length <= 12
  && long.messages.every(m => m.content.length <= 1000) && long.messages[0].role === 'user' && long.messages.at(-1).content === 'last', long.messages.length);
check('empty or assistant-last conversations are refused', read({ messages: [] }).ok === false
  && read({ messages: [{ role: 'user', content: 'a' }, { role: 'assistant', content: 'b' }] }).ok === false);
store.sessions[r.session].n = 30;
check('30 messages per chat', session(sign(r2)).ok === false);
store.count = 300;
check('daily limit across the site', read({ messages: [{ role: 'user', content: 'hi' }] }).ok === false);
store.count = 0; store.sessions[r.session].n = 1;

// The model request
const chat = { ...session(sign(r2)), messages: r2.messages };
const build = av => new Function('$input', '$', '$env', code(wf, 'Build chat request'))(
  { first: () => ({ json: av }) }, () => ({ first: () => ({ json: chat }) }), env)[0].json.claude_request;
const req = build({ homes: { 'home-2': [['2026-11-01', '2026-12-01']], 'home-3': [] } });
check('uses the configured model and structured JSON output', req.model === 'claude-haiku-4-5'
  && req.output_config.format.type === 'json_schema' && req.output_config.format.schema.properties.lead.additionalProperties === false);
check('rules and facts come first and are cached; availability after', req.system[0].cache_control && req.system[0].text.includes('Never state or estimate a price')
  && req.system[0].text.includes('Abington Colonial') && !req.system[0].text.includes('Today is') && req.system[1].text.includes('Nov 1, 2026'));
check('homes without a calendar are marked "check with the team"', req.system[1].text.includes("home-1 Framingham Center House: no live calendar"));
check('availability failure still builds a request', build({ error: {} }).system[1].text.includes('no live calendar'));
check('conversation passed as-is', JSON.stringify(req.messages) === JSON.stringify(r2.messages));

// The answer: rules enforced in code, handoff
const answer = (ai, stop = 'end_turn', chatState = chat) => new Function('$input', '$', '$getWorkflowStaticData', code(wf, 'Check chat answer'))(
  { first: () => ({ json: { content: [{ type: 'text', text: typeof ai === 'string' ? ai : JSON.stringify(ai) }], stop_reason: stop } }) },
  () => ({ first: () => ({ json: { chat: chatState } }) }), () => store)[0].json;
const noLead = { ready: false, first_name: '', last_name: '', email: '', phone: '', inquiry_type: 'stay', segment: '', property_id: '', check_in: '', check_out: '', guests: '', summary: '' };
let a = answer({ reply: 'Cranston looks open in February!', lead: noLead });
check('normal reply passes through with the session', a.response.reply === 'Cranston looks open in February!' && a.response.session === r.session && !a.handoff);
check('a price in the reply is replaced by the quote message', answer({ reply: 'It is $185 per night.', lead: noLead }).response.reply.includes('personal quote')
  && answer({ reply: 'About 3000 USD a month.', lead: noLead }).response.reply.includes('personal quote'));
check('"you\'re booked" is replaced by "our team will confirm"', answer({ reply: "Great, you're booked for November!", lead: noLead }).response.reply.includes('our team will confirm'));
check('assistant never names anyone but the business', !JSON.stringify(build({})).match(/\bLy\b|husband|wife/));
check('broken JSON or a refusal gets a safe reply', answer('not json').response.reply.includes('rephrase') && answer({ reply: 'x', lead: noLead }, 'refusal').response.reply.includes("can't help"));
const lead = { ...noLead, ready: true, first_name: 'Kim', email: 'Kim@Example.com', segment: 'travel_nurse', property_id: 'home-2',
  check_in: '2027-02-01', check_out: '2027-05-01', guests: '1 person', summary: 'Travel nurse, 13 weeks at Rhode Island Hospital.' };
check('no handoff without a valid email', !answer({ reply: 'ok', lead: { ...lead, email: 'kim' } }).handoff);
a = answer({ reply: 'Sent!', lead });
check('agreed lead becomes a normal inquiry for owner review', a.handoff && a.inquiry.form_type === 'inquiry' && a.inquiry.email === 'kim@example.com'
  && a.inquiry.segment === 'travel_nurse' && a.inquiry.check_in === '2027-02-01' && a.inquiry.guests === '1'
  && a.inquiry.message.includes('Travel nurse, 13 weeks') && a.inquiry.message.includes('Visitor: Dates?') && a.response.handed_off);
check('the same chat never sends a second request', !answer({ reply: 'Sent!', lead }).handoff);

// The inquiry workflow accepts the assistant's request without a browser token (internal key only)
const prep = headers => new Function('$input', '$', '$env', code(inq, 'Prepare spam check'))(
  { first: () => ({ json: { lead: {}, valid: true } }) }, () => ({ first: () => ({ json: { body: {}, headers } }) }), env)[0].json;
check('assistant requests skip the browser spam check with the internal key', prep({ 'x-ntstays-key': 'k3y' }).check_human === false
  && prep({ 'x-ntstays-key': 'wrong' }).check_human === true && prep({}).check_human === true);
const wh = wf.nodes.find(n => n.name === 'Chat message');
check('chat endpoint only accepts the website\'s origins', wh.parameters.options.allowedOrigins.includes('https://ntstays.com'));
console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
