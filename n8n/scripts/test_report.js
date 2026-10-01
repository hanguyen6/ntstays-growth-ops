// Tests the monthly channel report workflow without n8n, Claude or email:  node scripts/test_report.js
// Runs the workflow's own code from workflow/ntstays-report.json with stand-ins for n8n's $input, $, $env, $execution.
const fs = require('fs');
const path = require('path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-report.json'), 'utf8'));
const team = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-team.json'), 'utf8'));
const node = name => wf.nodes.find(n => n.name === name);
const code = name => node(name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const env = { FOLLOWUP_KEY: 'k3y', OWNER_EMAIL: 'owner@example.com', FROM_EMAIL: 'hello@ntstays.com', CLAUDE_MODEL: 'claude-haiku-4-5' };

// ---- which month
const start = (json, e = env) => new Function('$input', '$env', code('Start report'))({ first: () => ({ json }) }, e);
let s = start({});
check('scheduled run reports on last month', /^\d{4}-\d{2}$/.test(s[0].json.month) && s[0].json.prev < s[0].json.month && !s[0].json.manual, s);
s = start({ headers: { 'x-ntstays-key': 'k3y' }, body: { month: '2026-01' } });
check('manual run with the key picks the month; January\'s previous month is December', s[0].json.month === '2026-01' && s[0].json.prev === '2025-12', s);
check('manual run without the key does nothing', start({ headers: { 'x-ntstays-key': 'nope' }, body: {} }).length === 0);

// ---- the facts (computed in code)
const LIVE = {
  airbnb: [{ month: '2026-08', property_id: 'all', overall_conversion: 0.21, listing_to_booking: 1.2 },
           { month: '2026-09', property_id: 'all', overall_conversion: 0.68, similar_overall: 0.29, first_page_rate: 51.8, search_to_listing: 25.89, listing_to_booking: 2.62 },
           { month: '2026-09', property_id: 'home-2', overall_conversion: 9.9 }],
  vrbo: [{ property_id: 'home-2', month: '2026-09', as_of: '2026-09-28', impressions: 471, views: 76, bookings: 1 },
         { property_id: 'home-3', month: '2026-08', as_of: '2026-08-28', impressions: 300, views: 40, bookings: 0 }],
  furnished_finder: [
    { property_id: 'home-1', as_of: '2026-08-28', impressions: 1000, listing_views: 150, booking_inquiries: 40, direct_messages: 30, phone_reveals: 40 },
    { property_id: 'home-1', as_of: '2026-09-28', impressions: 1143, listing_views: 159, booking_inquiries: 47, direct_messages: 34, phone_reveals: 42 },
    { property_id: 'home-2', as_of: '2026-08-28', impressions: 700, listing_views: 80, booking_inquiries: 60, direct_messages: 48, phone_reveals: 50 }],
  bookings: [{ channel: 'furnished_finder', property_id: 'home-1', move_in: '2026-09-10', move_out: '2026-12-10', signed: '2026-09-05', monthly_rent: 3000 },
             { channel: 'referral', property_id: 'home-3', move_in: '2026-08-20', move_out: '2026-09-05', signed: '2026-08-01', monthly_rent: null }],
};
const EXPORT_OVERRIDE = null;
const factsCode = code('Compute the month');
const facts = (live, month = '2026-09', prev = '2026-08') => new Function('$input', '$', factsCode)(
  { first: () => ({ json: live }) }, () => ({ first: () => ({ json: { month, prev } }) }))[0].json;
const f = facts(LIVE);
check('Airbnb: the month\'s all-listings rates as logged, with last month for comparison (not a single home\'s)', f.facts.airbnb.overall_conversion === '0.68%'
  && f.facts.airbnb.similar_listings === '0.29%' && f.facts.airbnb.previous_month.overall_conversion === '0.21%', f.facts.airbnb);
check('Vrbo: the month\'s counts and rates', f.facts.vrbo.property_views === 76 && f.facts.vrbo.viewed === '16.1%' && f.facts.vrbo.booked === '1.3%', f.facts.vrbo);
check('Furnished Finder: new inquiries by difference from the previous entry, leases by signed date',
  f.facts.furnished_finder.new_booking_inquiries === 7 && f.facts.furnished_finder.leases_signed === 1
  && f.facts.furnished_finder.inquiry_to_lease === '14.3%', f.facts.furnished_finder);
check('missing inputs listed: an unlogged Vrbo home and Furnished Finder listing', f.facts.missing.some(m => /Vrbo numbers for Abington/.test(m))
  && f.facts.missing.some(m => /Furnished Finder numbers for Cranston/.test(m)), f.facts.missing);
const ffNights = f.facts.bookings_by_channel.find(b => b.channel === 'Furnished Finder');
check('bookings by channel counts nights inside the month', ffNights && ffNights.stays === 1 && ffNights.nights === 21, f.facts.bookings_by_channel);
check('channel value is percentages only', f.facts.channel_value.every(v => /%$/.test(v.revenue_share) && (v.fee === null || /%$/.test(v.fee))), f.facts.channel_value);
check('the allowed numbers are the facts\' numbers', f.allowed.includes('0.68%') && f.allowed.includes('0.68') && f.allowed.includes('471') && !f.allowed.includes('999'));
const none = facts({ airbnb: [], vrbo: [], furnished_finder: [], bookings: [] });
check('nothing logged: every channel is null and the gaps are listed', none.facts.airbnb === null && none.facts.vrbo === null
  && none.facts.missing.some(m => /Airbnb conversion rates/.test(m)), none.facts);

// ---- the Claude request
const req = new Function('$input', '$env', code('Build the Claude request'))({ first: () => ({ json: f }) }, env)[0].json;
check('structured output with the numbers rule, facts as input', req.claude_request.output_config.format.type === 'json_schema'
  && req.claude_request.system.includes('Use only numbers that appear in FACTS') && req.claude_request.messages[0].content.includes('"0.68%"')
  && req.claude_request.model === 'claude-haiku-4-5');

// ---- the faithfulness check
const draft = over => ({ subject: 'September 2026 channel report', headline: 'Airbnb conversion jumped to 0.68%',
  channels: [{ name: 'Airbnb', text: 'Overall conversion was 0.68%, above similar listings at 0.29%.' },
             { name: 'Vrbo', text: 'Cranston: 471 impressions, 76 views, 1 booking; 16.1% viewed.' },
             { name: 'Furnished Finder', text: '7 new booking inquiries and 1 lease signed (14.3%).' }],
  watch: ['Vrbo numbers for Abington were not logged'], next_actions: ['Log the missing Furnished Finder numbers for Cranston'], ...over });
const checkRun = (report, extra = {}) => new Function('$input', '$', code('Check the report'))(
  { first: () => ({ json: { content: [{ type: 'text', text: typeof report === 'string' ? report : JSON.stringify(report) }],
    stop_reason: 'end_turn', usage: { input_tokens: 1500, output_tokens: 400 }, ...extra } }) },
  () => ({ first: () => ({ json: { ...req, started: Date.now() - 2500 } }) }))[0].json;
let c = checkRun(draft());
check('a faithful draft passes', c.passed && c.problems.length === 0, c.problems);
check('the model call is measured: tokens, cost, time', c.call.input_tokens === 1500 && c.call.cost_usd === 0.0035 && c.call.seconds >= 2.4, c.call);
c = checkRun(draft({ headline: 'Airbnb conversion up 0.47 points' }));
check('an invented number (0.47, the model did the math) blocks the draft', !c.passed && c.bad_numbers.includes('0.47'), c);
c = checkRun(draft({ watch: ['Revenue about $4,000 lower'] }));
check('a dollar amount blocks the draft', !c.passed && c.problems.some(p => /dollar/.test(p)), c.problems);
c = checkRun(draft({ watch: ['Keep going'], next_actions: ['Post more'] }));
check('missing inputs left out of the draft block it', !c.passed && c.problems.some(p => /missing inputs/.test(p)), c.problems);
check('broken JSON and refusals block the draft', !checkRun('not json').passed && !checkRun(draft(), { stop_reason: 'refusal' }).passed);
check('small counts (up to 12) and years are fine in prose', checkRun(draft({ headline: '3 channels in September 2026' })).passed);

// ---- emails and the audit row
c = checkRun(draft());
const emails = new Function('$', '$env', '$execution', code('Build the report emails'))(
  () => ({ first: () => ({ json: c }) }), env, { resumeFormUrl: 'https://n8n.example/form/abc' })[0].json;
check('the owner gets the draft, the computed numbers and the review link', emails.approval_email.htmlContent.includes('https://n8n.example/form/abc')
  && emails.approval_email.htmlContent.includes('computed, not written by AI') && emails.approval_email.to[0].email === 'owner@example.com');
check('a blocked draft emails the reasons and the numbers instead', emails.blocked_email.subject.includes('blocked') && emails.blocked_email.htmlContent.includes('0.68%'));
const audit = new Function('$', code('AI call audit row'))(() => ({ first: () => ({ json: c }) }))[0].json;
check('one audit row per model call, with the table\'s four columns', JSON.stringify(Object.keys(audit)) === JSON.stringify(['kind', 'entered_by', 'entered_at', 'data'])
  && audit.kind === 'ai_call' && JSON.parse(audit.data).output_tokens === 400);

// ---- the owner's decision
const decide = (form, e = { ...env, REPORT_RECIPIENTS: 'a@x.com, b@y.com' }) => new Function('$input', '$', '$env', code('Read the decision'))(
  { first: () => ({ json: form }) }, () => ({ first: () => ({ json: emails }) }), e)[0].json;
let d = decide({ Decision: 'Send to the team', Subject: emails.subject, Report: emails.plain });
check('Send: goes to every report recipient, logged as sent', d.status === 'sent' && d.team_email.to.length === 2 && !d.edited
  && JSON.parse(d.log.data).recipients === 2);
d = decide({ Decision: 'Send to the team', Subject: emails.subject, Report: emails.plain + '\n\nGreat month overall.' });
check('an edit without new numbers still sends (marked edited)', d.status === 'sent' && d.edited);
d = decide({ Decision: 'Send to the team', Subject: emails.subject, Report: emails.plain.replace('0.68%', '0.86%') });
check('an edit that changes a number is blocked, and the owner is told', d.status === 'edit_blocked' && d.bad_numbers.includes('0.86%') && d.owner_note.htmlContent.includes('0.86%'));
check('Don\'t send: nothing goes out, logged', decide({ Decision: "Don't send" }).status === 'not_sent');
check('recipients default to the owner', decide({ Decision: 'Send to the team', Report: emails.plain }, env).team_email.to[0].email === 'owner@example.com');

// ---- one rewrite when the draft fails, then the same check
const bad = checkRun(draft({ headline: 'Furnished Finder share up 14.4 points' }));
check('a failed first draft asks for one rewrite; a passing one or a refusal does not', bad.retry && bad.attempt === 1
  && !checkRun(draft()).retry && !checkRun(draft(), { stop_reason: 'refusal' }).retry, bad);
const retryReq = new Function('$', code('Build the retry request'))(
  n => ({ first: () => ({ json: n === 'Check the report' ? bad : req }) }))[0].json;
const msgs = retryReq.claude_request.messages;
check('the rewrite request carries the draft and names the bad number', retryReq.attempt === 2 && msgs.length === 3
  && msgs[1].role === 'assistant' && msgs[1].content.includes('14.4') && msgs[2].role === 'user' && msgs[2].content.includes('14.4')
  && retryReq.claude_request.output_config.format.type === 'json_schema' && retryReq.allowed.includes('0.68%'), msgs);
const rewriteCheck = (report) => new Function('$input', '$', code('Check the rewrite'))(
  { first: () => ({ json: { content: [{ type: 'text', text: JSON.stringify(report) }], stop_reason: 'end_turn', usage: { input_tokens: 1900, output_tokens: 380 } } }) },
  n => ({ first: () => ({ json: n === 'Build the retry request' ? retryReq : null }) }))[0].json;
const fixed = rewriteCheck(draft());
check('a good rewrite passes, is attempt 2, and never asks for another rewrite', fixed.passed && fixed.attempt === 2 && !fixed.retry, fixed);
const stillBad = rewriteCheck(draft({ headline: 'Furnished Finder share up 14.4 points' }));
check('a bad rewrite is blocked, with no third try', !stillBad.passed && !stillBad.retry && stillBad.first_try.bad_numbers[0] === '14.4', stillBad);
const emailsFor = (first, rewrite) => new Function('$', '$env', '$execution', code('Build the report emails'))(
  n => n === 'Check the rewrite' ? { isExecuted: Boolean(rewrite), first: () => ({ json: rewrite }) } : { isExecuted: true, first: () => ({ json: first }) },
  env, { resumeFormUrl: 'https://n8n.example/form/abc' })[0].json;
check('after a good rewrite, the owner reviews the rewrite', emailsFor(bad, fixed).passed && emailsFor(bad, fixed).attempt === 2);
const blockedHtml = emailsFor(bad, stillBad).blocked_email.htmlContent;
check('the blocked email shows the draft with the bad number highlighted and says it was rewritten once',
  /<mark[^>]*>14\.4<\/mark>/.test(blockedHtml) && blockedHtml.includes('rewrote it once') && !/<mark[^>]*>0\.68%/.test(blockedHtml), blockedHtml.slice(0, 400));
check('the rewrite is logged as its own AI call', JSON.parse(new Function('$', code('Rewrite audit row'))(
  () => ({ first: () => ({ json: fixed }) }))[0].json.data).attempt === 2);
check('wiring: failed first draft → rewrite → same emails; otherwise straight to the emails',
  wf.connections['Rewrite once?'].main[0][0].node === 'Build the retry request' && wf.connections['Rewrite once?'].main[1][0].node === 'Build the report emails'
  && wf.connections['Log the rewrite call'].main[0][0].node === 'Build the report emails');

// ---- wiring and the team summary
check('runs on the 1st of each month at 8:00 New York time', node('On the 1st of the month').parameters.rule.interval[0].expression === '0 8 1 * *'
  && wf.settings.timezone === 'America/New_York');
check('nothing is sent without passing the checks and the owner\'s Send', wf.connections['Passed the checks?'].main[0][0].node === 'Email the owner for review'
  && wf.connections['Send it?'].main[0][0].node === 'Email the team the report');
const summaryCode = team.nodes.find(n => n.name === 'Summarize entries').parameters.jsCode;
const sum = new Function('$input', '$', summaryCode)({ all: () => [
  { json: { id: 1, kind: 'ai_call', data: JSON.stringify({ month: '2026-09', passed: true, cost_usd: 0.0035 }), entered_by: 'monthly-report', entered_at: 'x' } },
  { json: { id: 2, kind: 'report', data: JSON.stringify({ month: '2026-09', status: 'sent' }), entered_by: 'monthly-report', entered_at: 'y' } }] },
  () => ({ first: () => ({ json: { user: 'mm@example.com' } }) }))[0].json;
check('report runs go to the dashboard, not to Recent entries', sum.ai_calls.length === 1 && sum.reports[0].status === 'sent' && sum.recent.length === 0);

console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
