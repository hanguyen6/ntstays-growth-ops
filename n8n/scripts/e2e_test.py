"""End-to-end test of the NTStays inquiry workflow against the mock APIs.

Needs n8n running with the workflow published and mock/mock_server.py running
(see SETUP.md, "Test locally first"). Then:  python scripts/e2e_test.py
"""
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

N8N = os.environ.get("N8N_URL", "http://localhost:5678")
MOCK = os.environ.get("MOCK_URL", "http://localhost:8765")
HOOK = f"{N8N}/webhook/ntstays-inquiry"
ADDRESS = os.environ.get("BUSINESS_ADDRESS", "123 Test St, Boston, MA 02101")
FAILS = []


def req(method, url, body=None, headers=None, form=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    if form is not None:  # multipart, like the n8n review form
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in form.items()]
        data = ("".join(parts) + f"--{boundary}--\r\n").encode()
        h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def js(raw):
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {}


def state():
    return js(req("GET", f"{MOCK}/_state")[2])


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def wait_for(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        s = state()
        if pred(s):
            return s
        time.sleep(0.5)
    return state()


def review_url_for(s, email):
    for e in reversed(s["emails"]):
        if e.get("replyTo", {}).get("email") == email and "ntstays-owner-review" in (e.get("tags") or []):
            m = re.search(r'href="([^"]+form-waiting[^"]+)"', e["htmlContent"])
            return m.group(1) if m else None
    return None


def submit_review(url, decision, subject="", body="", note="", pack="", amount="", pay_for=""):
    """Open the review form (GET must not submit anything), then POST it like a browser would."""
    code, _, html = req("GET", url)
    fields = {"field-0": decision, "field-1": subject, "field-2": body, "field-3": note, "field-4": pack,
              "field-5": amount, "field-6": pay_for}
    for _ in range(10):
        code, _, raw = req("POST", url, form=fields)
        if code != 409:
            return code, html
        time.sleep(1)
    return code, html


def main():
    req("POST", f"{MOCK}/_reset")

    # CORS: the site origin is allowed.
    code, h, _ = req("OPTIONS", HOOK, headers={"Origin": "https://ntstays.com", "Access-Control-Request-Method": "POST"})
    check("CORS allows ntstays.com", h.get("Access-Control-Allow-Origin") in ("https://ntstays.com", "*"), h.get("Access-Control-Allow-Origin"))

    # Bot: honeypot filled -> 200 but nothing happens.
    code, _, raw = req("POST", HOOK, {"form_type": "inquiry", "first_name": "Bot", "email": "bot@spam.io",
                                      "message": "buy now", "website": "http://spam.io"})
    time.sleep(1)
    check("bot gets a quiet 200", code == 200 and js(raw).get("ok") is True, code)
    check("bot triggers no API calls", state()["requests"] == [], state()["requests"])

    # Invalid input -> 400 with reasons.
    code, _, raw = req("POST", HOOK, {"form_type": "inquiry", "email": "nope", "message": ""})
    check("invalid inquiry gets 400", code == 400, code)
    check("400 lists what to fix", len(js(raw).get("errors", [])) == 3, js(raw))

    # Newsletter sign-up.
    code, _, raw = req("POST", HOOK, {"form_type": "subscribe", "first_name": "Lee", "email": "Lee@Example.org",
                                      "marketing_opt_in": True, "page": "https://ntstays.com/"})
    s = wait_for(lambda s: any("Marketing consent" in n["properties"]["hs_note_body"] for n in s["notes"]))
    sub = next((c for c in s["contacts"].values() if c["properties"]["email"] == "lee@example.org"), None)
    check("subscribe returns 200 fast", code == 200)
    check("subscriber saved as 'subscriber'", sub and sub["properties"].get("lifecyclestage") == "subscriber", sub)
    check("consent note saved with page", any("ntstays.com" in n["properties"]["hs_note_body"] for n in s["notes"]))
    s = wait_for(lambda s: any("Welcome email sent" in n["properties"]["hs_note_body"] for n in s["notes"]))
    w = next((e for e in s["emails"] if "ntstays-welcome" in (e.get("tags") or [])), None)
    check("welcome email sent to new subscriber", w is not None and w["to"][0]["email"] == "lee@example.org")
    check("welcome greets by first name", w is not None and "Hi Lee," in w["textContent"])
    check("welcome has mailing address and unsubscribe link", w is not None and ADDRESS in w["htmlContent"]
          and "/webhook/ntstays-unsubscribe?e=" in w["htmlContent"])
    check("welcome has one-click unsubscribe headers", w is not None
          and w.get("headers", {}).get("List-Unsubscribe-Post") == "List-Unsubscribe=One-Click")
    check("welcome logged in HubSpot", any("Welcome email sent" in n["properties"]["hs_note_body"] for n in s["notes"]))
    check("subscribe uses no AI, sends only the welcome", s["claude_calls"] == 0 and len(s["emails"]) == 1)

    # Owner-service lead, opted in, owner edits and sends.
    maria = {"form_type": "inquiry", "inquiry_type": "property_management", "first_name": "Maria", "last_name": "Lopez",
             "email": "Maria@Example.com", "service_city": "Worcester, MA", "property_type": "Single-family home",
             "timeline": "Within 1-3 months", "marketing_opt_in": True,
             "message": "I have a 3 bedroom house I want to turn into a short-term rental. Can you manage it?"}
    t0 = time.time()
    code, _, raw = req("POST", HOOK, maria)
    check("inquiry answered quickly (before AI runs)", code == 200 and time.time() - t0 < 5, f"{code} {time.time()-t0:.1f}s")
    s = wait_for(lambda s: review_url_for(s, "maria@example.com"))
    owner_mail = next(e for e in s["emails"] if "ntstays-owner-review" in e.get("tags", []))
    check("owner gets a review email", owner_mail["to"][0]["email"] == "owner@example.com")
    check("owner email subject shows tier", owner_mail["subject"].startswith("[NTStays] HOT"), owner_mail["subject"])
    check("owner can reply straight to lead", owner_mail["replyTo"]["email"] == "maria@example.com")
    mid = next(c["id"] for c in s["contacts"].values() if c["properties"]["email"] == "maria@example.com")
    check("contact created as lead", s["contacts"][mid]["properties"].get("lifecyclestage") == "lead")
    check("opt-in consent recorded", any("ticked" in n["properties"]["hs_note_body"] and n["contact_id"] == mid for n in s["notes"]))
    check("nothing sent to lead before review", not any(e["to"][0]["email"] == "maria@example.com" for e in s["emails"]))

    url = review_url_for(s, "maria@example.com")
    code, html = submit_review(url, "Send this reply", "Re: managing your Worcester home",
                               "Hi Maria,\n\nThanks! Would Thursday at 6pm work for a quick call?\n\nBest,\nHa", "Called her too")
    check("review form shows the draft", b"Hi Maria" in html)
    s = wait_for(lambda s: any(e["to"][0]["email"] == "maria@example.com" for e in s["emails"]))
    sent = [e for e in s["emails"] if e["to"][0]["email"] == "maria@example.com"]
    check("edited reply sent to lead", sent and "Thursday at 6pm" in sent[-1]["textContent"], sent[-1:] and sent[-1]["textContent"])
    check("reply comes from hello@ntstays.com", sent and sent[-1]["sender"]["email"] == "hello@ntstays.com")
    check("owner reply includes the owner results pack", sent and "How our own homes perform" in sent[-1]["htmlContent"]
          and "How our own homes perform" in sent[-1]["textContent"])
    check("owner review email mentions the pack", "owner results pack" in owner_mail["htmlContent"])
    s = wait_for(lambda s: s["contacts"][mid]["properties"]["hs_lead_status"] == "IN_PROGRESS")
    check("lead status set to IN_PROGRESS", s["contacts"][mid]["properties"]["hs_lead_status"] == "IN_PROGRESS")
    check("reply logged as edited by owner", any("edited by owner" in n["properties"]["hs_note_body"] for n in s["notes"]))

    # Stay inquiry with a complaint: flagged, owner chooses not to send.
    ci = time.strftime("%Y-%m-%d", time.localtime(time.time() + 20 * 86400))
    co = time.strftime("%Y-%m-%d", time.localtime(time.time() + 24 * 86400))
    sam = {"form_type": "inquiry", "inquiry_type": "stay", "first_name": "Sam", "email": "sam@example.net",
           "property_id": "home-1", "check_in": ci, "check_out": co, "guests": 4,
           "message": "We stayed last month and the AC was broken. I'd like a refund, but also want to book again."}
    req("POST", HOOK, sam)
    s = wait_for(lambda s: review_url_for(s, "sam@example.net"))
    mail = next(e for e in reversed(s["emails"]) if e.get("replyTo", {}).get("email") == "sam@example.net")
    check("complaint flagged in owner email", "needs_attention" in mail["htmlContent"])
    check("stay nights computed", "4 nights" in mail["htmlContent"])
    n_before = len(s["emails"])
    code, _ = submit_review(review_url_for(s, "sam@example.net"), "Don't send (I'll handle it myself)", note="Calling Sam")
    s = wait_for(lambda s: any("chose not to send" in n["properties"]["hs_note_body"] for n in s["notes"]))
    check("don't-send sends nothing", len(s["emails"]) == n_before)
    check("don't-send decision logged with note", any("chose not to send" in n["properties"]["hs_note_body"]
                                                      and "Calling Sam" in n["properties"]["hs_note_body"] for n in s["notes"]))

    # Returning contact is matched, not duplicated.
    req("POST", HOOK, {**maria, "message": "Following up on my property question."})
    s = wait_for(lambda s: len([e for e in s["emails"] if e.get("replyTo", {}).get("email") == "maria@example.com"]) >= 2)
    check("returning contact not duplicated", sum(c["properties"]["email"] == "maria@example.com" for c in s["contacts"].values()) == 1)
    n_maria = len([e for e in s["emails"] if e["to"][0]["email"] == "maria@example.com"])
    submit_review(review_url_for(s, "maria@example.com"), "Send this reply", pack="Don't include")
    s = wait_for(lambda s: len([e for e in s["emails"] if e["to"][0]["email"] == "maria@example.com"]) > n_maria)
    last = [e for e in s["emails"] if e["to"][0]["email"] == "maria@example.com"][-1]
    check("owner can leave the pack out", "How our own homes perform" not in last["htmlContent"])

    check("one AI call per real inquiry", s["claude_calls"] == 3, s["claude_calls"])

    # Message says condo, form says single-family: flagged for the owner.
    req("POST", HOOK, {"form_type": "inquiry", "inquiry_type": "property_management", "first_name": "Harry",
                       "email": "harry@example.com", "property_type": "Single-family home", "timeline": "As soon as possible",
                       "message": "I have a condo in Quincy that I need managed."})
    s = wait_for(lambda s: review_url_for(s, "harry@example.com"))
    mail = next(e for e in reversed(s["emails"]) if e.get("replyTo", {}).get("email") == "harry@example.com")
    check("property type mismatch flagged", "property_type_mismatch" in mail["htmlContent"]
          and "condo" in mail["htmlContent"])

    # A failing step triggers the error-alert workflow, which emails the owner.
    req("POST", HOOK, {"form_type": "inquiry", "inquiry_type": "cleaning", "first_name": "Err",
                       "email": "err@example.com", "message": "__force_error__ please"})
    s = wait_for(lambda s: any("ntstays-error-alert" in (e.get("tags") or []) for e in s["emails"]), timeout=60)
    alert = next((e for e in s["emails"] if "ntstays-error-alert" in (e.get("tags") or [])), None)
    check("failure alert emailed to owner", alert is not None and alert["to"][0]["email"] == "owner@example.com")
    check("alert names the failed step", alert is not None and "Claude" in alert["subject"], alert and alert["subject"])
    check("alert includes a fix hint", alert is not None and "ANTHROPIC_API_KEY" in alert["htmlContent"])

    # Subscribing again: consent logged again, but no second welcome.
    def welcomes(s, email):
        return [e for e in s["emails"] if "ntstays-welcome" in (e.get("tags") or []) and e["to"][0]["email"] == email]
    def consent_notes(s, email):
        cid = next((c["id"] for c in s["contacts"].values() if c["properties"]["email"] == email), None)
        return [n for n in s["notes"] if n["contact_id"] == cid and "Marketing consent" in n["properties"]["hs_note_body"]]
    req("POST", HOOK, {"form_type": "subscribe", "first_name": "Lee", "email": "lee@example.org", "marketing_opt_in": True})
    s = wait_for(lambda s: len(consent_notes(s, "lee@example.org")) >= 2)
    time.sleep(3)
    check("repeat sign-up gets no second welcome", len(welcomes(state(), "lee@example.org")) == 1)

    # An existing lead subscribes: stays a lead, keeps their name, gets the welcome.
    req("POST", HOOK, {"form_type": "subscribe", "first_name": "M", "email": "maria@example.com", "marketing_opt_in": True})
    s = wait_for(lambda s: welcomes(s, "maria@example.com"))
    mp = s["contacts"][mid]["properties"]
    check("lead who subscribes stays a lead", mp.get("lifecyclestage") == "lead" and mp.get("firstname") == "Maria", mp)
    check("lead who subscribes gets the welcome", len(welcomes(s, "maria@example.com")) == 1)

    # Unsubscribe: opening the link only asks to confirm; the button (POST) unsubscribes.
    w = welcomes(state(), "lee@example.org")[0]
    link = html_mod.unescape(re.search(r'href="([^"]*ntstays-unsubscribe[^"]*)"', w["htmlContent"]).group(1))
    lee_id = next(c["id"] for c in state()["contacts"].values() if c["properties"]["email"] == "lee@example.org")
    code, h, page = req("GET", link)
    check("unsubscribe link shows a confirm button", code == 200 and b'method="post"' in page
          and "text/html" in h.get("Content-Type", ""), code)
    time.sleep(1)
    check("opening the link changes nothing", not any("Unsubscribed" in n["properties"]["hs_note_body"] for n in state()["notes"]))
    code, _, page = req("GET", link[:-4] + "0000")
    check("tampered link is rejected", code == 400 and b"not valid" in page, code)
    r = urllib.request.Request(link, data=b"List-Unsubscribe=One-Click", method="POST",
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        code, page = resp.status, resp.read()
    check("confirming unsubscribes", code == 200 and b"unsubscribed" in page, code)
    s = wait_for(lambda s: any("ntstays-unsubscribe" in (e.get("tags") or []) for e in s["emails"]))
    check("unsubscribe logged on the contact", any(n["contact_id"] == lee_id and "Unsubscribed" in n["properties"]["hs_note_body"]
                                                   for n in s["notes"]))
    check("owner told about the unsubscribe", any("ntstays-unsubscribe" in (e.get("tags") or [])
                                                  and e["to"][0]["email"] == "owner@example.com" for e in s["emails"]))

    # Feedback form: owner gets the review with a line for reviews.csv, reviewer gets a thank-you, no AI.
    calls = state()["claude_calls"]
    code, _, raw = req("POST", HOOK, {"form_type": "review", "role": "partner", "first_name": "Pat", "last_name": "Nguyen",
                                      "email": "pat@acme.example", "company": "Acme Claims", "property_id": "home-3",
                                      "rating": "5", "review": "Fast, flexible and responsive partner.", "publish_as": "company"})
    s = wait_for(lambda s: any("ntstays-feedback-thanks" in (e.get("tags") or []) for e in s["emails"]))
    fb = next((e for e in s["emails"] if "ntstays-feedback" in (e.get("tags") or [])), None)
    check("feedback accepted", code == 200 and js(raw).get("ok") is True, code)
    check("owner gets the feedback with a reviews.csv line", fb is not None and "reviews.csv" in fb["htmlContent"]
          and "Acme Claims" in fb["htmlContent"])
    check("reviewer thanked", any("ntstays-feedback-thanks" in (e.get("tags") or []) and e["to"][0]["email"] == "pat@acme.example"
                                  for e in s["emails"]))
    check("feedback saved in HubSpot", any("Feedback received" in n["properties"]["hs_note_body"] for n in s["notes"]))
    check("feedback uses no AI", s["claude_calls"] == calls, s["claude_calls"])

    # Calendar sync: public availability, dates only (the mock serves home-2's calendar).
    code, h, raw = req("GET", f"{N8N}/webhook/ntstays-availability", headers={"Origin": "https://ntstays.com"})
    av = js(raw) if code == 200 else {}
    check("availability endpoint answers", code == 200 and "homes" in av, code)
    check("availability has home-2's booked dates", len(av.get("homes", {}).get("home-2", [])) == 2, av)
    check("availability holds dates only", b"9999" not in raw and b"Reserved" not in raw)

    # Request to book: amount in the review form -> Stripe payment link in the reply -> guest pays -> confirmations.
    ci2 = time.strftime("%Y-%m-%d", time.localtime(time.time() + 40 * 86400))
    co2 = time.strftime("%Y-%m-%d", time.localtime(time.time() + 70 * 86400))
    req("POST", HOOK, {"form_type": "inquiry", "inquiry_type": "stay", "segment": "travel_nurse", "first_name": "Kim",
                       "email": "kim@example.com", "property_id": "home-2", "check_in": ci2, "check_out": co2,
                       "message": "13-week contract at Rhode Island Hospital."})
    s = wait_for(lambda s: review_url_for(s, "kim@example.com"))
    submit_review(review_url_for(s, "kim@example.com"), "Send this reply", amount="3450.50", pay_for="First month, Cranston House")
    s = wait_for(lambda s: any(e["to"][0]["email"] == "kim@example.com" for e in s["emails"]))
    kim = [e for e in s["emails"] if e["to"][0]["email"] == "kim@example.com"][-1]
    m = re.search(r"https://buy\.stripe\.com/test_(plink_\w+)", kim["htmlContent"])
    check("reply has a Stripe payment link", m is not None and "$3,450.50" in kim["htmlContent"], kim["htmlContent"][-400:])
    link = s["stripe"]["links"].get(m.group(1)) if m else {}
    check("payment link carries the booking, one payment only", link.get("pi_metadata", {}).get("check_in") == ci2
          and link.get("limit") == "1", link)
    event = js(req("POST", f"{MOCK}/_stripe/pay", {"link": m.group(1) if m else ""})[2])
    code, _, _ = req("POST", f"{N8N}/webhook/ntstays-stripe", event)
    check("Stripe notice accepted", code == 200, code)
    s = wait_for(lambda s: any("ntstays-booking-confirmed" in (e.get("tags") or []) for e in s["emails"]))
    conf = next((e for e in s["emails"] if "ntstays-booking-confirmed" in (e.get("tags") or [])), None)
    check("guest gets a booking confirmation", conf is not None and conf["to"][0]["email"] == "kim@example.com"
          and "Cranston House" in conf["textContent"])
    check("owner told about the payment", any("ntstays-payment-owner" in (e.get("tags") or []) for e in s["emails"]))
    s = wait_for(lambda s: any("Payment received" in n["properties"]["hs_note_body"] for n in s["notes"]))
    check("payment logged in HubSpot", any("Payment received" in n["properties"]["hs_note_body"] for n in s["notes"]))
    n_conf = len([e for e in s["emails"] if "ntstays-booking-confirmed" in (e.get("tags") or [])])
    req("POST", f"{N8N}/webhook/ntstays-stripe", event)  # Stripe retries notices: must not confirm twice
    time.sleep(3)
    check("a repeated notice doesn't confirm twice",
          len([e for e in state()["emails"] if "ntstays-booking-confirmed" in (e.get("tags") or [])]) == n_conf)
    code, _, raw = req("GET", f"{N8N}/webhook/ntstays-direct-calendar?home=home-2")
    check("direct-bookings calendar has the paid dates", code == 200 and ci2.replace("-", "").encode() in raw
          and b"kim" not in raw, raw[:200])

    # Spam protection: a bad Turnstile token is refused before anything else happens.
    n_req = len(state()["requests"])
    code, _, raw = req("POST", HOOK, {"form_type": "inquiry", "first_name": "Bot", "email": "bot2@spam.io",
                                      "message": "cheap pills", "turnstile": "bad-token"})
    check("failed spam check gets 400", code == 400 and "spam check" in json.dumps(js(raw)), code)
    time.sleep(1)
    check("failed spam check reaches no CRM, AI or email", not any(r["path"].startswith(("/crm", "/v1/messages", "/v3"))
                                                                  for r in state()["requests"][n_req:]))

    # Follow-ups: an unpaid payment link, 3 days old -> the morning check drafts a reminder for the owner.
    req("POST", HOOK, {"form_type": "inquiry", "inquiry_type": "stay", "first_name": "Lee", "email": "lee.pay@example.com",
                       "property_id": "home-3", "check_in": ci2, "check_out": co2, "message": "Family of four, monthly stay."})
    s = wait_for(lambda s: review_url_for(s, "lee.pay@example.com"))
    submit_review(review_url_for(s, "lee.pay@example.com"), "Send this reply", amount="2000", pay_for="First month, Abington")
    s = wait_for(lambda s: any(e["to"][0]["email"] == "lee.pay@example.com" for e in s["emails"]))
    lee = [e for e in s["emails"] if e["to"][0]["email"] == "lee.pay@example.com"][-1]
    lid = re.search(r"test_(plink_\w+)", lee["htmlContent"]).group(1)
    req("POST", f"{MOCK}/_stripe/backdate", {"link": lid, "days": 3})
    key = os.environ.get("FOLLOWUP_KEY", "local-test-only-unsubscribe-secret")
    req("POST", f"{N8N}/webhook/ntstays-followups-run", {}, headers={"x-ntstays-key": key})
    s = wait_for(lambda s: any("ntstays-followup-review" in (e.get("tags") or []) for e in s["emails"]))
    fu = next((e for e in s["emails"] if "ntstays-followup-review" in (e.get("tags") or [])), None)
    check("owner gets a payment-reminder draft", fu is not None and "Payment reminder for Lee" in fu["subject"])
    check("reminder queued once (marked in Stripe)", s["stripe"]["links"][lid]["metadata"].get("nudge_queued"))
    check("nothing sent to the guest before review", not any("ntstays-followup" in (e.get("tags") or []) for e in s["emails"]))
    url = re.search(r'href="([^"]+form-waiting[^"]+)"', fu["htmlContent"]).group(1)
    req("GET", url)
    for _ in range(10):
        c2, _, _ = req("POST", url, form={"field-0": "Send this follow-up", "field-1": "", "field-2": ""})
        if c2 != 409:
            break
        time.sleep(1)
    s = wait_for(lambda s: any("ntstays-followup-payment_reminder" in (e.get("tags") or []) for e in s["emails"]))
    sent_fu = next((e for e in s["emails"] if "ntstays-followup-payment_reminder" in (e.get("tags") or [])), None)
    check("approved reminder sent with the payment link", sent_fu is not None and lid in sent_fu["textContent"])
    req("POST", f"{N8N}/webhook/ntstays-followups-run", {}, headers={"x-ntstays-key": key})
    time.sleep(3)
    check("no second reminder for the same link",
          len([e for e in state()["emails"] if "ntstays-followup-review" in (e.get("tags") or [])]) == 1)

    # Website assistant: answers, keeps prices out, and hands a request to the owner only after the visitor agrees.
    chat_url = f"{N8N}/webhook/ntstays-chat"
    convo, sess = [], {}
    def say(text, token="ok-token"):
        convo.append({"role": "user", "content": text})
        c, _, raw = req("POST", chat_url, {"messages": convo, "turnstile": token, **sess}, headers={"Origin": "https://ntstays.com"})
        body = js(raw)
        if c == 200:
            convo.append({"role": "assistant", "content": body["reply"]})
            sess.update({"session": body["session"], "sig": body["sig"]})
        return c, body
    c, first = req("POST", chat_url, {"messages": [{"role": "user", "content": "hi"}], "turnstile": "bad-token"})[0:3:2]
    check("chat: failed spam check on a new chat is refused", c == 400)
    c, b = say("Hi, I'm a travel nurse looking at Cranston")
    check("chat: answers and returns a signed session", c == 200 and b.get("reply") and b.get("session") and b.get("sig"), b)
    c, b = say("What's the price?")
    check("chat: a price from the model never reaches the visitor", c == 200 and "$" not in b["reply"] and "quote" in b["reply"], b)
    c, b = req("POST", chat_url, {"messages": convo + [{"role": "user", "content": "x"}], "session": sess["session"], "sig": "forged"})[0:3:2]
    check("chat: forged session signature refused", c == 403)
    c, b = say("My name is Jo, jo.nurse@example.com")
    check("chat: asks before sending anything", c == 200 and not b.get("handed_off"), b)
    time.sleep(2)
    check("chat: nothing reaches the owner before the visitor agrees", review_url_for(state(), "jo.nurse@example.com") is None)
    c, b = say("yes please send it")
    check("chat: hands off after the visitor agrees", c == 200 and b.get("handed_off") is True, b)
    s = wait_for(lambda s: review_url_for(s, "jo.nurse@example.com"))
    mail = next((e for e in reversed(s["emails"]) if e.get("replyTo", {}).get("email") == "jo.nurse@example.com"), None)
    check("chat: request arrives in the normal owner review flow", mail is not None and "website assistant" in mail["htmlContent"])
    creq = state().get("chat_requests", [{}])[-1]
    check("chat: model gets cached rules first and live availability after", creq.get("system", [{}])[0].get("cache_control")
          and "Availability" in creq.get("system", [{}, {}])[1].get("text", ""))

    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
