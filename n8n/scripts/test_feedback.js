// Tests the feedback-form branch (ntstays.com/review) without n8n or Docker:  node scripts/test_feedback.js
// Runs the workflow's own code from workflow/ntstays-inquiry.json with stand-ins for n8n's $input, $ and $env.
const fs = require('fs');
const path = require('path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-inquiry.json'), 'utf8'));
const code = name => wf.nodes.find(n => n.name === name).parameters.jsCode;
const env = { FROM_EMAIL: 'hello@ntstays.com', OWNER_EMAIL: 'owner@example.com', OWNER_NAME: 'Ha' };
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const validate = body => new Function('$input', '$env', code('Validate & normalize'))({ all: () => [{ json: { body } }] }, env)[0].json;
const build = v => new Function('$input', '$', '$env', code('Build feedback records'))(
  { first: () => ({ json: {} }) }, () => ({ first: () => ({ json: v }) }), env)[0].json;
// Minimal CSV reader, to prove the pasted line splits into the right columns.
const parseCsv = line => { const out = []; let cur = '', q = false;
  for (let i = 0; i < line.length; i++) { const c = line[i];
    if (q) { if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
    else if (c === '"') q = true; else if (c === ',') { out.push(cur); cur = ''; } else cur += c; }
  out.push(cur); return out; };

const partner = { form_type: 'review', role: 'partner', first_name: 'Pat', last_name: 'Nguyen', email: 'Pat@Acme.example',
  company: 'Acme Claims, Inc.', property_id: 'home-3', stay_month: '2026-05', rating: '5',
  review: 'Fast, flexible and "always" responsive.\nThe family loved the home.', private_note: 'Invoice was late once.',
  home_city: 'Boston, MA', publish_as: 'company' };
let v = validate(partner);
check('valid feedback form', v.valid && v.lead.form_type === 'review' && v.lead.review.rating === 5, v.errors);
check('feedback is not an inquiry', v.lead.inquiry_type === '');
let r = build(v);
const cols = parseCsv(r.csv_line);
check('pasted line has the 11 reviews.csv columns', cols.length === 11, cols);
check('line keeps commas, quotes and the company name', cols[4] === 'Acme Claims, Inc.' && cols[6].includes('"always"')
  && cols[8] === 'company' && cols[0] === 'home-3' && cols[2] === '2026-05-01', cols);
check('private note never goes in the line', !r.csv_line.includes('Invoice was late'));
check('owner email has the review, the private note (marked) and the line', r.owner_email.htmlContent.includes('Private (never publish)')
  && r.owner_email.htmlContent.includes('reviews.csv') && r.owner_email.replyTo.email === 'pat@acme.example');
check('reviewer gets a thank-you', r.thanks_email.to[0].email === 'pat@acme.example' && r.thanks_email.textContent.startsWith('Hi Pat,'));
check('HubSpot contact has the company', r.contact_properties.company === 'Acme Claims, Inc.' && r.contact_properties.email === 'pat@acme.example');

v = validate({ ...partner, role: 'guest', company: '', publish_as: 'company' });
check('company name without a company falls back to first name + initial', build(v).csv_line.split(',')[4] === 'Pat N.', build(v).csv_line);
v = validate({ ...partner, role: 'monthly_guest', publish_as: 'anonymous' });
check('anonymous guest shows as "Verified guest"', parseCsv(build(v).csv_line)[4] === 'Verified guest');
v = validate({ ...partner, publish_as: 'private' });
r = build(v);
check('private feedback: no line to paste, marked private', r.owner_email.subject.includes('(private)')
  && !r.owner_email.htmlContent.includes('<pre') && r.owner_email.htmlContent.includes("don't add it"));
v = validate({ ...partner, rating: '', review: 'ok' });
check('missing rating and too-short review are rejected', !v.valid && v.errors.includes('a star rating')
  && v.errors.includes('a few words in your review'), v.errors);
check('honeypot still catches bots', validate({ ...partner, website: 'http://spam' }).is_bot);

const note = new Function('$input', '$', '$env', code('Build feedback note'))(
  { first: () => ({ json: { results: [{ id: '42' }] } }) }, () => ({ first: () => ({ json: build(validate(partner)) }) }), env)[0].json;
check('HubSpot note on the reviewer', note.note.associations[0].to.id === '42' && note.note.properties.hs_note_body.includes('5/5'));

const next = wf.connections['Newsletter sign-up?'].main[1].map(c => c.node);
const fb = wf.connections['Feedback?'].main.map(o => o.map(c => c.node));
check('routing: newsletter -> feedback? -> feedback branch / inquiry', next.includes('Feedback?')
  && fb[0].includes('Build feedback records') && fb[1].includes('HubSpot: find contact'), { next, fb });
console.log(fails ? `${fails} failed` : 'All checks passed');
process.exit(fails ? 1 : 0);
