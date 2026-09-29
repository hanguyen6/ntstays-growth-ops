// Tests the calendar sync (workflow/ntstays-availability.json) without n8n or Docker:  node scripts/test_availability.js
// Runs the workflow's own code with stand-ins for n8n's $input, $, $env and $getWorkflowStaticData.
const fs = require('fs');
const path = require('path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-availability.json'), 'utf8'));
const code = name => wf.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };

const day = n => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const ymd = s => s.replace(/-/g, '');
const ev = (a, b, summary, extra = '') => `BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:${ymd(a)}\r\nDTEND;VALUE=DATE:${ymd(b)}\r\nSUMMARY:${summary}\r\n${extra}UID:x@airbnb.com\r\nEND:VEVENT\r\n`;
const cal = events => `BEGIN:VCALENDAR\r\nPRODID:-//Airbnb Inc//Hosting Calendar 1.0//EN\r\nVERSION:2.0\r\n${events}END:VCALENDAR\r\n`;

const store = {};
const env = { ICAL_HOME_2: 'https://cal.example/a.ics https://cal.example/b.ics', ICAL_HOME_3: 'https://cal.example/c.ics' };
const runCheck = () => new Function('$env', '$getWorkflowStaticData', code('Check cache'))(env, () => store)[0].json;
const runMerge = (feeds, responses, e = env) => new Function('$input', '$', '$env', '$getWorkflowStaticData', code('Merge busy dates'))(
  { all: () => responses.map(r => ({ json: r })) }, () => ({ all: () => feeds.map(f => ({ json: f })) }), e, () => store)[0].json.body;

let c = runCheck();
check('no cache yet: fetch all feeds', !c.use_cache && c.feeds.length === 3 && c.feeds[0].home === 'home-2', c);

const feeds = c.feeds;
const airbnbA = cal(ev(day(2), day(9), 'Reserved', 'DESCRIPTION:Reservation URL: https://www.airbnb.com/hosting/reservations/details/HMSECRET\\nPhone Number (Last 4 Digits): 1234\r\n')
  + ev(day(20), day(40), 'Airbnb (Not available)') + ev(day(-30), day(-20), 'Reserved'));
// Vrbo-style: date-times, a folded line, a cancelled booking, a range overlapping Airbnb's
const vrboB = cal('BEGIN:VEVENT\r\nDTSTART:' + ymd(day(8)) + 'T160000Z\r\nDTEND:' + ymd(day(12)) + 'T100000Z\r\nSUMMARY:Reserved - long\r\n  folded title\r\nEND:VEVENT\r\n'
  + ev(day(50), day(55), 'Reserved', 'STATUS:CANCELLED\r\n'));
const abington = cal(ev(day(0), day(1), 'Reserved'));
let body = runMerge(feeds, [{ ics: airbnbA }, { ics: vrboB }, { ics: abington }]);
check('overlapping bookings from two platforms merge into one range', JSON.stringify(body.homes['home-2'].slice(0, 1)) === JSON.stringify([[day(2), day(12)]]), body.homes['home-2']);
check('"Not available" blocks count as busy by default', body.homes['home-2'].some(r => r[0] === day(20) && r[1] === day(40)), body.homes['home-2']);
check('past stays and cancelled bookings are dropped', !JSON.stringify(body.homes).includes(day(-30)) && !body.homes['home-2'].some(r => r[0] === day(50)));
check('only dates leave the server', !JSON.stringify(body).includes('HMSECRET') && !JSON.stringify(body).includes('1234')
  && !JSON.stringify(body).includes('Reserved'));
check('second home parsed', JSON.stringify(body.homes['home-3']) === JSON.stringify([[day(0), day(1)]]), body.homes['home-3']);

c = runCheck();
check('fresh cache is served without fetching', c.use_cache && JSON.stringify(c.body.homes) === JSON.stringify(body.homes));

store.cache.at = 0;  // expire it
body = runMerge(feeds, [{ ics: airbnbA }, { error: { message: 'timeout' } }, { ics: abington }]);
check('a failed feed keeps that home\'s last good dates and is reported', body.stale.includes('home-2')
  && body.homes['home-2'][0][1] === day(12), body);

body = runMerge(feeds, [{ ics: airbnbA }, { ics: vrboB }, { ics: abington }], { ...env, ICAL_IGNORE_BLOCKS: 'home-2' });
check('ICAL_IGNORE_BLOCKS: only real reservations count for that home', !body.homes['home-2'].some(r => r[0] === day(20)), body.homes['home-2']);

store.cache = undefined;
body = runMerge(feeds, [{ error: {} }, { error: {} }, { error: {} }]);
check('all feeds failing does not cache an empty calendar', store.cache === undefined && body.stale.length === 2);

const noFeeds = new Function('$env', '$getWorkflowStaticData', code('Check cache'))({}, () => ({}))[0].json;
check('no calendar links configured: answers with an empty calendar', noFeeds.use_cache && JSON.stringify(noFeeds.body.homes) === '{}');

const wh = wf.nodes.find(n => n.type === 'n8n-nodes-base.webhook');
check('public GET endpoint, limited to the website origins', wh.parameters.httpMethod === 'GET'
  && wh.parameters.path === 'ntstays-availability' && wh.parameters.options.allowedOrigins.includes('https://ntstays.com'));
console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
