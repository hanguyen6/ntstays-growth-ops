// Where this visitor came from, for campaign tracking. Read once, on the first page of the visit:
//   - campaign tags on the link (utm_source, utm_medium, utm_campaign, utm_content, utm_term), or else
//   - the site that sent them (Google, Facebook, ...), or "direct" if they typed the address.
// Kept in this browser tab only (sessionStorage, no cookies) and sent along with a form or chat request,
// so each contact in the CRM shows its source. Forms read it with window.ntSource.get().
(() => {
  const KEY = 'ntstays-src';
  const clean = (v, n = 60) => (v || '').toString().trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9._-]/g, '').slice(0, n);
  // Known sites -> [source, medium]
  const SITES = [
    [/(^|\.)google\./, 'google', 'organic'], [/(^|\.)bing\.com$/, 'bing', 'organic'], [/(^|\.)duckduckgo\.com$/, 'duckduckgo', 'organic'],
    [/(^|\.)yahoo\.com$/, 'yahoo', 'organic'], [/(^|\.)facebook\.com$|^fb\.me$/, 'facebook', 'social'],
    [/(^|\.)instagram\.com$/, 'instagram', 'social'], [/(^|\.)linkedin\.com$|^lnkd\.in$/, 'linkedin', 'social'],
    [/^t\.co$|(^|\.)x\.com$|(^|\.)twitter\.com$/, 'x', 'social'], [/(^|\.)reddit\.com$/, 'reddit', 'social'],
    [/(^|\.)nextdoor\.com$/, 'nextdoor', 'social'], [/(^|\.)youtube\.com$/, 'youtube', 'social'],
    [/^mail\.google\.com$|(^|\.)outlook\.(live|office)\.com$|^mail\.yahoo\.com$/, 'email', 'email'],
  ];

  function detect() {
    const q = new URLSearchParams(location.search);
    const ref = (() => { try { return document.referrer ? new URL(document.referrer).hostname.replace(/^www\./, '') : ''; } catch (_) { return ''; } })();
    const own = ref === location.hostname.replace(/^www\./, '');
    const s = { source: clean(q.get('utm_source')), medium: clean(q.get('utm_medium')), campaign: clean(q.get('utm_campaign')),
      content: clean(q.get('utm_content')), term: clean(q.get('utm_term')),
      landing: location.pathname.slice(0, 100), referrer: own ? '' : clean(ref, 100) };
    if (!s.source && q.get('gclid')) { s.source = 'google'; s.medium = s.medium || 'ads'; }
    if (!s.source && q.get('fbclid')) { s.source = 'facebook'; s.medium = s.medium || 'social'; }
    if (!s.source && s.referrer) {
      const hit = SITES.find(([re]) => re.test(s.referrer));
      s.source = hit ? hit[1] : s.referrer;
      s.medium = s.medium || (hit ? hit[2] : 'referral');
    }
    if (!s.source) { s.source = 'direct'; s.medium = s.medium || 'none'; }
    return s;
  }

  let src = null;
  try { src = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (_) {}
  if (!src) {
    src = detect();
    try { sessionStorage.setItem(KEY, JSON.stringify(src)); } catch (_) {}
  }
  window.ntSource = { get: () => ({ ...src }) };
})();
