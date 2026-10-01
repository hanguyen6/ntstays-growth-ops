"""Local stand-in for the HubSpot CRM API, the Claude Messages API, Brevo email sending and the Stripe API.

Lets you run and test the whole workflow with no accounts or API keys:
    python mock/mock_server.py            # listens on http://localhost:8765

Point the workflow at it with HUBSPOT_BASE_URL, ANTHROPIC_BASE_URL and BREVO_BASE_URL
set to http://localhost:8765 (see .env.example). Emails are captured, not sent.
GET /_state shows everything the workflow wrote; POST /_reset clears it.
POST /_stripe/pay {"link": "plink_..."} pays a payment link and returns the checkout.session.completed event
that Stripe would send, for the test to post to the n8n webhook.
"""
from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE_LOCK = threading.Lock()
STATE = {"contacts": {}, "notes": [], "tasks": [], "emails": [], "claude_calls": 0, "requests": [],
         "stripe": {"prices": {}, "links": {}, "intents": {}}}
STRIPE_PATHS = ("/v1/prices", "/v1/payment_links", "/v1/payment_intents")
TURNSTILE_PATH = "/turnstile/v0/siteverify"
NEXT_ID = [1000]


def _new_id():
    NEXT_ID[0] += 1
    return str(NEXT_ID[0])


def fake_chat(messages: list) -> dict:
    """Stand-in for the website assistant: answers, asks to send, and sends once the visitor says yes."""
    last = messages[-1]["content"].lower()
    everything = " ".join(m["content"] for m in messages if m["role"] == "user")
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", everything)
    lead = {"ready": False, "first_name": "", "last_name": "", "email": "", "phone": "", "inquiry_type": "stay",
            "segment": "travel_nurse" if "nurse" in everything.lower() else "", "property_id": "home-2",
            "check_in": "", "check_out": "", "guests": "", "summary": ""}
    if "price" in last:
        return {"reply": "It's $199 per night.", "lead": lead}  # the workflow must replace this
    if email and last.strip().startswith("yes"):
        lead.update({"ready": True, "first_name": "Jo", "email": email.group(0),
                     "summary": "Travel nurse asking about the Cranston house."})
        return {"reply": "Done! I've sent this to our team.", "lead": lead}
    if email:
        return {"reply": "Thanks! Shall I send this to our team?", "lead": lead}
    return {"reply": "Happy to help. The Cranston house looks open in February.", "lead": lead}


def fake_report(messages: list, mode: str = "good") -> dict:
    """Stand-in for the monthly report: a draft that uses only numbers from the facts it was given.
    mode "bad_once": the first draft has a calculated number (14.4), the rewrite is clean; "bad_always": both are bad."""
    facts = json.loads(messages[0]["content"].split("FACTS:", 1)[1])
    rewrite = len(messages) > 1
    ab = facts.get("airbnb") or {}
    lines = [{"name": "Airbnb", "text": f"Overall conversion was {ab['overall_conversion']}." if ab.get("overall_conversion")
              else "Airbnb numbers weren't logged."}]
    bad = mode == "bad_always" or (mode == "bad_once" and not rewrite)
    headline = "Furnished Finder share up 14.4 points" if bad else f"Channel report for {facts['month']}"
    return {"subject": f"NTStays channel report: {facts['month']}", "headline": headline,
            "channels": lines, "watch": [f"Log or refresh: {m}" for m in facts.get("missing", [])[:3]],
            "next_actions": ["Log next month's platform numbers"]}


