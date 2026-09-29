// Tests the results packs in the "Read review decision" step, without n8n or Docker:  node scripts/test_owner_pack.js
// Runs that step's code from workflow/ntstays-inquiry.json with stand-ins for n8n's $input, $ and $env.
// Rebuild first after editing build_workflow.py:  python build_workflow.py
const fs = require('fs');
const path = require('path');
const wf = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflow', 'ntstays-inquiry.json'), 'utf8'));
const code = wf.nodes.find(n => n.name === 'Read review decision').parameters.jsCode;
const run = (form, lead) => {
  const d = { lead, email_subject: 'Re: your inquiry', email_body: 'Hi Pat,\n\nThanks for reaching out.\n\nBest,\nHa', contact_id: '1' };
  const fn = new Function('$input', '$', '$env', code);
  return fn({ first: () => ({ json: form }) }, () => ({ first: () => ({ json: d }) }),
    { FROM_EMAIL: 'hello@ntstays.com', OWNER_NAME: 'Ha' })[0].json;
};
const base = { email: 'pat@example.com', first_name: 'Pat', last_name: 'Lee' };
const owner = { ...base, inquiry_type: 'property_management', is_service: true };
const cleaning = { ...base, inquiry_type: 'cleaning', is_service: true };
const insurer = { ...base, inquiry_type: 'stay', segment: 'insurance', is_service: false };
const nurse = { ...base, inquiry_type: 'stay', segment: 'travel_nurse', is_service: false };
const guest = { ...base, inquiry_type: 'stay', segment: '', is_service: false };
const send = { Decision: 'Send this reply' };
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail))); if (!ok) fails++; };
const isPdf = b64 => Buffer.from(b64 || '', 'base64').subarray(0, 5).toString() === '%PDF-';

let r = run(send, owner);
check('owner inquiry gets the owner pack', r.owner_pack === 'owner' && r.reply_email.htmlContent.includes('How our own homes perform'), r.owner_pack);
check('owner pack has stats and the Cranston case study', /\d\.\d\d ★/.test(r.reply_email.htmlContent) && r.reply_email.htmlContent.includes('$XXk'));
check('owner portfolio PDF attached', r.reply_email.attachment?.[0]?.name === 'NTStays-owner-brochure.pdf' && isPdf(r.reply_email.attachment[0].content));
check('text version has the pack and mentions the attachment', r.reply_email.textContent.startsWith('Hi Pat')
  && r.reply_email.textContent.includes('How our own homes perform') && r.reply_email.textContent.includes('portfolio is attached'));
check('no placeholders left', !JSON.stringify(r.reply_email).includes('__ATTACHMENT_LINE__'));
check('cleaning inquiry also gets the owner pack', run(send, cleaning).owner_pack === 'owner');

r = run(send, insurer);
check('insurance-housing inquiry gets the partner pack', r.owner_pack === 'partner'
  && r.reply_email.htmlContent.includes('Furnished whole homes for displaced families') && r.reply_email.htmlContent.includes('Direct billing'));
check('partner pack has no revenue figures', !r.reply_email.htmlContent.includes('$XXk') && !r.reply_email.textContent.includes('$XXk'));
check('partner portfolio PDF attached', r.reply_email.attachment?.[0]?.name === 'NTStays-partner-brochure.pdf' && isPdf(r.reply_email.attachment[0].content));

r = run({ ...send, 'Results pack': "Don't include" }, insurer);
check("Don't include: no pack, no attachment", !r.owner_pack && !r.reply_email.attachment && !r.reply_email.htmlContent.includes('displaced families'));
check('travel nurse stay gets no pack', !run(send, nurse).owner_pack && !run(send, nurse).reply_email.attachment);
check('regular guest stay gets no pack', !run(send, guest).owner_pack);
check("don't send still means don't send", run({ Decision: "Don't send (I'll handle it myself)" }, owner).decision === 'dont_send');
console.log(fails ? `${fails} failed` : 'All checks passed');
if (process.argv.includes('--preview')) {
  fs.writeFileSync(path.join(__dirname, '..', '_owner_preview.html'), run(send, owner).reply_email.htmlContent);
  fs.writeFileSync(path.join(__dirname, '..', '_partner_preview.html'), run(send, insurer).reply_email.htmlContent);
}
process.exit(fails ? 1 : 0);
