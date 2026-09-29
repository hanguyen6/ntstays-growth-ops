// Tests follow-ups and spam protection without n8n, Docker, Stripe or Cloudflare:  node scripts/test_followups.js
// Runs the workflows' own code with stand-ins for n8n's $input, $, $env, $execution and $getWorkflowStaticData.
const fs = require('fs');
const path = require('path');
const load = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', f), 'utf8'));
const fu = load('ntstays-followups.json'), inq = load('ntstays-inquiry.json');
const code = (wf, name) => wf.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const env = { FROM_EMAIL: 'hello@ntstays.com', OWNER_EMAIL: 'owner@example.com', OWNER_NAME: 'Ha', STRIPE_SECRET_KEY: 'rk_test_x', UNSUBSCRIBE_SECRET: 'k3y' };
const day = n => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

// Start: schedule runs; webhook needs the key
const start = (json, e = env) => new Function('$input', '$env', code(fu, 'Start check'))({ first: () => ({ json }) }, e);
check('morning schedule starts the check', start({ timestamp: 'x' })[0].json.stripe === true);
check('run-now webhook needs the internal key', start({ headers: {} }).length === 0 && start({ headers: { 'x-ntstays-key': 'k3y' } }).length === 1);

// Find: what's due today
const base = { ntstays: 'booking', first_name: 'Kim', email: 'kim@example.com', home: 'home-2', contact_id: '7' };
const links = { data: [
  { id: 'plink_due', url: 'https://buy.stripe.com/a', metadata: { ...base, ref: 'r1', sent: day(-3), check_in: day(10), check_out: day(40) } },
  { id: 'plink_new', url: 'https://buy.stripe.com/b', metadata: { ...base, ref: 'r2', sent: day(-1), check_in: day(10), check_out: day(40) } },
  { id: 'plink_paid', url: 'https://buy.stripe.com/c', metadata: { ...base, ref: 'r3', sent: day(-5), check_in: day(10), check_out: day(40) } },
  { id: 'plink_done', url: 'https://buy.stripe.com/d', metadata: { ...base, ref: 'r4', sent: day(-5), check_in: day(10), nudge_queued: day(-2) } },
  { id: 'plink_past', url: 'https://buy.stripe.com/e', metadata: { ...base, ref: 'r5', sent: day(-9), check_in: day(-1) } },
  { id: 'plink_other', url: 'https://buy.stripe.com/f', metadata: {} }] };
const paid = { data: [
  { id: 'pi_paid', status: 'succeeded', metadata: { ...base, ref: 'r3', check_in: day(10), check_out: day(40) } },
  { id: 'pi_left', status: 'succeeded', metadata: { ...base, ref: 'r6', check_in: day(-10), check_out: day(-1) } },
  { id: 'pi_long', status: 'succeeded', metadata: { ...base, ref: 'r7', check_in: day(-60), check_out: day(14) } },
  { id: 'pi_short', status: 'succeeded', metadata: { ...base, ref: 'r8', check_in: day(10), check_out: day(14) } },
  { id: 'pi_old', status: 'succeeded', metadata: { ...base, ref: 'r9', check_in: day(-30), check_out: day(-8) } }] };
const store = {};
const find = () => new Function('$input', '$', '$getWorkflowStaticData', code(fu, 'Find due follow-ups'))(
  { first: () => ({ json: paid }) }, () => ({ first: () => ({ json: links }) }), () => store).map(i => i.json);
let due = find();
const keys = due.map(i => i.key).sort();
check('payment reminder only for the unpaid link sent 2+ days ago', due.filter(i => i.kind === 'payment_reminder').map(i => i.link_id).join() === 'plink_due', keys);
check('thank-you the day after check-out, not for old stays', due.filter(i => i.kind === 'thank_you').map(i => i.key).join() === 'thanks:pi_left', keys);
check('extension offer only for a monthly stay ending in 2 weeks', due.filter(i => i.kind === 'extension').map(i => i.key).join() === 'extend:pi_long', keys);
check('thank-yous and extension offers are never queued twice', find().filter(i => i.kind !== 'payment_reminder').length === 0);
const routes = fu.connections['Start follow-up review'].main[0][0].node === 'Payment reminder?'
  && fu.connections['Payment reminder?'].main[0][0].node === 'Stripe: mark reminder queued';
