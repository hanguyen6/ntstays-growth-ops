// Tests the "team data" workflow (the sign-in "Log numbers" page) without n8n:  node scripts/test_team.js
// Runs the workflow's own code from workflow/ntstays-team.json with stand-ins for n8n's $input, $ and $env.
const fs = require('fs');
const path = require('path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-team.json'), 'utf8'));
const code = name => wf.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const KEY = 'k'.repeat(32);
const keyCheck = (headers, env = { TEAM_API_KEY: KEY }) => new Function('$input', '$env', code('Check team key (log)'))(
  { first: () => ({ json: { headers, body: { kind: 'x' } } }) }, env)[0].json;
const entry = (body, user = 'mm@example.com') => new Function('$input', code('Check entry'))(
  { first: () => ({ json: { user, body } }) })[0].json;

check('the Worker\'s key and a signed-in email are required', keyCheck({ 'x-ntstays-key': KEY, 'x-ntstays-user': 'MM@Example.com' }).ok
  && keyCheck({ 'x-ntstays-key': KEY, 'x-ntstays-user': 'MM@Example.com' }).user === 'mm@example.com'
  && !keyCheck({ 'x-ntstays-key': 'wrong', 'x-ntstays-user': 'a@b.c' }).ok && !keyCheck({ 'x-ntstays-key': KEY }).ok);
check('refused while TEAM_API_KEY is missing or short', !keyCheck({ 'x-ntstays-key': '', 'x-ntstays-user': 'a@b.c' }, {}).ok
  && !keyCheck({ 'x-ntstays-key': 'short', 'x-ntstays-user': 'a@b.c' }, { TEAM_API_KEY: 'short' }).ok);

const booking = { kind: 'booking', channel: 'furnished_finder', property_id: 'home-3', move_in: '2026-10-01', move_out: '2027-01-01',
  lead_type: 'travel_nurse', contact_email: 'Kim@Example.com', monthly_rent: '3200', note: 'Nurse at South Shore' };
let e = entry(booking);
const saved = JSON.parse(e.row.data);
check('a Furnished Finder lease is accepted', e.valid && e.row.kind === 'booking' && saved.channel === 'furnished_finder'
  && saved.monthly_rent === 3200 && saved.contact_email === 'kim@example.com' && e.row.entered_by === 'mm@example.com', e);
e = entry({ ...booking, contact_email: '(508) 555-0142' });
check('a phone number in the contact box is accepted', e.valid && JSON.parse(e.row.data).contact_phone === '(508) 555-0142'
  && JSON.parse(e.row.data).contact_email === '', e);
check('international phone and email both work; junk is refused', entry({ ...booking, contact_email: '+1 774-555-0100' }).valid
  && JSON.parse(entry({ ...booking, contact_email: 'Kim@Example.com' }).row.data).contact_email === 'kim@example.com'
  && !entry({ ...booking, contact_email: 'call me' }).valid && !entry({ ...booking, contact_email: '123' }).valid);
check('signed-on date optional, checked when given', entry({ ...booking, signed_on: '2026-09-15' }).valid
  && JSON.parse(entry({ ...booking, signed_on: '2026-09-15' }).row.data).signed_on === '2026-09-15' && !entry({ ...booking, signed_on: 'soon' }).valid);
check('the row has exactly the table\'s columns', JSON.stringify(Object.keys(e.row)) === JSON.stringify(['kind', 'data', 'entered_by', 'entered_at']));
e = entry({ ...booking, channel: 'airbnb', property_id: 'home-9', move_out: '2026-09-01', lead_type: 'x', contact_email: 'kim', monthly_rent: 'about 3200' });
check('bad bookings are explained (Airbnb comes from the exports, not here)', !e.valid && e.errors.length === 6, e.errors);
e = entry({ kind: 'ff_stats', property_id: 'home-2', as_of: '2026-10-01', impressions: '1,143', listing_views: '159', favorites: '6', shares: '',
  booking_inquiries: '47', direct_messages: '34', phone_reveals: '42', matched_leads: '117', unmatched_leads: '625' });
