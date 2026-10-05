// Tests request-to-book payments without n8n, Docker or Stripe:  node scripts/test_payments.js
// Runs the workflows' own code (payment link in the inquiry workflow, confirmation and calendar feed in the payments
// workflow) with stand-ins for n8n's $input, $, $env and $getWorkflowStaticData.
const fs = require('fs');
const path = require('path');
const load = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', f), 'utf8'));
const inq = load('ntstays-inquiry.json'), pay = load('ntstays-payments.json');
const code = (wf, name) => wf.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const env = { FROM_EMAIL: 'hello@ntstays.com', OWNER_EMAIL: 'owner@example.com', OWNER_NAME: 'Ha', STRIPE_SECRET_KEY: 'rk_test_x' };
const params = body => Object.fromEntries(new URLSearchParams(body));

// 1. Review decision: amount -> payment
const lead = { inquiry_type: 'stay', segment: 'travel_nurse', is_service: false, property_id: 'home-2', check_in: '2026-11-01',
  check_out: '2026-12-01', guests: 2, email: 'kim@example.com', first_name: 'Kim', last_name: 'Lee' };
const decide = (form, e = env) => new Function('$input', '$', '$env', code(inq, 'Read review decision'))(
  { first: () => ({ json: form }) },
  () => ({ first: () => ({ json: { lead, email_subject: 'Re: Cranston', email_body: 'Hi Kim,\n\nYes, those dates work.\n\nHa', contact_id: '77' } }) }),
  e)[0].json;
let d = decide({ Decision: 'Send this reply', 'Amount to charge (USD)': '3,450.50', 'Payment for': 'November stay, Cranston House' });
check('amount becomes a payment in cents', d.payment && d.payment.cents === 345050, d.payment);
const price = params(d.payment.price_body);
check('Stripe price request is form-encoded correctly', price.unit_amount === '345050' && price.currency === 'usd'
  && price['product_data[name]'] === 'NTStays: November stay, Cranston House', price);
check('booking details travel with the payment', d.payment.metadata.home === 'home-2' && d.payment.metadata.check_out === '2026-12-01'
  && d.payment.metadata.contact_id === '77' && d.payment.metadata.ntstays === 'booking', d.payment.metadata);
check('no amount: no payment link', decide({ Decision: 'Send this reply' }).payment === null);
check("don't send: no payment link", decide({ Decision: "Don't send (I'll handle it myself)", 'Amount to charge (USD)': '100' }).payment === null);
check('under $0.50: no payment link', decide({ Decision: 'Send this reply', 'Amount to charge (USD)': '0.25' }).payment === null);
check('Stripe not set up: no payment link', decide({ Decision: 'Send this reply', 'Amount to charge (USD)': '100' },
  { ...env, STRIPE_SECRET_KEY: '' }).payment === null);

// 2. Payment link request, then the Pay button in the reply
const asDecision = () => ({ first: () => ({ json: d }) });
const link = new Function('$input', '$', '$env', code(inq, 'Build payment link request'))(
  { first: () => ({ json: { id: 'price_123' } }) }, asDecision, env)[0].json;
const lp = params(link.link_body);
check('payment link uses the price, once only, with booking details', lp['line_items[0][price]'] === 'price_123'
  && lp['restrictions[completed_sessions][limit]'] === '1' && lp['payment_intent_data[metadata][check_in]'] === '2026-11-01'
  && lp['payment_intent_data[metadata][email]'] === 'kim@example.com', lp);
let threw = false;
try { new Function('$input', '$', '$env', code(inq, 'Build payment link request'))({ first: () => ({ json: { error: { message: 'bad key' } } }) }, asDecision, env); }
catch (e) { threw = /price/.test(e.message); }
check('a Stripe error stops the reply (nothing half-sent) and raises an alert', threw);
const withLink = new Function('$input', '$', '$env', code(inq, 'Add payment link to reply'))(
  { first: () => ({ json: { id: 'plink_1', url: 'https://buy.stripe.com/test_abc' } }) }, asDecision, env)[0].json;
check('reply gets a Pay securely button with the amount', withLink.reply_email.htmlContent.includes('https://buy.stripe.com/test_abc?prefilled_email=kim%40example.com')
  && withLink.reply_email.htmlContent.includes('$3,450.50') && withLink.reply_email.htmlContent.endsWith('</div>'));
