// Tests campaign tracking (where a visitor came from) without a browser, n8n or HubSpot:  node scripts/test_source.js
// Runs site/assets/source.js with a stand-in browser, and the workflows' own code with stand-ins for n8n.
const fs = require('fs');
const path = require('path');
const load = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', f), 'utf8'));
const inq = load('ntstays-inquiry.json'), chatWf = load('ntstays-chat.json');
const code = (w, name) => w.nodes.find(n => n.name === name).parameters.jsCode;
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };

// ---- the website script
const SOURCE_JS = fs.readFileSync(path.join(__dirname, '..', '..', 'site', 'assets', 'source.js'), 'utf8');
function visit(url, referrer = '', storage = {}) {
  const u = new URL(url);
  const window = {};
  const sessionStorage = { getItem: k => storage[k] ?? null, setItem: (k, v) => { storage[k] = v; } };
  new Function('window', 'location', 'document', 'sessionStorage', SOURCE_JS)(
    window, { search: u.search, pathname: u.pathname, hostname: u.hostname }, { referrer }, sessionStorage);
  return window.ntSource.get();
}
let s = visit('https://ntstays.com/travel-nurses?utm_source=Facebook&utm_medium=social&utm_campaign=Nurses Oct26');
check('campaign tags are read and tidied', s.source === 'facebook' && s.medium === 'social' && s.campaign === 'nurses-oct26'
  && s.landing === '/travel-nurses', s);
s = visit('https://ntstays.com/', 'https://www.google.com/');
check('Google search without tags', s.source === 'google' && s.medium === 'organic' && s.referrer === 'google.com', s);
s = visit('https://ntstays.com/', 'https://l.facebook.com/l.php?u=x');
check('Facebook link without tags', s.source === 'facebook' && s.medium === 'social', s);
s = visit('https://ntstays.com/insurance-housing', 'https://claims.example.org/portal');
check('other websites count as referrals', s.source === 'claims.example.org' && s.medium === 'referral', s);
s = visit('https://ntstays.com/');
check('typed address is "direct"', s.source === 'direct' && s.medium === 'none', s);
s = visit('https://ntstays.com/?gclid=abc');
check('Google Ads click', s.source === 'google' && s.medium === 'ads', s);
const tab = {};
visit('https://ntstays.com/?utm_source=flyer&utm_campaign=hospital-board', '', tab);
s = visit('https://ntstays.com/travel-nurses', 'https://ntstays.com/', tab);
check('the first page of the visit wins, later pages keep it', s.source === 'flyer' && s.campaign === 'hospital-board', s);

// ---- the inquiry workflow
const ON = { HUBSPOT_SOURCE_FIELDS: 'on', FROM_EMAIL: 'hello@ntstays.com', OWNER_EMAIL: 'owner@example.com' };
const validate = (body, env = ON) => new Function('$input', '$env', code(inq, 'Validate & normalize'))(
  { all: () => [{ json: { body } }] }, env)[0].json;
const form = { form_type: 'inquiry', inquiry_type: 'stay', first_name: 'Kim', email: 'kim@example.com', message: 'Dates?',
  heard_about: 'hospital_agency',
  source: { source: 'facebook', medium: 'social', campaign: 'nurses-oct26<script>', landing: '/travel-nurses"><b>', referrer: 'l.facebook.com' } };
let v = validate(form);
check('server keeps only plain labels', v.lead.source.campaign === 'nurses-oct26script' && v.lead.source.landing === '/travel-nursesb'
  && v.lead.heard_about === 'hospital_agency', v.lead.source);
check('unknown "heard about" answers are dropped', validate({ ...form, heard_about: 'hacker' }).lead.heard_about === '');
check('no source at all is fine', validate({ ...form, source: 'x' }).lead.source.source === '');

const ai = { score: 80, reasons: ['ok'], summary: 'Nurse', email_subject: 'Hi', email_body: 'Hi Kim, thanks.' };
const checkAi = (lead, existing = {}, env = ON) => new Function('$input', '$', '$env', code(inq, 'Check AI output'))(
  { all: () => [{ json: { content: [{ type: 'text', text: JSON.stringify(ai) }] } }] },
  () => ({ all: () => [{ json: { lead, existing_contact_id: Object.keys(existing).length ? '42' : null, existing_properties: existing } }] }),
  env)[0].json;