check('reminders are marked in Stripe after queuing (never sent twice)', routes);

// Draft: owner review email, only with the key
const draft = (body, headers = { 'x-ntstays-key': 'k3y' }) => new Function('$input', '$env', '$execution', code(fu, 'Build follow-up draft'))(
  { first: () => ({ json: { headers, body } }) }, env, { resumeFormUrl: 'https://n8n.example/form-waiting/1' });
check('follow-up webhook refuses calls without the key', draft(due[0], {}).length === 0);
const reminder = draft(due.find(i => i.kind === 'payment_reminder'))[0].json;
check('payment reminder draft has the payment link with the email filled in', reminder.message.includes('https://buy.stripe.com/a?prefilled_email=kim%40example.com')
  && reminder.message.startsWith('Hi Kim,') && reminder.subject.includes('Cranston House'), reminder.message);
check('owner gets the draft with a review button', reminder.owner_email.to[0].email === 'owner@example.com'
  && reminder.owner_email.htmlContent.includes('form-waiting') && reminder.owner_email.subject.includes('Payment reminder for Kim'));
const thanks = draft({ kind: 'thank_you', meta: { ...base, check_out: day(-1) } })[0].json;
check('thank-you draft links to the feedback form', thanks.message.includes('https://ntstays.com/review'));
const ext = draft({ kind: 'extension', meta: { ...base, check_out: day(14) } })[0].json;
check('extension draft names the end date and promises nothing', ext.message.includes('ends on') && !/guarantee|discount/i.test(ext.message));

// Decision: nothing goes out unless the owner chooses Send
const decide = (form, d) => new Function('$input', '$', '$env', code(fu, 'Read follow-up decision'))(
  { first: () => ({ json: form }) }, () => ({ first: () => ({ json: d }) }), env)[0].json;
let r = decide({ Decision: 'Send this follow-up', Message: 'Hi Kim,\n\nEdited.\n\nhttps://ntstays.com/review' }, thanks);
check('edited follow-up is what gets sent, links clickable', r.send && r.guest_email.textContent.includes('Edited.')
  && r.guest_email.htmlContent.includes('<a href="https://ntstays.com/review">') && r.guest_email.to[0].email === 'kim@example.com');
check("Don't send sends nothing", decide({ Decision: "Don't send" }, thanks).send === false && decide({}, thanks).send === false);

// Spam protection in the inquiry workflow
const prep = (body, e) => new Function('$input', '$', '$env', code(inq, 'Prepare spam check'))(
  { first: () => ({ json: { lead: { email: 'a@b.co' }, valid: true } }) },
  () => ({ first: () => ({ json: { body, headers: { 'cf-connecting-ip': '1.2.3.4' } } }) }), e)[0].json;
check('spam check off until TURNSTILE_SECRET is set', prep({ turnstile: 'tok' }, {}).check_human === false);
const on = prep({ turnstile: 'tok' }, { TURNSTILE_SECRET: 's3' });
check('spam check sends secret, token and visitor IP to Cloudflare', on.check_human && on.turnstile_body.includes('secret=s3')
  && on.turnstile_body.includes('response=tok') && on.turnstile_body.includes('remoteip=1.2.3.4') && on.lead.email === 'a@b.co');
const result = r2 => new Function('$input', '$', code(inq, 'Read spam check'))({ first: () => ({ json: r2 }) },
  () => ({ first: () => ({ json: { lead: { email: 'a@b.co' } } }) }))[0].json;
check('Cloudflare success lets the form through, anything else is refused', result({ success: true }).human === true
  && result({ success: false, 'error-codes': ['timeout-or-duplicate'] }).human === false && result({}).human === false);
const e = inq.connections;
check('routing: valid -> spam check -> thanks (or 400)', e['Valid?'].main[0][0].node === 'Prepare spam check'
  && e['Human?'].main[0][0].node === 'Thank the visitor (200)' && e['Human?'].main[1][0].node === 'Spam check failed (400)'
  && e['Spam check on?'].main[1][0].node === 'Thank the visitor (200)');
console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
