# NTStays lean setup: step by step

What you're building: an NTStays website where guests and property owners send inquiries. Each
inquiry is saved in HubSpot, scored and drafted by Claude, and emailed to you. You open a review
form, edit the draft if you want, and click Send. Nothing reaches a guest or owner until you do.

```
ntstays.com (Cloudflare Pages) ──form──▶ n8n.ntstays.com (your VPS: n8n + Caddy)
                                              ├─▶ HubSpot  (contact, notes, consent, lead status)
                                              ├─▶ Claude   (score + draft)
                                              └─▶ Brevo    (review email to you, approved reply to them)
hello@ntstays.com ──Cloudflare Email Routing──▶ your personal inbox
```

Budget: about $6-8 a month (server) + $12-15 a year (domain) + a few cents of Claude usage.
Allow 2-3 hours for the first setup. Do the steps in order.

---

## 1. Buy the domain and move DNS to Cloudflare (15 min)

1. Create a free account at cloudflare.com.
2. Buy `ntstays.com` (or your choice) through **Cloudflare Registrar**, or buy it elsewhere and add it to
   Cloudflare as a site (Cloudflare shows the two nameservers to set at your registrar).
3. If you pick a different domain, replace `ntstays.com` everywhere below, in `site/index.html`
   (`CONFIG`), and in `n8n/build_workflow.py` (`ALLOWED_ORIGINS`, then run `python build_workflow.py`).

## 2. Set up hello@ntstays.com (10 min)

1. Cloudflare dashboard → your domain → **Email** → **Email Routing** → enable.
2. Add a route: `hello@ntstays.com` → your personal email. Confirm the verification email.

This receives mail for free. Sending is done by Brevo (step 4).

## 3. Rent the server (15 min)

1. Create a small Linux VPS (Ubuntu 24.04, 2 GB RAM is enough). Hetzner, DigitalOcean, Vultr, or
   Lightsail all work at about $5-7 a month.
2. In Cloudflare DNS, add an **A record**: name `n8n`, value = the server's IP, **proxy status: DNS only**
   (grey cloud). Caddy needs this to get the HTTPS certificate.
3. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
4. Turn on the firewall, allowing only SSH and web traffic:
   ```bash
   ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
   ```

## 4. Create the accounts and keys (30 min)

| Service | What to do | Goes in `.env` as |
|---|---|---|
| **HubSpot** (free) | Sign up. Settings → Integrations → **Private Apps** → Create. Scopes: `crm.objects.contacts.read` and `crm.objects.contacts.write`. Copy the access token. If a note call later fails with 403, the error names the missing scope; add it. | `HUBSPOT_TOKEN` |
| **Claude API** | console.anthropic.com → API keys → create. Add a small credit balance and a monthly spend limit (e.g. $10). Pick a model ID from the models page. | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` |
| **Brevo** (free plan) | Sign up. **Senders, Domains & Dedicated IPs** → add and authenticate `ntstays.com` (it gives you DNS records: add them in Cloudflare). Add sender `hello@ntstays.com`. Settings → **SMTP & API** → API keys → create. | `BREVO_API_KEY` |

Authenticating the domain in Brevo (SPF/DKIM/DMARC) is what keeps your replies out of spam folders.
Don't skip it.

## 5. Start n8n on the server (20 min)

Copy the `n8n/` folder to the server (for example `scp -r n8n root@SERVER_IP:/opt/ntstays`), then:

```bash
cd /opt/ntstays
cp .env.example .env
nano .env                      # fill in every value; generate N8N_ENCRYPTION_KEY and UNSUBSCRIBE_SECRET with: openssl rand -hex 32
docker compose up -d
docker compose logs -f caddy   # wait for "certificate obtained", then Ctrl+C
```

Open **https://n8n.ntstays.com** right away and create the owner account (strong password), then turn
on two-factor login under your user settings. Until you do, anyone who finds the URL could claim it.

Import and turn on both workflows (the error-alert workflow first, because the inquiry workflow points to it):

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-error-alert.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-inquiry.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-availability.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-payments.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-followups.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-chat.json
docker compose exec n8n n8n publish:workflow --id=ntstaysErrorAlert01
docker compose exec n8n n8n publish:workflow --id=ntstaysInquiry01
docker compose exec n8n n8n publish:workflow --id=ntstaysAvailability01
docker compose exec n8n n8n publish:workflow --id=ntstaysPayments01
docker compose exec n8n n8n publish:workflow --id=ntstaysFollowups01
docker compose exec n8n n8n publish:workflow --id=ntstaysChat01
docker compose restart n8n
```

## 6. Publish the website (15 min)

1. Edit `site/index.html`: the `CONFIG` block (the webhook URL is already
   `https://n8n.ntstays.com/webhook/ntstays-inquiry`) and the `PROPERTIES` list: names, cities, sleeps,
   blurbs, photos, Airbnb and Vrbo links. Put photos in `site/img/` and reference them as `img/name.jpg`.