check('plain-text reply has the link too', withLink.reply_email.textContent.includes('Pay securely by card: https://buy.stripe.com/test_abc'));
check('the rest of the reply is unchanged', withLink.reply_email.htmlContent.startsWith(d.reply_email.htmlContent.slice(0, -6)));
const edges = inq.connections;
check('routing: send -> collect payment? -> price -> link -> reply', edges['Send reply?'].main[0][0].node === 'Collect payment?'
  && edges['Collect payment?'].main[0][0].node === 'Stripe: create price' && edges['Collect payment?'].main[1][0].node === 'Email reply to lead'
  && edges['Add payment link to reply'].main[0][0].node === 'Email reply to lead');

// 3. Stripe notice -> confirmation
const readEvent = body => new Function('$input', code(pay, 'Read Stripe event'))({ first: () => ({ json: { body } }) });
check('paid checkout is picked up', readEvent({ id: 'evt_1', type: 'checkout.session.completed',
  data: { object: { payment_status: 'paid', payment_intent: 'pi_1' } } })[0]?.json.payment_intent === 'pi_1');
check('other events are ignored', readEvent({ type: 'payment_intent.created', data: { object: {} } }).length === 0
  && readEvent({ type: 'checkout.session.completed', data: { object: { payment_status: 'unpaid', payment_intent: 'pi_2' } } }).length === 0);
const store = {};
const confirm = pi => new Function('$input', '$env', '$getWorkflowStaticData', code(pay, 'Build confirmation'))(
  { first: () => ({ json: pi }) }, env, () => store);
const pi = { id: 'pi_1', status: 'succeeded', amount_received: 345050, currency: 'usd', metadata: { ...d.payment.metadata } };
let c = confirm(pi)[0]?.json;
check('guest confirmation: home, dates, amount', c && c.guest_email.to[0].email === 'kim@example.com' && c.guest_email.textContent.includes('Cranston House')
  && c.guest_email.textContent.includes('$3,450.50') && c.guest_email.subject.startsWith('Your stay is confirmed'), c && c.guest_email.subject);
check('owner told, HubSpot note on the contact', c.owner_email.to[0].email === 'owner@example.com' && c.has_contact && c.note.associations[0].to.id === '77');
check('the same payment is only confirmed once', confirm(pi).length === 0);
check('an unpaid or foreign payment confirms nothing', confirm({ ...pi, id: 'pi_9', status: 'requires_payment_method' }).length === 0
  && confirm({ ...pi, id: 'pi_8', metadata: {} }).length === 0);

// 4. Direct-bookings calendar feed
const feed = (home, res) => new Function('$input', '$', code(pay, 'Build iCal feed'))(
  { first: () => ({ json: res }) }, () => ({ first: () => ({ json: { home } }) }))[0].json.ics;
const intents = { data: [pi, { id: 'pi_3', status: 'succeeded', metadata: { ntstays: 'booking', home: 'home-3', check_in: '2026-10-05', check_out: '2026-10-09' } },
  { id: 'pi_4', status: 'succeeded', metadata: { ntstays: 'booking', home: 'home-2', check_in: 'soon', check_out: '' } }] };
const ics = feed('home-2', intents);
check('feed has the home\'s paid booking as dates', ics.includes('DTSTART;VALUE=DATE:20261101') && ics.includes('DTEND;VALUE=DATE:20261201')
  && ics.startsWith('BEGIN:VCALENDAR') && ics.includes('END:VCALENDAR'));
// Look for the other home's booking as an event date, not the bare digits: the feed's DTSTAMP is today's date,
// which once matched (the test failed on 2026-10-05 only).
check('feed leaves out other homes, bad dates and all guest details', !ics.includes('DATE:20261005') && !ics.includes('soon')
  && !ics.includes('kim') && !ics.includes('3450') && (ics.match(/BEGIN:VEVENT/g) || []).length === 1);
check('Stripe unreachable: an empty but valid calendar', feed('home-2', { error: {} }).includes('BEGIN:VCALENDAR'));
const prep = q => new Function('$input', '$env', code(pay, 'Prepare feed'))({ first: () => ({ json: { query: q } }) }, env)[0].json;
check('unknown home: no Stripe call', !prep({ home: '../x' }).ask_stripe && prep({ home: 'home-1' }).ask_stripe);
console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
