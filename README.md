# NTStays Growth Ops

A production marketing and revenue-operations system for a three-home furnished-rental business, built with
**Claude Code**, **n8n** and the **Claude API**. It captures and attributes leads, triages them with AI under human
approval, and gives the marketing manager one place to see which channel actually converts.

- **Case study** (what it does, what broke, what I learned): [`docs/index.html`](docs/index.html), also served by GitHub Pages
- **Live site:** [ntstays.com](https://ntstays.com)
- **Dashboard demo** (made-up numbers, runs in the browser): [`docs/demo/`](docs/demo/)

> **The most boring marketing workflow you could automate end-to-end this week?**
> The monthly channel report. Pull each platform's numbers, reconcile them, chart them, write the summary, send it.
> Here it runs end to end: on the 1st of each month an n8n workflow computes the numbers in code, Claude writes the
> summary, a check blocks any draft with a number that isn't in the data, and the owner approves before it's sent.
> See `REPORT_*` in [`n8n/build_workflow.py`](n8n/build_workflow.py), its tests in
> [`n8n/scripts/test_report.js`](n8n/scripts/test_report.js) and the end-to-end run in
> [`n8n/scripts/e2e_report.py`](n8n/scripts/e2e_report.py).

## What's in here

| Path | What it is |
|---|---|
| [`n8n/build_workflow.py`](n8n/build_workflow.py) | Generates all 8 n8n workflows (179 nodes) as code: inquiries, AI chat, monthly channel report, payments, follow-ups, calendar sync, team data, error alerts |
| [`n8n/workflow/`](n8n/workflow/) | The generated workflow JSON, imported into n8n on deploy |
| [`n8n/scripts/`](n8n/scripts/) | Tests that run each workflow's own code with stand-ins for n8n (`test_*.js`), plus end-to-end tests against a real n8n and mock APIs (`e2e_test.py`, `e2e_report.py`, `mock/`) |
| [`worker/`](worker/) | Cloudflare Worker: verifies the Cloudflare Access login (JWT signature, audience, expiry), splits access by role, proxies the team pages to n8n. Fails closed. |
| [`site/`](site/) | The public website, plus the sign-in team pages in [`site/team/`](site/team/) (marketing dashboard, Log numbers) |
| [`stats/`](stats/) | Turns Airbnb, Vrbo and Booking.com exports into the stats behind the site and the dashboard. Runs on [`stats/sample/`](stats/sample/) (made-up data). |
| [`marketing/`](marketing/) | Brochure sources and a campaign link and QR builder |
| [`SETUP.md`](SETUP.md) | How the whole system is set up and operated |

## How the AI is kept honest

- **Structured output, checked in code.** Claude returns JSON against a schema; a check step rejects bad JSON, removes
  prices and booking confirmations, and flags anything unusual for the owner.
- **Every number is checked.** In the monthly report, code computes the figures and Claude only writes; a draft with any
  number not in the computed data is blocked, and every model call is logged with tokens, cost and time.
- **A person sends every email reply.** The AI drafts, the owner edits and presses Send in an n8n form.
- **Fail closed.** The team pages refuse everyone until Cloudflare Access is configured, on every hostname.
- **Audit trail.** Logged numbers are append-only; corrections are new rows that point at the old ones.
- **Tests gate deploys.** The workflows are rebuilt and compared with the committed JSON, then every suite runs.

## Run the tests

```bash
cd n8n && for t in scripts/test_*.js; do node "$t"; done   # n8n workflow code
node worker/test_worker.mjs                                   # sign-in guard
python stats/test_build_stats.py                              # stats builder
```

No accounts or keys needed. The end-to-end test (`n8n/scripts/e2e_test.py`) needs Docker; see SETUP.md.

## What was left out

This is a cleaned copy of a private repository, with a fresh history. Real platform exports, guest details,
credentials, internal notes and one email-only revenue figure are not included. The dashboard data here is built
from the made-up sample exports. Shared for review; not licensed for reuse.