2. Edit the bracketed parts of `site/privacy.html` (date, mailing address, retention period).
3. Cloudflare dashboard → **Workers & Pages** → Create → **Pages** → **Upload assets** → drag in the
   `site` folder.
4. In the Pages project → **Custom domains** → add `ntstays.com` (and `www.ntstays.com`).

To update the site later, upload the folder again (or connect a GitHub repo for automatic deploys).

## 7. Test it for real (10 min)

1. On ntstays.com, send an inquiry using a second email address of yours. Pick "Property management".
2. Within a minute you should get a review email at `OWNER_EMAIL`. Check spam the first time.
3. Click **Review, edit & send**, change a sentence, choose **Send this reply**, submit.
4. Check the second inbox for the reply, and HubSpot → Contacts for the contact, notes, and lead status.
5. Subscribe with the newsletter form (use an address you can check). You should get the welcome email,
   and the contact should show lifecycle stage *Subscriber*, a consent note, and a "Welcome email sent" note.
6. Click **Unsubscribe** at the bottom of the welcome email, then the button on the page. You get an
   "unsubscribed" email and the contact gets an "Unsubscribed" note.

If something fails, open n8n → **Executions**: every run shows each step's input and output.

---

## Updating the server after a change

Pushing to `main` deploys the server automatically once the setup below is done: GitHub checks that the
workflow files match `build_workflow.py` and that every test passes, then runs `n8n/scripts/deploy.sh` on the
server (pull, import and publish every workflow, restart n8n, check it's back up). Watch it under the repo's
**Actions** tab (**Deploy n8n**); GitHub emails you if a deploy fails. To redeploy without a change, open
**Deploy n8n** there and press **Run workflow**. To deploy by hand instead:

```bash
bash /opt/ntstays/n8n/scripts/deploy.sh
```

### Automatic server deploys: one-time setup (15 min)

GitHub gets an SSH key that the server only accepts for running the deploy script: it can't open a shell,
read files or do anything else.

1. On your computer (PowerShell), make the key:
   ```powershell
   ssh-keygen -t ed25519 -f ntstays-deploy -N '""' -C github-deploy
   ```
   This creates `ntstays-deploy` (private) and `ntstays-deploy.pub` (public).
2. On the server, allow that key to run only the deploy script. Paste the contents of `ntstays-deploy.pub` in
   place of `PUBLIC_KEY`:
   ```bash
   echo 'command="bash /opt/ntstays/n8n/scripts/deploy.sh",restrict PUBLIC_KEY' >> /root/.ssh/authorized_keys
   ```
   Then print the server's own key line, which lets GitHub be sure it's talking to your server (put your
   server's IP in place of `SERVER_IP`):
   ```bash
   echo "SERVER_IP $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
   ```
3. On GitHub: the repo → **Settings → Secrets and variables → Actions → New repository secret**, three times:
   - `DEPLOY_HOST`: the server's IP
   - `DEPLOY_SSH_KEY`: the whole contents of `ntstays-deploy` (the private file, including the BEGIN/END lines)
   - `DEPLOY_KNOWN_HOSTS`: the line printed in step 2
4. Delete both key files from your computer; GitHub now holds the only copy of the private key.
5. Test it: **Actions → Deploy n8n → Run workflow**. It should finish green in about two minutes.

To revoke access, delete the `github-deploy` line from `/root/.ssh/authorized_keys` on the server.

The deploy waits until n8n is back up. Workflow and `docker-compose.yml` changes deploy this way; `.env`
never does (secrets aren't in git).

Re-importing replaces the workflow with the repo version, so make workflow changes in `build_workflow.py`
(not in the n8n editor), or they'll be overwritten on the next import. After editing `.env`, use
`docker compose up -d --force-recreate n8n` (a plain restart does not reload `.env`).

Website changes (`site/`) need only `git push`; Cloudflare redeploys automatically.

---

## Test locally first (optional, no accounts needed)

On any machine with Docker:

```bash
cd n8n
cp .env.mock .env
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile mock up -d
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-error-alert.json
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-inquiry.json
docker compose exec n8n n8n publish:workflow --id=ntstaysErrorAlert01
docker compose exec n8n n8n publish:workflow --id=ntstaysInquiry01
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-availability.json
docker compose exec n8n n8n publish:workflow --id=ntstaysAvailability01
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-payments.json
docker compose exec n8n n8n publish:workflow --id=ntstaysPayments01
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-followups.json
docker compose exec n8n n8n publish:workflow --id=ntstaysFollowups01
docker compose exec n8n n8n import:workflow --input=/workflows/ntstays-chat.json
docker compose exec n8n n8n publish:workflow --id=ntstaysChat01
docker compose -f docker-compose.yml -f docker-compose.local.yml restart n8n
python scripts/e2e_test.py        # 84 checks: bots, spam check, subscribe, send (results pack, payment link), paid booking, follow-ups, chat, feedback, availability
                                  # contact, property-type mismatch, failure alert, repeat sign-up, unsubscribe
```

The mock stands in for HubSpot, Claude, and Brevo. `curl localhost:8765/_state` shows everything
"sent". To try the site locally, change `WEBHOOK_URL` in `site/index.html` to
`http://localhost:5678/webhook/ntstays-inquiry` and run `python -m http.server 8080` in `site/`.

## How the workflow behaves

| Situation | What happens |
|---|---|
| Spam bot fills the hidden field | Accepted quietly, nothing saved, no cost |
| Missing email, name, or message | Website shows what to fix (400) |
| Newsletter sign-up | Consent note saved (time, page, wording). New contacts become *Subscriber*; existing leads and customers keep their stage and name. A welcome email goes out once (not again if they sign up twice), with a one-click unsubscribe link and your mailing address. No AI |
| Unsubscribe link | Opening it shows a confirm button (so email link scanners can't unsubscribe anyone). Confirming (or Gmail's one-click unsubscribe) logs an *Unsubscribed* note on the contact and emails you |
| Real inquiry | Visitor gets an instant thank-you. Then: HubSpot lookup, Claude score + draft, checks (wording like "discount" or "is booked", length, name, complaint flags), contact upsert, note, opt-in consent note if ticked, review email to you |
| You choose **Send** | Your edited (or original) reply goes out from hello@ntstays.com, logged on the contact, lead status In Progress |
| Owner-service or insurance-housing inquiry, you choose **Send** | A **results pack** and a **one-page portfolio (PDF)** are added to your reply: the **owner pack** (ratings, stays, guest origins, the Cranston case study with its 2024 revenue range) for management, staging, renovation and cleaning inquiries, or the **partner pack** (homes, bedrooms, direct billing, reviews; no revenue) for inquiries from the insurance-housing page. Choose "Don't include" at the bottom of the review form to leave it out |
| You choose **Don't send**, or 3 days pass | Nothing is sent; the decision is logged |

| Any step fails (expired key, API change, Brevo limit...) | The **NTStays: error alerts** workflow emails you the failed step, the error, a likely fix, and a link to the run |

Tiers: owner-service inquiries are **hot** from score 60 (stays from 70), **warm** from 40.

Checks flagged in the review email: wording like "discount" or "is booked", long replies, missing first
name, complaints or refunds (needs attention), check-in in the past, and a property
type in the message that disagrees with the form (e.g. "condo" vs "Single-family home").

## Stats from Airbnb, Vrbo and Booking.com (photos, reviews, revenue, guest origins)

Airbnb, Vrbo and Booking.com only give API access to approved software partners (channel managers), and all
three forbid scraping. So this works from the exports you download from your own host accounts, about once a
month. Everything runs on your computer; nothing new on the server.

```
platform exports ──▶ stats/exports/ (git-ignored) ──python stats/build_stats.py──┬─▶ stats/out/dashboard.html  private: revenue, occupancy, channels, origins
                                                                                  └─▶ site/data/stats.json      public: ratings, featured reviews, where guests come from
```

**1. Download the exports** into `stats/exports/` (any file names; `.csv`, `.xls` or `.xlsx`; the script
recognizes each format by its columns):

| Platform | Where (menus move around; look for "export" or "download") | What it gives you |
|---|---|---|
| Airbnb | Menu → **Earnings** (or Transaction history) → pick the dates → **Export CSV**. Do both the paid and upcoming tabs. | Stays, dates, nights, gross, fees, payout |
| Booking.com | Extranet → **Reservations** → date range → **Download** (.xls is fine). Includes property name and location for every listing. | Stays, total payment, commission, status |
| Booking.com reviews | Extranet → **Guest reviews** → download (CSV). Matched to the home through the reservation number. | Score /10, category scores, positive/negative text |
| Vrbo | **Reservation Manager → Financial Reporting** → set the dates, switch to "Stays within this date range", Refresh → **Download** as CSV. Several rows per reservation (payments, reversals) are added up. | Stays, gross, deductions, payout |
| Vrbo reviews | No download: select everything on the **Reviews** page, copy, and paste into an Excel sheet (column A). Save as `.xlsx`. | Score /10, title, text |
| Airbnb reviews | No download: open your profile's reviews, select all, copy, paste into Word, save as `.docx`. Each review is linked to its stay by first name + month (most link; the rest count in the overall rating only). | Rating /5, text, **guest's home city** |
| Medium-term leases | Copy `stats/leases-template.csv` to `stats/exports/leases.csv`, replace the example rows: one row per lease (Furnished Finder, insurance placement, direct...), `monthly_rent` + dates is enough. | Revenue and occupancy the platforms never see |
| Direct bookings | Fill in the format of `stats/sample/direct-bookings.csv`. | Anything booked outside the platforms |

Match listings to homes with the `match` text in `stats/config.json`: a piece of the listing name, city,
or the Vrbo property ID (IDs keep street addresses out of the repo).

Optional, by hand:

- `guest_origins.csv` (`confirmation,city,region,country`): none of these exports include where guests live
  (except the Booking.com CSV format with "Booker country", if your account offers it). Each guest profile shows
  it; one line per stay fills in "where guests come from".
- `reviews.csv` (`property,platform,date,rating,display_name,origin,text,feature`): for reviews typed in by
  hand, such as Airbnb's (rating out of 5).

**Which reviews go on the website:** the dashboard lists every review with its code. Put the codes you want in
`feature_codes` in `stats/config.json`. Only 4★+ reviews with text are shown, as first name + initial, with the
positive text only.

See `stats/sample/` for every format. Try it with made-up data (writes only the dashboard):

```bash
python stats/build_stats.py --exports stats/sample --today 2026-09-26
```

**2. Map listings to your homes:** in `stats/config.json`, give each property its `match` text (a piece of the
listing name as it appears in the exports) and `hosting_since` (first bookable day, for occupancy). Ids must
match `PROPERTIES` in `site/index.html`. Unmatched listings show as a warning at the top of the dashboard.

**3. Build:**

```bash
python stats/build_stats.py
```

Open `stats/out/dashboard.html` in your browser: gross revenue and payout, occupancy, average nightly rate,
RevPAR, average stay and booking lead time (last 12 months and all time), monthly revenue by property, channel
mix and platform fees, the next 90 days on the books, where guests come from, and ratings per property. Keep
it private: it's git-ignored and never deployed.

**4. Publish:** check `site/data/stats.json` (the only thing that goes public: no guest names, no revenue),
then commit and push. The site shows ratings on each home's card and a "What guests say" section with the
featured reviews and numbers like "guests from 14 states and 6 countries". Until that file exists the section
stays hidden. `public` in `config.json` controls what's included (occupancy is off by default).

**Photos:** copy your original photos into `photos/home-1/`, `photos/home-2/`, `photos/home-3/` (git-ignored),
named in the order you want, with a caption: `01-living-room.jpg`, `02-kitchen.jpg`... (no caption for names
like `IMG_1234`). Then:

```bash
python tools/prepare_photos.py
```

It turns each photo upright, makes 1600 px and 800 px copies in `site/img/<id>/`, strips all metadata (phone
photos carry GPS coordinates of the home), and writes `site/img/photos.json`. The first photo is the card's
cover; the rest are behind previous/next buttons. Up to 20 per home; about 8-12 is plenty. iPhone HEIC files
need `pip install pillow-heif` first. Preview locally (`python -m http.server 8080` in `site/`), then commit and
push. Use photos you or your own photographer took, not downloads from the listing pages (photos made by a
platform's photography program may belong to the platform).

Tests: `python stats/test_build_stats.py` (parsing of each platform, the numbers, and that no guest names or
revenue reach the public file).

## Calendar sync (availability on the website)

The "NTStays: availability" workflow reads each home's calendar export links (Airbnb, Vrbo, Booking.com) and
publishes only the booked date ranges at `https://n8n.ntstays.com/webhook/ntstays-availability`. The website then
shows a "See availability" calendar on each home, and the request forms say whether the chosen dates look open.
Homes without a calendar link simply don't show the button.

1. Copy each listing's export link: Airbnb (Listing > Availability > Connect calendars > Export calendar), Vrbo
   (Calendar > Import & export > Export), Booking.com (Rates & availability > Sync calendars > Export).
2. On the server, add them to `/opt/ntstays/n8n/.env`, one line per home, several links separated by spaces:
   ```
   ICAL_HOME_1=https://www.airbnb.com/calendar/ical/....ics?t=... https://www.vrbo.com/icalendar/....ics
   ICAL_HOME_2=...
   ICAL_HOME_3=...
   ```
   Keep them private: anyone with a link sees your booked dates. They never go in the repo or on the site.
3. `docker compose up -d --force-recreate n8n` (a plain restart doesn't reload `.env`), then import and publish
   the workflows as in "Updating the server after a change".
4. Check: open `https://n8n.ntstays.com/webhook/ntstays-availability`; you should see date ranges per home.

Airbnb marks both bookings and your own blocks as "Not available". If a home is blocked on the platforms but open
to direct monthly guests, add it to `ICAL_IGNORE_BLOCKS` (e.g. `ICAL_IGNORE_BLOCKS=home-2`) so only real
reservations show as booked. Dates refresh every 30 minutes (`AVAILABILITY_CACHE_MINUTES`). Test without Docker:
`node n8n/scripts/test_availability.js`.

## Spam protection (Cloudflare Turnstile)

Every form (contact, newsletter, travel-nurse and insurance requests, feedback) has an invisible Cloudflare
Turnstile check; it only shows a checkbox if something looks suspicious. The server verifies each form's token with
Cloudflare before anything reaches HubSpot, Claude or email; a failed check gets "please reload and try again".

1. Cloudflare dashboard > **Turnstile** > **Add widget**: name "NTStays forms", domains `ntstays.com` (add
   `localhost` for local testing), mode **Managed**. You get a **site key** (public) and a **secret key**.
2. Put the site key in `site/assets/turnstile.js` (`const SITE_KEY = '...'`), commit and push.
3. Put the secret in the server's `.env` as `TURNSTILE_SECRET=...` and run `docker compose up -d --force-recreate n8n`.

Do steps 2 and 3 together: with only the secret set, every form is refused; with neither, the check is off.

## Website assistant (AI chat)

An "Ask us" chat bubble on the homepage and both landing pages. The "NTStays: website assistant" workflow answers
with Claude from a fixed set of facts (`ASSISTANT_FACTS` and `CHAT_RULES` in `n8n/build_workflow.py`, plus
`BUSINESS_FACTS` / `PROPERTY_FACTS` from `.env`) and today's availability from the calendar sync.

- **Rules** (in the prompt, and checked again in code): no prices (a price in an answer is replaced by "we send a
  personal quote"), no booking confirmations, no sensitive data, on topic only.
- **Requests to you:** when a visitor wants to book or talk to you, the assistant collects name, email and dates, asks
  "Shall I send this to our team?", and only after a yes posts a normal inquiry (with a chat summary and transcript)
  into your review flow. One request per chat.
- **Limits:** the first message of a chat passes the Turnstile spam check; the server then signs the session.
  30 visitor messages per chat, `CHAT_DAILY_LIMIT` (default 300) messages per day for the whole site, 1,000
  characters per message, the last 12 messages sent to the model. The fixed prompt is cached, so repeat messages
  cost less.
- **Model:** `CHAT_MODEL` if set, else `CLAUDE_MODEL`. At Haiku rates a typical chat costs a fraction of a cent to
  a few cents.
- **Updating what it knows:** edit `ASSISTANT_FACTS` (keep it true), rebuild the workflow, import and publish.

After importing and publishing, open ntstays.com and try the bubble: ask about a home, a date, and "send this to our
team" with your own email. Test without Docker: `node n8n/scripts/test_chat.js`.

## Follow-ups (payment reminders, thank-yous, extension offers)

The "NTStays: follow-ups" workflow checks Stripe every morning at 9:00 and drafts follow-ups for you to approve,
the same way inquiry replies work (an email with the draft and a "Review, edit & send" button):

| Follow-up | When | What the guest gets |
|---|---|---|
| Payment reminder | A payment link was sent 2+ days ago, isn't paid, and the stay hasn't started | A friendly nudge with the payment link |
| Thank-you | The day after check-out | Thanks, and the feedback link (ntstays.com/review) |
| Extension offer | Two weeks before a stay of 28+ nights ends | "Need a few more weeks? Reply and we'll check the calendar" |

Nothing reaches a guest until you choose Send; the review links expire after 5 days. Each payment link gets one
reminder at most. Only stays paid through Stripe payment links are covered. Wording is in `FU_DRAFT_JS` in
`n8n/build_workflow.py`. To run the morning check now (for testing), on the server:
`curl -X POST -H "x-ntstays-key: <UNSUBSCRIBE_SECRET from .env>" http://localhost:5678/webhook/ntstays-followups-run`
(inside the n8n container) or from anywhere via `https://n8n.ntstays.com/webhook/ntstays-followups-run`.
Test without Docker: `node n8n/scripts/test_followups.js`.

## Payments and direct bookings (Stripe)

**How it works.** When you approve a reply in the review form, enter an **Amount to charge (USD)** (and check
**Payment for**, pre-filled with the dates). The workflow creates a one-time Stripe payment link for that amount and
adds a "Pay securely by card" button to your reply. Leave the amount empty for a normal reply. When the guest pays,
Stripe notifies the "NTStays: payments" workflow, which checks the payment with Stripe, emails the guest a booking
confirmation and you a "payment received" note, logs it in HubSpot and marks the contact as a customer.

Stripe is the booking record: each payment carries the home and dates. Include any taxes and fees in the amount you
enter (on direct stays of about a month or less you collect occupancy taxes yourself; ask your accountant).

**Set up (test mode first):**

1. In Stripe, switch to **Test mode**. Developers > API keys > **Create restricted key**, name it "NTStays n8n",
   and set: **Products: Write, Prices: Write, Payment Links: Write, PaymentIntents: Read** (everything else None).
   Payment Links: Write also lets the follow-ups read open links and mark reminders as sent.
2. Developers > Webhooks > **Add endpoint**: `https://n8n.ntstays.com/webhook/ntstays-stripe`, event
   **checkout.session.completed**.
3. On the server, add to `.env` (then `docker compose up -d --force-recreate n8n`):
   ```
   STRIPE_SECRET_KEY=rk_test_...
   ```
4. Import and publish the workflows (see "Updating the server after a change").
5. Test: send yourself a stay request, approve it with an amount, pay with Stripe's test card
   **4242 4242 4242 4242** (any future date, any CVC). You should get the confirmation email and the payment email.
6. Go live: repeat steps 1-2 in live mode, replace the key with the live `rk_live_...` key, recreate n8n.

The key is restricted on purpose: it can create prices and payment links and read payments, but can't refund, pay
out, or read your customers. Never paste it into chat or the repo.

**Direct bookings on Airbnb and Vrbo (two-way blocking).** Each home has a calendar feed of its paid direct
bookings (dates only): `https://n8n.ntstays.com/webhook/ntstays-direct-calendar?home=home-1` (`home-2`, `home-3`).
Import it once per listing, so a direct booking blocks those dates on the platforms:
- Airbnb: Listing > Availability > **Connect calendars** > **Import calendar**, paste the link, name it "NTStays direct".
- Vrbo: Calendar > **Import & export** > **Import**, paste the link.
- Booking.com: Rates & availability > **Sync calendars** > import.

The platforms refresh imported calendars every few hours, so block a same-day booking by hand too. Stays paid
another way (Zelle, insurer invoices) aren't in the feed: block those dates on the platforms yourself.

Test without Docker: `node n8n/scripts/test_payments.js`.

## Collecting reviews (feedback form)

Send past guests and partners (insurance companies, adjusters, housing providers) this link:
**https://ntstays.com/review**. It's hidden from search engines and not linked from the site.

They choose who they are, the home, a star rating, their review, an optional private note ("what could we do
better", never published), their home city (adds a route to the guest map), and how they'd like to be named:
first name and initial, company name (partners), no name, or private feedback only.

What happens: the reviewer is saved in HubSpot with a note, they get a thank-you email, and you get an email with
the review and a line ready to paste. To publish a review:

1. Paste the line into `stats/exports/reviews.csv` (create it with this header if it doesn't exist):
   `property,platform,date,rating,display_name,origin,text,feature,publish_as,role,code`
2. To feature it on the website, add its code (for example `FB-20261002-pat`) to `feature_codes` in
   `stats/config.json`. Only 4-star-and-up reviews with text are shown; private feedback is never published.
3. Run `python stats/build_stats.py`, check `site/data/stats.json`, then commit and push.

No AI is used for feedback. Test without Docker: `node n8n/scripts/test_feedback.js`.

## Portfolios and results packs (email only)

Two one-page portfolios for business clients, in `marketing/`:

| Portfolio | For | Shows |
|---|---|---|
| `owner-brochure.html` | Owners (management, staging, renovation, cleaning) | Photos, rating, stays, guest origins, nightly vs monthly, the Cranston case study (with a revenue range), services |
| `partner-brochure.html` | Insurers, adjusters, housing providers | The three homes with bedrooms and sleeps, rating, stays, why partners work with us (direct billing), a route map of where guests come from, reviews |

Build the PDFs (numbers and the map come from `site/data/stats.json`; it warns if one runs over a page):

```bash
python tools/build_brochure.py
```

Then rebuild the workflow so replies carry the new PDFs and numbers, and update the server ("Updating the server
after a change"):

```bash
python n8n/build_workflow.py
```

The workflow embeds both PDFs, so they never need a public link. They include business figures, so send them to
people who asked; don't link them from the site. Pack wording and the Cranston figures are in `CASE_STUDY` and
`results_packs()` in `n8n/build_workflow.py`. Test without Docker: `node n8n/scripts/test_owner_pack.js`.

## Campaign tracking (where leads come from)

Every request from the website (forms and chat) and every newsletter sign-up records where the visitor came from:
the **campaign link** they clicked, or else the site that sent them (Google, Facebook, ...), or "direct". It shows in
the owner review email ("Came from"), in the HubSpot note, and, once set up below, in fields on the HubSpot contact.
The website keeps it only for the visit, in the browser tab, with no cookies (the privacy page says so). The request
forms also ask an optional "How did you hear about us?", which covers word of mouth and repeat guests.

**Make campaign links** with `marketing/campaign-links.html` (open the file in a browser): pick the page, the source
(`facebook`, `hospital-board`, `flyer`), the kind of channel and a campaign name (`nurses-2026-10`). It gives the link
and a QR code for print, and lists the naming rules. A contact keeps the first source it came from.

**One-time HubSpot setup (10 min)**, so sources (and the lead type: travel nurse, insurance, owner…) become filterable
fields on each contact:

1. HubSpot → **Settings → Properties → Contact properties → Create property**, six times, each in the group
   "Contact information", field type **Single-line text**, with exactly these internal names:

   | Label | Internal name |
   |---|---|
   | NTStays source | `ntstays_source` |
   | NTStays medium | `ntstays_medium` |
   | NTStays campaign | `ntstays_campaign` |
   | NTStays first page | `ntstays_first_page` |
   | Heard about us | `ntstays_heard_about` |
   | NTStays lead type | `ntstays_lead_type` |

2. Then turn them on in `/opt/ntstays/n8n/.env` with `HUBSPOT_SOURCE_FIELDS=on` and run
   `docker compose up -d --force-recreate n8n`. (Before the fields exist, leave it off: HubSpot refuses
   unknown fields and the request would fail.)

**Results per campaign:** in HubSpot, filter contacts by "NTStays campaign" or "NTStays source" and look at Lead status
(New = inquiry, In progress = your reply was sent) and Lifecycle stage (Customer = paid). For the dashboard, export them
monthly: **Contacts → Export** (all contacts, CSV, including the columns Create Date, Lead Status, Lifecycle Stage and
the six NTStays fields), save the file in `stats/exports/` and run `python stats/build_stats.py`. The private dashboard's
**Website pipeline** section then shows inquiries → quoted → booked by source, campaign, "heard about us" and month.
The export has names and emails: it stays in `stats/exports/` (never committed); the dashboard shows only counts.

**Airbnb's own funnel:** each month, Airbnb → **Performance** → download the monthly report (CSV) and save it in
`stats/exports/` under any name (the first line says which month it is; downloading a month again replaces it). The
dashboard's **Airbnb listing performance** section shows bookings, nights and booking value per home, and per listing
the view → contact and contact → book rates. Airbnb has no export of these for other date ranges and no API for hosts.

## Marketing dashboard (sign-in, for the marketing manager)

**ntstays.com/team/marketing** shows pipeline conversion for the channels that bring bookings today, with a time-range
filter (the website is new, so direct-booking metrics wait until it has traffic; its tracking already runs):

1. **Airbnb pipeline**: overall conversion vs similar listings, search → listing → booking, first-page impression rate
   and bookings made, by month (Airbnb's Booking conversion page, logged monthly; bookings from the monthly reports).
2. **Vrbo pipeline**: search impressions → property views → bookings per home (Vrbo's Ranking metrics, last 30 days,
   logged monthly per property).
3. **Furnished Finder pipeline**: impressions → listing views → booking inquiries → leases, inquiry → lease rate, new
   tenant contacts by month and cost per lease (Listing Performance panel, logged monthly; leases logged).
4. **Bookings by channel**: stays or nights per month from Airbnb, Furnished Finder, Vrbo and Booking.com.
5. **Channel value**: revenue share and fee % by channel (platform fees from the exports, Furnished Finder's yearly fee,
   0% direct). Percentages only; the amounts behind them are in the page's data (behind the sign-in), and Furnished
   Finder/direct leases count when their monthly rent is logged.

It shows counts, rates and percentages only (no names, emails or dollar amounts). To see how it works without data, open
`ntstays.com/team/marketing?demo=1` once signed in, or `stats/out/marketing.html` on your computer after running the stats.

**Sign-in (Cloudflare Access, free for up to 50 people; one-time setup, 15 min).** People sign in with their email and
a one-time code; nobody else can open `/team/…`. The site's Worker (`worker/index.js`) also refuses `/team/…` unless
Cloudflare Access has signed the visitor in, so the page stays private on the `workers.dev` address too, and even
before Access is set up.

1. Cloudflare dashboard → **Zero Trust** (first time: pick a team name, e.g. `ntstays`, and the **Free** plan).
2. **Settings → Authentication → Login methods**: make sure **One-time PIN** is on.
3. **Access → Applications → Add an application → Self-hosted**:
   - Name `NTStays team`, session duration `1 week`.
   - Domain `ntstays.com`, path `team`; add a second destination with the same domain and path `team/*`.
   - Policy: name `Team`, action **Allow**, include **Emails**: your email and the marketing manager's.
   - Save, then copy the **Application Audience (AUD) Tag** from the application's overview.
4. Your team domain is `<team name>.cloudflareaccess.com` (shown under Zero Trust → Settings).
5. Put both in `wrangler.jsonc` under `"vars"` (`ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`), commit and push (or send them
   to Claude). They aren't secrets.
6. Test in a private window: `ntstays.com/team/marketing` asks for your email, emails a code, then shows the page.
   An email that isn't on the list gets no code.

To add or remove someone later, edit the policy's email list (step 3); no code change.

**Team home and who sees what.** Every public page's footer has a small "Team" link to **ntstays.com/team**, which
shows the signed-in person the pages they may open. The Access policy decides who can sign in at all; two optional
lists decide which page each person gets. Set them in Cloudflare → Workers & Pages → ntstays → Settings → Variables
and secrets → Add → type **Secret** (so deploys keep them), comma-separated emails (or `@yourcompany.com` for a whole
domain):

- `TEAM_LOG_EMAILS`: who can open **Log numbers** and save entries
- `TEAM_DASHBOARD_EMAILS`: who can open the **Marketing dashboard**

Leave a list unset and everyone signed in can use that page. Put yourself on both. Someone signed in but not on a
list gets a "No access" page naming their email.

**Log numbers page (ntstays.com/team/log).** Same sign-in. The sales or marketing manager logs what the platform
exports don't have: each **booking** from Furnished Finder, the website, referrals, repeat guests or insurance and
housing companies (channel, home, dates, guest type; email and rent optional, never shown on the dashboard), and once
a month **Furnished Finder's Listing Performance numbers** for each of the three listings (one per home; all numbers as shown: impressions, listing views, favorites
and shares cover the last 90 days; booking inquiries, direct messages, phone reveals and tenant leads are totals since
joining, so the dashboard uses the month-to-month difference; there's no export or API) and **Airbnb's booking
conversion rates** for the month (Performance → Conversion → Booking conversion, all listings, dates set to that
month; past months can be added too; optionally also one home's listings). The dashboard has a Home filter and
compares the three Furnished Finder listings. Entries show on the dashboard right away.
Mistakes are removed on the page (kept, crossed out). Entries are stored in n8n (workflow "NTStays: team data").

One-time setup for it (10 min):

1. In n8n (n8n.ntstays.com) → **Overview → Data tables → Create data table**, named exactly `ntstays_team_log`, with
   four **String** columns: `kind`, `data`, `entered_by`, `entered_at`.
2. Make a key: `openssl rand -hex 32`. Add it to `/opt/ntstays/n8n/.env` as `TEAM_API_KEY=...` and run
   `docker compose up -d --force-recreate n8n`.
3. Give the Worker the same key: Cloudflare dashboard → **Workers & Pages → ntstays → Settings → Variables and
   secrets → Add → Secret**, name `TEAM_API_KEY`, the same value. (A secret stays through every deploy.)
4. Put the yearly Furnished Finder fee for all three listings together in `stats/config.json` → `"marketing_costs"`,
   e.g. `"furnished-finder": 597`, for cost per lease (a single home is shown a third of it); run the stats and push.

**Updating the numbers (monthly, with the stats):** save the HubSpot contacts export and the Airbnb reports in
`stats/exports/`, put campaign costs in `stats/config.json` → `"marketing_costs"`, then run
`python stats/build_stats.py`. It writes `site/team/marketing-data.json`; commit and push it to update the page.
Direct and Furnished Finder stays come from the Log numbers page (don't also keep them in a bookings file in
`stats/exports/`, or they count twice).

## Monthly channel report (AI summary, checked and approved)

On the 1st of each month at 8:00 the workflow "NTStays: monthly channel report" computes last month's numbers in code
(logged Airbnb rates, Vrbo and Furnished Finder numbers, leases, and the export-based stays and fees), has Claude write
a short summary, and **blocks the draft unless every number in it appears in the computed data** (no dollar amounts,
missing inputs named). You get the draft and the numbers table by email with a **Review & send** form; you can edit the
text, and an edit is checked again before it goes to `REPORT_RECIPIENTS` (default: `OWNER_EMAIL`). A blocked draft
emails you the reasons and the numbers instead. Every model call (tokens, cost, time, checks) and every outcome is logged
in the `ntstays_team_log` table and shown under **Monthly report runs** on the marketing dashboard.

- Needs: the data table and `TEAM_API_KEY` from the Log numbers setup; optional `REPORT_RECIPIENTS`, `REPORT_MODEL`.
- Run it now for any month: `curl -X POST https://n8n.ntstays.com/webhook/ntstays-report-run -H "x-ntstays-key: $FOLLOWUP_KEY"
  -H "Content-Type: application/json" -d '{"month":"2026-09"}'` (on the server, the key is `FOLLOWUP_KEY` or
  `UNSUBSCRIBE_SECRET` from `.env`).
- The export-based numbers are built into the workflow from `site/team/marketing-data.json`: refresh the stats and push,
  and the deploy rebuilds it.
- Tests: `node n8n/scripts/test_report.js`; end to end against a local n8n and the mock APIs: `python n8n/scripts/e2e_report.py`.

## Marketing rules to follow

- Only email people who opted in: the newsletter form, the checkbox on the contact form, or a sign-up
  card in your homes. Never import Airbnb or Vrbo guest details for marketing; their policies forbid it.
- Every marketing email needs an unsubscribe link and NTStays' mailing address. The welcome email includes
  both (`BUSINESS_ADDRESS` in `.env`); HubSpot adds them to its marketing emails.
- When you get an "unsubscribed" email, don't email that person marketing again. If you send newsletters from
  HubSpot, also open the contact and choose **Communication subscriptions → Unsubscribe from all email**.
- To change the welcome email's wording, edit `PARAGRAPHS` in `WELCOME_JS` in `n8n/build_workflow.py`, run
  `python n8n/build_workflow.py`, then deploy as above.
- Replies to someone's own inquiry are fine to send; they asked you a question.

## Costs to watch

- Claude: set a monthly spend limit in the console. Expect cents per month at this volume.
- Brevo free plan: a daily sending limit that is far above what this workflow needs.
- HubSpot free: marketing emails carry HubSpot branding and have a monthly cap; upgrade only if needed.