const ffd = JSON.parse(e.row.data);
check('Furnished Finder panel numbers accepted (commas fine, blanks allowed)', e.valid && ffd.impressions === 1143 && ffd.shares === null
  && ffd.booking_inquiries === 47 && ffd.unmatched_leads === 625 && ffd.property_id === 'home-2', e);
check('Furnished Finder numbers need the listing\'s home', !entry({ kind: 'ff_stats', as_of: '2026-10-01', listing_views: '5' }).valid
  && entry({ kind: 'ff_stats', as_of: '2026-10-01', listing_views: '5' }).errors.includes('which listing (home)'));
check('Furnished Finder numbers need a date and whole numbers', !entry({ kind: 'ff_stats', property_id: 'home-1', as_of: '', listing_views: '3.5' }).valid
  && !entry({ kind: 'ff_stats', property_id: 'home-1', as_of: '2026-10-01' }).valid);
e = entry({ kind: 'airbnb_stats', month: '2026-08', overall_conversion: '0.29', first_page_rate: '55.1%', search_to_listing: '18.79',
  listing_to_booking: '1.56', similar_overall: '0.32' });
const ab = JSON.parse(e.row.data);
check('Airbnb conversion rates accepted as percentages (all listings by default)', e.valid && ab.overall_conversion === 0.29 && ab.first_page_rate === 55.1
  && ab.listing_to_booking === 1.56 && ab.property_id === 'all', e);
check('Airbnb rates can be for one home', JSON.parse(entry({ kind: 'airbnb_stats', month: '2026-08', property_id: 'home-3', overall_conversion: '1' }).row.data).property_id === 'home-3'
  && !entry({ kind: 'airbnb_stats', month: '2026-08', property_id: 'home-9', overall_conversion: '1' }).valid);
check('Airbnb rates need a month and real percentages', !entry({ kind: 'airbnb_stats', month: '2026-8', overall_conversion: '0.29' }).valid
  && !entry({ kind: 'airbnb_stats', month: '2026-08', overall_conversion: '120' }).valid && !entry({ kind: 'airbnb_stats', month: '2026-08' }).valid);
e = entry({ kind: 'vrbo_stats', property_id: 'home-2', as_of: '2026-09-28', impressions: '471', views: '76', bookings: '1' });
check('Vrbo ranking metrics accepted per home', e.valid && JSON.parse(e.row.data).views === 76 && JSON.parse(e.row.data).property_id === 'home-2', e);
check('Vrbo metrics need the home and a date', !entry({ kind: 'vrbo_stats', as_of: '2026-09-28', views: '5' }).valid
  && !entry({ kind: 'vrbo_stats', property_id: 'home-2', views: '5' }).valid);
check('removing an entry needs its number', entry({ kind: 'void', id: '12' }).valid && !entry({ kind: 'void' }).valid);
check('unknown entries refused', !entry({ kind: 'drop table' }).valid);