let props = checkAi(v.lead).contact_properties;
check('new contact gets source, medium, campaign, first page and "heard about"', props.ntstays_source === 'facebook'
  && props.ntstays_medium === 'social' && props.ntstays_campaign === 'nurses-oct26script' && props.ntstays_first_page === '/travel-nursesb'
  && props.ntstays_heard_about === 'hospital_agency', props);
check('lead type recorded: guest stay, audience from the landing page, owners', props.ntstays_lead_type === 'guest'
  && checkAi(validate({ ...form, segment: 'travel_nurse' }).lead).contact_properties.ntstays_lead_type === 'travel_nurse'
  && checkAi(validate({ ...form, inquiry_type: 'property_management' }).lead).contact_properties.ntstays_lead_type === 'owner');
props = checkAi(v.lead, { ntstays_source: 'google', ntstays_heard_about: '' }).contact_properties;
check('a returning contact keeps its first source', !('ntstays_source' in props) && !('ntstays_campaign' in props)
  && props.ntstays_heard_about === 'hospital_agency', props);
props = checkAi(v.lead, {}, { ...ON, HUBSPOT_SOURCE_FIELDS: '' }).contact_properties;
check('custom fields are only sent once they exist in HubSpot (HUBSPOT_SOURCE_FIELDS=on)', !Object.keys(props).some(k => k.startsWith('ntstays_')), props);
const findNode = inq.nodes.find(n => n.name === 'HubSpot: find contact');
check('contact search only asks for the custom fields when they exist', JSON.stringify(findNode.parameters).includes("HUBSPOT_SOURCE_FIELDS === 'on' ? ['ntstays_source', 'ntstays_heard_about', 'ntstays_lead_type'] : []"));

const noteOut = new Function('$input', '$', '$env', '$execution', code(inq, 'Build review note & owner email'))(
  { all: () => [{ json: { results: [{ id: '7' }] } }] },
  () => ({ all: () => [{ json: { ...checkAi(v.lead), flags: [] } }] }), ON, { resumeFormUrl: 'https://n8n.example/form' })[0].json;
check('owner email shows where the lead came from', noteOut.owner_email.htmlContent.includes('facebook / social, campaign nurses-oct26script')
  && noteOut.owner_email.htmlContent.includes('hospital or staffing agency'), noteOut.owner_email.htmlContent.match(/Came from.{0,160}/));
check('the CRM note shows it too', noteOut.note.properties.hs_note_body.includes('Came from:</b> facebook / social'));

const sub = validate({ form_type: 'subscribe', email: 'sam@example.com', source: { source: 'google', medium: 'organic', landing: '/' } });
const subOut = new Function('$input', '$', '$env', code(inq, 'Build subscriber'))(
  { first: () => ({ json: { results: [] } }) }, () => ({ first: () => ({ json: sub }) }), ON)[0].json;
check('newsletter sign-ups get the source too (no lead type)', subOut.contact_properties.ntstays_source === 'google' && !('ntstays_campaign' in subOut.contact_properties)
  && !('ntstays_lead_type' in subOut.contact_properties),
  subOut.contact_properties);

// ---- the chat passes the source on to the request it sends
const env = { CLAUDE_MODEL: 'claude-haiku-4-5', UNSUBSCRIBE_SECRET: 'k3y' };
const read = new Function('$input', '$env', '$getWorkflowStaticData', code(chatWf, 'Read chat'))(
  { first: () => ({ json: { body: { messages: [{ role: 'user', content: 'Hi' }], source: { source: 'flyer', campaign: 'hospital-board' } } } }) },
  env, () => ({}))[0].json;
check('chat reads the source', read.source.source === 'flyer' && read.source.campaign === 'hospital-board', read.source);
const lead = { ready: true, first_name: 'Kim', last_name: '', email: 'kim@example.com', phone: '', inquiry_type: 'stay', segment: '',
  property_id: '', check_in: '', check_out: '', guests: '', summary: 'Nurse.' };
const answer = new Function('$input', '$', '$getWorkflowStaticData', code(chatWf, 'Check chat answer'))(
  { first: () => ({ json: { content: [{ type: 'text', text: JSON.stringify({ reply: 'Sent!', lead }) }], stop_reason: 'end_turn' } }) },
  () => ({ first: () => ({ json: { chat: { ...read, session: 'abcdefghijkl.9999999999', sig: 's' } } }) }), () => ({ sessions: {} }))[0].json;
check('chat request carries the source', answer.handoff && answer.inquiry.source.source === 'flyer', answer.inquiry);
check('and the inquiry workflow accepts it', validate(answer.inquiry).lead.source.campaign === 'hospital-board');

console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
