"""End-to-end test of the monthly channel report against a real n8n and the mock APIs.
Needs n8n running with the "team data" and "monthly channel report" workflows published, the data table
"ntstays_team_log" created, and mock/mock_server.py standing in for Claude and Brevo:
    python scripts/e2e_report.py
Env: N8N_URL (default http://localhost:5678), MOCK_URL (http://localhost:8765), TEAM_API_KEY, FOLLOWUP_KEY.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

N8N = os.environ.get("N8N_URL", "http://localhost:5678")
MOCK = os.environ.get("MOCK_URL", "http://localhost:8765")
TEAM_KEY = os.environ.get("TEAM_API_KEY", "local-test-team-key-0123456789")
RUN_KEY = os.environ.get("FOLLOWUP_KEY", "local-test-followup-key")
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        FAILS.append(name)


def req(method, url, body=None, headers=None, form=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    if form is not None:
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in form.items()]
        data = ("".join(parts) + f"--{boundary}--\r\n").encode()
        h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def team(method, body=None):
    code, raw = req(method, f"{N8N}/webhook/ntstays-team", body,
                    {"x-ntstays-key": TEAM_KEY, "x-ntstays-user": "mm@example.com"})
    return code, json.loads(raw or b"{}")


def state():
    return json.loads(req("GET", f"{MOCK}/_state")[1])


def wait_for(pred, secs=40):
    for _ in range(secs * 2):
        s = state()
        if pred(s):
            return s
        time.sleep(0.5)
    return state()


def tagged(s, tag):
    return [e for e in s["emails"] if tag in (e.get("tags") or [])]


def run_report(month):
    code, _ = req("POST", f"{N8N}/webhook/ntstays-report-run", {"month": month}, {"x-ntstays-key": RUN_KEY})
    return code


def submit(url, fields):
    req("GET", url)
    for _ in range(10):
        code, _ = req("POST", url, form=fields)
        if code != 409:
            return code
        time.sleep(1)
    return code


def main():
    req("POST", f"{MOCK}/_reset")
    # Numbers the team would log.
    for entry in [
        {"kind": "airbnb_stats", "month": "2026-08", "overall_conversion": "0.21", "listing_to_booking": "1.2"},
        {"kind": "airbnb_stats", "month": "2026-09", "overall_conversion": "0.68", "similar_overall": "0.29",
         "first_page_rate": "51.8", "search_to_listing": "25.89", "listing_to_booking": "2.62"},
        {"kind": "vrbo_stats", "property_id": "home-2", "as_of": "2026-09-28", "impressions": "471", "views": "76", "bookings": "1"},
        {"kind": "ff_stats", "property_id": "home-1", "as_of": "2026-08-28", "impressions": "1000", "listing_views": "150", "booking_inquiries": "40"},
        {"kind": "ff_stats", "property_id": "home-1", "as_of": "2026-09-28", "impressions": "1143", "listing_views": "159", "booking_inquiries": "47"},
        {"kind": "booking", "channel": "furnished_finder", "property_id": "home-1", "move_in": "2026-09-10", "move_out": "2026-12-10",
         "lead_type": "travel_nurse", "signed_on": "2026-09-05", "monthly_rent": "3000"},
    ]:
        code, body = team("POST", entry)
        if code != 200:
            check(f"logged {entry['kind']}", False, body)
    check("manual run without the key is ignored", req("POST", f"{N8N}/webhook/ntstays-report-run", {"month": "2026-09"})[0] in (200, 204))

    # Run 1: the owner approves an edited (but faithful) report.
    check("report run starts", run_report("2026-09") in (200, 204))
    s = wait_for(lambda s: tagged(s, "ntstays-report-review") or tagged(s, "ntstays-report-blocked"))
    review = tagged(s, "ntstays-report-review")
    check("the owner gets a checked draft for review", len(review) == 1, [e["subject"] for e in s["emails"]])
    check("nothing goes to the team before approval", not tagged(s, "ntstays-report"))
    if not review:
        return
    html = review[0]["htmlContent"]
    check("the draft shows the computed numbers table", "computed, not written by AI" in html and "0.68%" in html and "25.89%" in html)
    url = re.search(r'href="([^"]+form-waiting[^"]+)"', html).group(1)
    code = submit(url, {"field-0": "Send to the team", "field-1": "NTStays September report",
                        "field-2": "Airbnb conversion was 0.68%, above similar listings at 0.29%.\n\nGreat month."})
    check("the approval form accepts the decision", code in (200, 302), code)
    s = wait_for(lambda s: tagged(s, "ntstays-report"))
    sent = tagged(s, "ntstays-report")
    check("the approved report reaches the team, with the numbers table", len(sent) == 1 and "0.68%" in sent[0]["htmlContent"]
          and sent[0]["subject"] == "NTStays September report", [e["subject"] for e in sent])

    # Run 2: an edit that changes a number is blocked.
    run_report("2026-09")
    s = wait_for(lambda s: len(tagged(s, "ntstays-report-review")) >= 2)
    url = re.search(r'href="([^"]+form-waiting[^"]+)"', tagged(s, "ntstays-report-review")[-1]["htmlContent"]).group(1)
    submit(url, {"field-0": "Send to the team", "field-1": "NTStays September report", "field-2": "Airbnb conversion was 0.86%."})
    s = wait_for(lambda s: len(tagged(s, "ntstays-report-blocked")) >= 1)
    check("an edit that changes a number is blocked and the owner is told",
          len(tagged(s, "ntstays-report")) == 1 and any("0.86%" in e["htmlContent"] for e in tagged(s, "ntstays-report-blocked")))

    # The audit trail.
    time.sleep(2)
    code, body = team("GET")
    calls, reports = body.get("ai_calls", []), body.get("reports", [])
    check("every model call is logged with tokens and cost", len(calls) >= 2 and calls[0].get("output_tokens") == 300
          and calls[0].get("cost_usd") is not None, calls[:1])
    check("each outcome is logged (sent, then blocked edit)", [r.get("status") for r in reports][:2] == ["edit_blocked", "sent"], reports[:2])
    check("report runs stay out of Recent entries", not any(r.get("kind") in ("ai_call", "report") for r in body.get("recent", [])))


if __name__ == "__main__":
    main()
    print(f"\n{len(FAILS)} failed" if FAILS else "\nAll checks passed")
    sys.exit(1 if FAILS else 0)