def fake_claude(user: dict) -> dict:
    """Deterministic stand-in for the model: simple keyword scoring and a templated reply."""
    about = user.get("inquiry_about", "")
    msg = (user.get("message") or "").lower()
    first = user.get("first_name") or "there"
    score = 35
    reasons = []
    if "property management" in about or "renovation" in about or "staging" in about:
        score += 25
        reasons.append(f"Owner-service inquiry: {about}")
        prop = user.get("property") or {}
        if prop.get("timeline") in ("As soon as possible", "Within 1-3 months"):
            score += 15
            reasons.append(f"Near timeline: {prop.get('timeline')}")
    stay = user.get("stay") or {}
    if stay.get("nights"):
        reasons.append(f"{stay['nights']} nights requested")
        if stay["nights"] >= 3:
            score += 15
        if stay.get("days_until_check_in") is not None and stay["days_until_check_in"] <= 60:
            score += 15
            reasons.append("Check-in within 60 days")
    attention = any(k in msg for k in ("complaint", "refund", "damage", "broken", "lawyer"))
    if not reasons:
        reasons.append("General question")
    body = (f"Hi {first},\n\nThanks for reaching out to NTStays about {about}. "
            "I'll check the details you shared and follow up shortly. "
            + ("Would a quick 15-minute call this week work to talk about your property?"
               if "stay" not in about else "I'll confirm dates and options for you soon.")
            + "\n\nBest,\nHa")
    return {"score": min(100, score), "reasons": reasons,
            "summary": f"{first} asked about {about}.",
            "email_subject": f"Re: your NTStays inquiry about {about}",
            "email_body": body, "needs_human_attention": attention,
            "attention_reason": "possible complaint" if attention else ""}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get("MOCK_VERBOSE"):
            super().log_message(fmt, *args)

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _form(self):
        from urllib.parse import parse_qsl
        n = int(self.headers.get("Content-Length") or 0)
        return dict(parse_qsl(self.rfile.read(n).decode()))

    def _stripe_meta(self, form, prefix):
        return {k[len(prefix) + 1:-1]: v for k, v in form.items() if k.startswith(prefix + "[") and k.endswith("]")
                and "][" not in k[len(prefix) + 1:-1]}

    def _stripe(self, method):
        """Just enough of Stripe: prices, payment links, payment intents (get + search)."""
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            return self._json(401, {"error": {"message": "No API key provided"}})
        st = STATE["stripe"]
        with STATE_LOCK:
            STATE["requests"].append({"method": method, "path": self.path})
            if method == "POST" and self.path == "/v1/prices":
                f = self._form()
                if not f.get("unit_amount") or not f.get("currency"):
                    return self._json(400, {"error": {"message": "unit_amount and currency are required"}})
                pid = f"price_{_new_id()}"
                st["prices"][pid] = {"id": pid, "unit_amount": int(f["unit_amount"]), "currency": f["currency"],
                                     "product_name": f.get("product_data[name]", "")}
                return self._json(200, st["prices"][pid])
            if method == "POST" and self.path == "/v1/payment_links":
                f = self._form()
                price = st["prices"].get(f.get("line_items[0][price]"))
                if not price:
                    return self._json(400, {"error": {"message": "No such price"}})
                lid = f"plink_{_new_id()}"
                st["links"][lid] = {"id": lid, "url": f"https://buy.stripe.com/test_{lid}", "price": price,
                                    "pi_metadata": self._stripe_meta(f, "payment_intent_data[metadata]"),
                                    "metadata": self._stripe_meta(f, "metadata"), "active": True,
                                    "limit": f.get("restrictions[completed_sessions][limit]")}
                return self._json(200, {"id": lid, "url": st["links"][lid]["url"], "active": True})
            if method == "GET" and self.path.startswith("/v1/payment_links"):
                data = [{"id": l["id"], "url": l["url"], "active": l["active"], "metadata": l["metadata"]}
                        for l in st["links"].values() if l["active"]]
                return self._json(200, {"object": "list", "data": data, "has_more": False})
            m = re.fullmatch(r"/v1/payment_links/(plink_\w+)", self.path)
            if method == "POST" and m:
                link = st["links"].get(m.group(1))
                if not link:
                    return self._json(404, {"error": {"message": "No such payment link"}})
                link["metadata"].update(self._stripe_meta(self._form(), "metadata"))
                return self._json(200, {"id": link["id"], "url": link["url"], "metadata": link["metadata"]})
            if method == "GET" and self.path.startswith("/v1/payment_intents/search"):
                data = [pi for pi in st["intents"].values() if pi["status"] == "succeeded"
                        and pi["metadata"].get("ntstays") == "booking"]
                return self._json(200, {"object": "search_result", "data": data, "has_more": False})
            m = re.fullmatch(r"/v1/payment_intents/(pi_\w+)", self.path)
            if method == "GET" and m:
                pi = st["intents"].get(m.group(1))
                return self._json(200, pi) if pi else self._json(404, {"error": {"message": "No such payment_intent"}})
        return self._json(404, {"error": {"message": "mock: unknown Stripe call"}})

    def _auth_ok(self):
        if self.path.startswith("/v1/"):
            return bool(self.headers.get("x-api-key")) and self.headers.get("anthropic-version")
        if self.path.startswith("/v3/"):
            return bool(self.headers.get("api-key"))
        return (self.headers.get("Authorization") or "").startswith("Bearer ") and len(self.headers["Authorization"]) > 7

    def do_GET(self):
        if self.path.startswith(STRIPE_PATHS):
            return self._stripe("GET")
        if self.path == "/_state":
            with STATE_LOCK:
                return self._json(200, STATE)
        if self.path.startswith("/ical/"):
            # A calendar export like Airbnb's: one reservation 10-14 days from now, and a block.
            import datetime as dt
            d = lambda n: (dt.date.today() + dt.timedelta(days=n)).strftime("%Y%m%d")
            ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                   f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{d(10)}\r\nDTEND;VALUE=DATE:{d(14)}\r\nSUMMARY:Reserved\r\n"
                   "DESCRIPTION:Phone Number (Last 4 Digits): 9999\r\nEND:VEVENT\r\n"
                   f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{d(30)}\r\nDTEND;VALUE=DATE:{d(35)}\r\nSUMMARY:Airbnb (Not available)\r\nEND:VEVENT\r\n"
                   "END:VCALENDAR\r\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("Content-Length", str(len(ics)))
            self.end_headers()
            self.wfile.write(ics)
            return
        return self._json(404, {"message": "not found"})

    def do_PATCH(self):
        body = self._body()
        m = re.fullmatch(r"/crm/v3/objects/contacts/(\d+)", self.path)
        if not self._auth_ok():
            return self._json(401, {"message": "missing auth"})
        with STATE_LOCK:
            STATE["requests"].append({"method": "PATCH", "path": self.path})
            if not m or m.group(1) not in STATE["contacts"]:
                return self._json(404, {"message": "contact not found"})
            c = STATE["contacts"][m.group(1)]
            c["properties"].update(body.get("properties", {}))
            return self._json(200, c)

    def do_POST(self):
        if self.path.startswith(STRIPE_PATHS):
            return self._stripe("POST")
        if self.path == TURNSTILE_PATH:
            # Cloudflare Turnstile stand-in: every token passes except "bad-token" (and a missing secret).
            f = self._form()
            ok = bool(f.get("secret")) and f.get("response") != "bad-token"
            return self._json(200, {"success": ok, "error-codes": [] if ok else ["invalid-input-response"]})
        body = self._body()
        if self.path == "/_reset":
            with STATE_LOCK:
                STATE.update({"contacts": {}, "notes": [], "tasks": [], "emails": [], "claude_calls": 0, "requests": [],
                              "stripe": {"prices": {}, "links": {}, "intents": {}},
                              "report_mode": body.get("report_mode", "good"), "report_requests": []})
            return self._json(200, {"ok": True})
        if self.path == "/_stripe/backdate":
            # Test hook: pretend a payment link was sent `days` ago.
            import datetime as dt
            with STATE_LOCK:
                link = STATE["stripe"]["links"].get(body.get("link"))
                if not link:
                    return self._json(404, {"message": "no such link"})
                link["metadata"]["sent"] = (dt.date.today() - dt.timedelta(days=int(body.get("days", 3)))).isoformat()
            return self._json(200, link["metadata"])
        if self.path == "/_stripe/pay":
            # Test hook: the guest pays a payment link. Returns the webhook event Stripe would send.
            with STATE_LOCK:
                link = STATE["stripe"]["links"].get(body.get("link"))
                if not link:
                    return self._json(404, {"message": "no such link"})
                pid = f"pi_{_new_id()}"
                link["active"] = False
                STATE["stripe"]["intents"][pid] = {"id": pid, "object": "payment_intent", "status": "succeeded",
                                                   "amount": link["price"]["unit_amount"], "amount_received": link["price"]["unit_amount"],
                                                   "currency": link["price"]["currency"], "metadata": link["pi_metadata"]}
            return self._json(200, {"id": f"evt_{pid}", "type": "checkout.session.completed", "data": {"object": {
                "id": f"cs_{pid}", "object": "checkout.session", "payment_status": "paid", "payment_intent": pid,
                "payment_link": link["id"]}}})
        if not self._auth_ok():
            return self._json(401, {"message": "missing or invalid auth header"})
        with STATE_LOCK:
            STATE["requests"].append({"method": "POST", "path": self.path})
            if self.path == "/v1/messages":
                STATE["claude_calls"] += 1
                if not body.get("model") or not body.get("messages"):
                    return self._json(400, {"type": "error", "error": {"message": "model and messages required"}})
                if body.get("output_config") and "monthly channel report" in str(body.get("system", "")):
                    STATE.setdefault("report_requests", []).append(body)
                    text = json.dumps(fake_report(body["messages"], STATE.get("report_mode", "good")))
                    return self._json(200, {
                        "id": "msg_mock_report", "type": "message", "role": "assistant", "model": body["model"],
                        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                        "usage": {"input_tokens": 1500, "output_tokens": 300}})
                if body.get("output_config"):
                    # The website assistant: structured JSON (reply + lead).
                    STATE.setdefault("chat_requests", []).append(body)
                    text = json.dumps(fake_chat(body["messages"]))
                    return self._json(200, {
                        "id": "msg_mock_chat", "type": "message", "role": "assistant", "model": body["model"],
                        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                        "usage": {"input_tokens": 900, "output_tokens": 120}})
                user = json.loads(body["messages"][-1]["content"])
                if "__force_error__" in (user.get("message") or ""):
                    # Test hook: simulate Claude rejecting the request (e.g. a bad model ID).
                    return self._json(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                       "message": "mock: forced error for testing"}})
                text = json.dumps(fake_claude(user))
                return self._json(200, {
                    "id": "msg_mock", "type": "message", "role": "assistant", "model": body["model"],
                    "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                    "usage": {"input_tokens": 420, "output_tokens": 180}})
            if self.path == "/v3/smtp/email":
                for k in ("sender", "to", "subject"):
                    if not body.get(k):
                        return self._json(400, {"code": "missing_parameter", "message": f"{k} is required"})
                if not (body.get("htmlContent") or body.get("textContent")):
                    return self._json(400, {"code": "missing_parameter", "message": "content is required"})
                STATE["emails"].append(body)
                return self._json(201, {"messageId": f"<mock-{len(STATE['emails'])}@brevo>"})
            if self.path == "/crm/v3/objects/contacts/search":
                email = body["filterGroups"][0]["filters"][0]["value"]
                hits = [c for c in STATE["contacts"].values() if c["properties"].get("email") == email]
                return self._json(200, {"total": len(hits), "results": hits[:1]})
            if self.path == "/crm/v3/objects/contacts/batch/upsert":
                results = []
                for inp in body["inputs"]:
                    email = inp["id"]
                    existing = next((c for c in STATE["contacts"].values() if c["properties"].get("email") == email), None)
                    if existing:
                        existing["properties"].update(inp["properties"])
                        existing["new"] = False
                        results.append(existing)
                    else:
                        cid = _new_id()
                        c = {"id": cid, "properties": dict(inp["properties"]), "new": True}
                        STATE["contacts"][cid] = c
                        results.append(c)
                return self._json(200, {"status": "COMPLETE", "results": results})
            if self.path in ("/crm/v3/objects/notes", "/crm/v3/objects/tasks"):
                kind = self.path.rsplit("/", 1)[1]
                to = body["associations"][0]["to"]["id"]
                if to not in STATE["contacts"]:
                    return self._json(400, {"message": f"association target {to} not found"})
                obj = {"id": _new_id(), "properties": body["properties"], "contact_id": to}
                STATE[kind].append(obj)
                return self._json(201, obj)
        return self._json(404, {"message": f"no mock for {self.path}"})


def main():
    port = int(os.environ.get("MOCK_PORT", "8765"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Mock HubSpot + Claude + Brevo on http://localhost:{port}  (GET /_state to inspect)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