const rows = [
  { id: 1, kind: 'booking', data: JSON.stringify({ ...booking, monthly_rent: 3200 }), entered_by: 'mm@example.com', entered_at: '2026-10-01T10:00:00Z' },
  { id: 2, kind: 'booking', data: JSON.stringify({ ...booking, channel: 'website', move_in: '2026-11-01', move_out: '2026-12-15' }), entered_by: 'mm@example.com', entered_at: '2026-10-02T10:00:00Z' },
  { id: 3, kind: 'ff_stats', data: JSON.stringify({ as_of: '2026-10-01', impressions: 1520, views: 310, booking_requests: 6 }), entered_by: 'ha@example.com', entered_at: '2026-10-01T11:00:00Z' },
  { id: 4, kind: 'void', data: JSON.stringify({ id: 2 }), entered_by: 'mm@example.com', entered_at: '2026-10-02T11:00:00Z' },
  { id: 5, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-08', overall_conversion: 0.2 }), entered_by: 'mm@example.com', entered_at: '2026-10-03T10:00:00Z' },
  { id: 6, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-08', overall_conversion: 0.29 }), entered_by: 'mm@example.com', entered_at: '2026-10-03T11:00:00Z' },
  { id: 7, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-07', overall_conversion: 0.4 }), entered_by: 'mm@example.com', entered_at: '2026-10-03T12:00:00Z' },
  { id: 8, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-08', property_id: 'home-2', overall_conversion: 0.9 }), entered_by: 'mm@example.com', entered_at: '2026-10-03T13:00:00Z' },
  { id: 9, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-07', overall_conversion: 0.4, search_to_listing: 18.5, listing_to_booking: 1.2 }), entered_by: 'mm@example.com', entered_at: '2026-10-04T10:00:00Z' },
  { id: 11, kind: 'vrbo_stats', data: JSON.stringify({ property_id: 'home-2', as_of: '2026-09-02', impressions: 400, views: 60, bookings: 0 }), entered_by: 'mm@example.com', entered_at: '2026-09-02T10:00:00Z' },
  { id: 12, kind: 'vrbo_stats', data: JSON.stringify({ property_id: 'home-2', as_of: '2026-09-28', impressions: 471, views: 76, bookings: 1 }), entered_by: 'mm@example.com', entered_at: '2026-09-28T10:00:00Z' },
  { id: 10, kind: 'airbnb_stats', data: JSON.stringify({ month: '2026-07', overall_conversion: null, similar_overall: 0.31, search_to_listing: null }), entered_by: 'mm@example.com', entered_at: '2026-10-04T11:00:00Z' },
];
const summarize = input => new Function('$input', '$', code('Summarize entries'))(
  { all: () => input.map(json => ({ json })) }, () => ({ first: () => ({ json: { user: 'mm@example.com' } }) }))[0].json;
const sum = summarize(rows);
check('removed entries don\'t count but stay listed', sum.bookings.length === 1 && sum.bookings[0].id === 1
  && sum.recent.find(r => r.id === 2).removed === true && sum.recent.length === 11, sum);
check('Vrbo: one result per home and month, the later entry wins', sum.vrbo.length === 1 && sum.vrbo[0].month === '2026-09'
  && sum.vrbo[0].views === 76 && sum.vrbo[0].bookings === 1, sum.vrbo);
const allAb = sum.airbnb.filter(a => a.property_id === 'all');
check('Airbnb: one entry per month and listings choice, the latest wins, in month order', allAb.length === 2 && allAb[0].month === '2026-07'
  && allAb[1].overall_conversion === 0.29 && sum.airbnb.find(a => a.property_id === 'home-2').overall_conversion === 0.9, sum.airbnb);
const jul = allAb.find(a => a.month === '2026-07');
check('Airbnb: topping up one rate keeps the others (blanks never erase)', jul.similar_overall === 0.31 && jul.overall_conversion === 0.4
  && jul.search_to_listing === 18.5 && jul.listing_to_booking === 1.2, jul);
check('Furnished Finder numbers returned in date order', sum.furnished_finder.length === 1 && sum.furnished_finder[0].as_of === '2026-10-01');
check('a lease counts from its signed-on date, else its move-in', sum.bookings[0].signed === '2026-10-01');
check('no emails or phones go to the dashboard; rent does (shown only as percentages)', !JSON.stringify(sum).includes('kim@')
  && !JSON.stringify(sum.bookings).includes('contact')
  && sum.bookings[0].monthly_rent === 3200);
check('who is signed in', sum.you === 'mm@example.com');
check('an empty table still answers', summarize([{}]).bookings.length === 0);
const load = wf.nodes.find(n => n.name === 'Load entries');
check('empty table still reaches the reply (alwaysOutputData)', load.alwaysOutputData === true && load.parameters.returnAll === true);
check('stored in the "ntstays_team_log" data table', wf.nodes.filter(n => n.type === 'n8n-nodes-base.dataTable')
  .every(n => n.parameters.dataTableId.value === 'ntstays_team_log'));

console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
