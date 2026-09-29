"""Tests for build_stats.py. No accounts or network needed:  python stats/test_build_stats.py"""
import csv
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_stats  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  ({detail})"))
    if not cond:
        FAILS.append(name)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_docx(path, paragraphs):
    """A minimal Word file: just the paragraphs."""
    import html
    import zipfile
    body = "".join(f"<w:p><w:r><w:t>{html.escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                                        f'2006/main"><w:body>{body}</w:body></w:document>')


CONFIG = {
    "currency": "USD",
    "properties": [
        {"id": "home-1", "name": "Lake", "match": ["Lakeview"], "hosting_since": "2025-01-01"},
        {"id": "home-2", "name": "Loft", "match": ["Loft"], "hosting_since": "2026-01-01"},
    ],
    "public": {"stays_hosted": True, "guest_origins": True, "ratings": True, "featured_reviews": True, "occupancy": False},
}
AIRBNB_HEADER = ["Date", "Type", "Confirmation Code", "Booking date", "Start date", "End date", "Nights", "Guest",
                 "Listing", "Currency", "Amount", "Paid out", "Service fee", "Cleaning fee", "Gross earnings"]


def small_fixture(d):
    """Hand-checkable: today = 2026-09-26, window 2025-09-26 .. 2026-09-26."""
    write_csv(d / "airbnb.csv", AIRBNB_HEADER, [
        # 4 nights, gross 1000, payout 970, booked 30 days ahead
        ["08/02/2026", "Reservation", "HMAAA", "07/02/2026", "08/01/2026", "08/05/2026", "4", "Jordan Secretname",
         "Lakeview Cottage", "USD", "970.00", "", "30.00", "100.00", "1000.00"],
        ["08/02/2026", "Reservation", "HMAAA", "07/02/2026", "08/01/2026", "08/05/2026", "4", "Jordan Secretname",
         "Lakeview Cottage", "USD", "970.00", "", "30.00", "100.00", "1000.00"],  # duplicate row (overlapping export)
        ["08/10/2026", "Adjustment", "HMAAA", "", "", "", "", "Jordan Secretname", "", "USD", "-20.00", "", "", "", ""],
        ["09/01/2026", "Payout", "", "", "", "", "", "", "", "USD", "", "950.00", "", "", ""],
        # a second room in the same home, overlapping 2 of those nights (booked 10 days ahead)
        ["08/03/2026", "Reservation", "HMDDD", "07/23/2026", "08/02/2026", "08/04/2026", "2", "Lee Hiddenname",
         "Lakeview Room", "USD", "200.00", "", "", "", "200.00"],
        # a future stay: 2 nights in October, on the books
        ["", "Reservation", "HMBBB", "09/01/2026", "10/10/2026", "10/12/2026", "2", "Pat Hiddenname",
         "Lakeview Cottage", "USD", "388.00", "", "12.00", "", "400.00"],
        # listing that matches no property -> warning
        ["", "Reservation", "HMCCC", "01/01/2026", "02/01/2026", "02/03/2026", "2", "X Y", "Mystery Cabin", "USD",
         "200.00", "", "", "", "200.00"],
    ])
    write_csv(d / "booking-loft.csv", ["Book number", "Guest name(s)", "Check-in", "Check-out", "Booked on", "Status",
                                       "People", "Price", "Commission amount", "Booker country", "Duration (nights)"], [
        ["111", "Anna Private", "2026-03-10", "2026-03-13", "2026-03-01 09:00:00", "ok", "2", "600 USD", "90 USD", "gb", "3"],
        ["112", "Ben Private", "2026-04-10", "2026-04-12", "2026-04-01 09:00:00", "cancelled_by_guest", "2", "400 USD",
         "60 USD", "de", "2"],
    ])
    write_csv(d / "guest_origins.csv", ["confirmation", "city", "region", "country"], [["HMAAA", "Austin", "TX", "US"]])
    write_csv(d / "reviews.csv", ["property", "platform", "date", "rating", "display_name", "origin", "text", "feature"], [
        ["home-1", "Airbnb", "2026-08-06", "5", "Jordan S.", "Austin, TX", "Great stay.", "yes"],
        ["home-2", "Booking.com", "2026-03-14", "4", "Anna Maria Private", "UK", "Nice loft.", "yes"],
        ["home-2", "Booking.com", "2026-03-20", "3", "Carl", "", "Noisy.", "yes"],  # 3 stars: never featured
    ])


def run_small():
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        small_fixture(d)
        out = d / "out"
        stats, pub = build_stats.main(["--exports", str(d), "--config", str(write_config(d)), "--out", str(out),
                                       "--public-out", str(out / "stats.json"), "--today", "2026-09-26", "--offline"])
        pub_text = (out / "stats.json").read_text(encoding="utf-8")
        dash = (out / "dashboard.html").read_text(encoding="utf-8")

    p1 = next(p for p in stats["per_property"] if p["id"] == "home-1")["l12m"]
    p2 = next(p for p in stats["per_property"] if p["id"] == "home-2")["l12m"]
    check("airbnb duplicate row ignored, adjustment applied", p1["gross"] == 1180 and p1["payout"] == 1150, p1)
    check("airbnb nights / stays", p1["nights"] == 6 and p1["stays"] == 2, p1)
    check("two rooms on one night = one occupied home-night", p1["occupied"] == 4, p1)
    check("occupancy uses the 365-night window", p1["available"] == 365 and abs(p1["occupancy"] - 4 / 365) < 1e-4, p1)
    check("ADR = gross / booked nights", p1["adr"] == 196.67, p1["adr"])
    check("lead time", p1["avg_lead_days"] == 20, p1["avg_lead_days"])
    check("hosting_since shortens the window", p2["available"] == 268, p2["available"])
    check("booking.com gross and commission", p2["gross"] == 600 and p2["payout"] == 510, p2)
    check("cancelled booking.com stay has no nights or revenue", p2["nights"] == 3 and p2["stays"] == 1, p2)
    check("cancelled counted", stats["cancelled"] == 1, stats["cancelled"])
    check("on the books (next 90 days)", stats["on_the_books_90d"] == {"nights": 2, "gross": 400.0, "stays": 1},
          stats["on_the_books_90d"])
    check("unmatched listing warned", any("Mystery Cabin" in w for w in stats["warnings"]), stats["warnings"])
    o = stats["origins"]
    check("origins: guest_origins.csv + booker country",
          o["us_states"] == ["Texas"] and o["countries"] == ["United Kingdom", "United States"], o)
    check("august revenue lands in 2026-08", next(m for m in stats["monthly"] if m["month"] == "2026-08")["home-1"]["gross"] == 1180)
    check("ratings by property", stats["ratings"]["by_property"]["home-2"]["avg"] == 3.5)

    check("public: 3-star review not featured", len(pub["reviews"]) == 2, pub["reviews"])
    check("public: full name cut to first word", any(r["name"] == "Anna" for r in pub["reviews"]), pub["reviews"])
    check("public: warning about full name", any("Anna Maria Private" in w for w in stats["warnings"]))
    for secret in ["Secretname", "Hiddenname", "Private", "HMAAA", "111"]:
        check(f"public stats.json has no {secret!r}", secret not in pub_text)
    check("public: no revenue fields", not any(k in pub_text for k in ["gross", "payout", "adr", "revpar"]))
    check("public: occupancy off by default", "occupancy" not in pub)
    check("dashboard embeds the stats", '"gross": 1180.0' in dash)
    check("dashboard has no guest names", "Secretname" not in dash and "Hiddenname" not in dash)


def run_formats():
    """Real-world layouts: Vrbo payout summary, Booking.com reservations + reviews, Vrbo reviews page in Excel."""
    import datetime as dt
    import openpyxl
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        write_csv(d / "VrboPayoutSummaryReport.csv", [
            "Property ID", "Unit ID", "Address", "Reservation ID", "Traveler First Name", "Traveler Last Name",
            "Booking status", "Check-in", "Check-out", "Nights", "Payout date", "Gross booking amount", "Deductions",
            "Payout", "Payout currency"], [
            ["111", "9", "1 Loft St", "HA-AAA", "Kim", "Secretname", "Reserve", "May 1, 2026", "May 4, 2026", "3",
             "May 2, 2026", "300.00", "25.00", "275.00", "USD"],
            # paid, reversed, paid again, then cancelled: keeps 100, no nights
            ["111", "9", "1 Loft St", "HA-BBB", "Lou", "Secretname", "Cancel", "June 1, 2026", "June 3, 2026", "0",
             "May 20, 2026", "250.00", "20.00", "230.00", "USD"],
            ["111", "9", "1 Loft St", "HA-BBB", "Lou", "Secretname", "Cancel", "June 1, 2026", "June 3, 2026", "0",
             "May 25, 2026", "-150.00", "-12.00", "-138.00", "USD"],
            # refunded to zero: cancelled
            ["111", "9", "1 Loft St", "HA-CCC", "Max", "Secretname", "Reserve", "July 1, 2026", "July 2, 2026", "1",
             "July 1, 2026", "200.00", "16.00", "184.00", "USD"],
            ["111", "9", "1 Loft St", "HA-CCC", "Max", "Secretname", "Reserve", "July 1, 2026", "July 2, 2026", "1",
             "July 9, 2026", "-200.00", "-16.00", "-184.00", "USD"],
        ])
        write_csv(d / "BookingReservations.csv", [
            "Property name", "Location", "Booker name", "Genius booker", "Arrival", "Departure", "Booked on", "Status",
            "Total payment", "Commission", "Currency", "Reservation number"], [
            ["Garden Room", "12 Main St\nLakeview, United States", "Ann Secretname", "No", "10 March 2026",
             "13 March 2026", "1 March 2026", "OK", "600", "90", "USD", "555"],
            ["Garden Room", "12 Main St\nLakeview, United States", "Bo Secretname", "No", "10 April 2026",
             "12 April 2026", "1 April 2026", "No show", "400", "", "USD", "556"],
        ])
        write_csv(d / "booking_reviews.csv", [
            "Review date", "Guest name", "Reservation number", "Review title", "Positive review", "Negative review",
            "Review score"], [["2026-03-14 10:00:00", "ann", "555", "Lovely", "Great room.", "Small closet.", "9"]])
        wb = openpyxl.Workbook()
        for line in ["LO.", "Lena Secretname", "Res #HA-AAA", "Fri, May 1 - Mon, May 4, 2026", "Cozy Loft", "Vrbo",
                     dt.datetime(2026, 8, 10), "Posted May 6, 2026", "Nice stay", "Clean and quiet.", "Show more",
                     "ZZ.", "Zed Secretname", "Res #HA-ZZZ", "Sun, Jun 1 - Mon, Jun 2, 2026", "Cozy Loft", "Vrbo",
                     "Zed did not submit a review"]:
            wb.active.append([line])
        wb.save(d / "Vrbo_review.xlsx")
        # Airbnb reviews page pasted into Word, plus the stay it belongs to, plus a medium-term lease
        write_csv(d / "airbnb.csv", AIRBNB_HEADER, [
            ["", "Reservation", "HMZZZ", "05/01/2026", "05/20/2026", "05/23/2026", "3", "Nora Secretname",
             "Lakeview Cottage", "USD", "300.00", "", "", "", "300.00"]])
        write_docx(d / "airbnb_reviews.docx", [
            "121 reviews", 'HYPERLINK "https://www.airbnb.com/users/profile/1"', "Nora", "Tampa, FL",
            "Rating 5 out of 5", ",·", "June 2026", "Lovely lake house.",
            'HYPERLINK "https://www.airbnb.com/users/profile/2"', "Response from Ha", "June 2026", "Thanks Nora!",
            'HYPERLINK "https://www.airbnb.com/users/profile/3"', "Omar", "Oxford, United Kingdom",
            "Rating 4 out of 5", ",·", "March 2026", "Good.", "Translated from FrenchShow original"])
        write_csv(d / "leases.csv", ["platform", "confirmation", "property", "segment", "check_in", "check_out",
                                     "monthly_rent", "status"],
                  [["Furnished Finder", "L-1", "home-2", "nurse", "2025-10-01", "2026-01-01", "3044", "ok"]])
        out = d / "out"
        cfg = dict(CONFIG, public={**CONFIG["public"], "feature_codes": ["HA-AAA", "555"]})
        cfg["properties"] = [dict(CONFIG["properties"][0]), dict(CONFIG["properties"][1], match=["Loft", "111"])]
        (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        stats, pub = build_stats.main(["--exports", str(d), "--config", str(d / "config.json"), "--out", str(out),
                                       "--public-out", str(out / "stats.json"), "--today", "2026-09-26", "--offline"])
        pub_text = (out / "stats.json").read_text(encoding="utf-8")

    p1 = next(p for p in stats["per_property"] if p["id"] == "home-1")["l12m"]
    p2 = next(p for p in stats["per_property"] if p["id"] == "home-2")["l12m"]
    check("vrbo + lease: stay, kept cancellation money, 3 months at 3044/mo", abs(p2["gross"] - 9600) < 0.01
          and p2["nights"] == 3 + 92, p2)
    check("vrbo: refunded-to-zero and cancelled stays have no nights", p2["stays"] == 2, p2)
    check("booking.com + airbnb: location matches the home, no-show earns nothing", p1["gross"] == 900
          and p1["payout"] == 810 and p1["nights"] == 6, p1)
    mt = stats["stay_types"]["l12m"]["Medium-term (28+ nights)"]
    check("medium-term split", mt["stays"] == 1 and mt["nights"] == 92, mt)
    air = [r for r in stats["reviews"] if r["platform"] == "Airbnb"]
    nora = next((r for r in air if r["display_name"] == "Nora"), {})
    check("airbnb review page: 2 guest reviews, host reply skipped", len(air) == 2, air)
    check("airbnb review linked to the stay by first name + month", nora.get("code") == "HMZZZ"
          and nora.get("property") == "home-1", nora)
    omar = next((r for r in air if r["display_name"] == "Omar"), {})
    check("airbnb review: translation note dropped", omar.get("text") == "Good.", omar)
    o = stats["origins"]
    check("origins from linked and unlinked reviews", "Florida" in o["us_states"] and "United Kingdom" in o["countries"], o)
    revs = {r["code"]: r for r in stats["reviews"]}
    check("booking review: 9/10 -> 4.5, home from its reservation", revs.get("555", {}).get("rating") == 4.5
          and revs["555"]["property"] == "home-1", revs.get("555"))
    check("vrbo review: Excel date Aug 10 = 8/10 -> 4.0", revs.get("HA-AAA", {}).get("rating") == 4.0, revs.get("HA-AAA"))
    check("vrbo review: title and text split", revs["HA-AAA"].get("title") == "Nice stay"
          and revs["HA-AAA"]["text"] == "Clean and quiet.", revs["HA-AAA"])
    check("vrbo review: stay without a review skipped", "HA-ZZZ" not in revs)
    check("reviews: names cut to first name + initial", revs["HA-AAA"]["display_name"] == "Lena S."
          and revs["555"]["display_name"] == "Ann")
    check("public: featured by code", sorted(r["name"] for r in pub["reviews"]) == ["Ann", "Lena S."], pub["reviews"])
    check("public: no guest surnames or negative comments", "Secretname" not in pub_text and "closet" not in pub_text)
    check("only the unlinked review warns", len(stats["warnings"]) == 1 and "1 review" in stats["warnings"][0],
          stats["warnings"])


def run_feedback():
    """Lines pasted from the feedback form's email into reviews.csv."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        write_csv(d / "reviews.csv", ["property", "platform", "date", "rating", "display_name", "origin", "text", "feature",
                                      "publish_as", "role", "code"], [
            ["home-2", "Direct", "2026-08-01", "5", "Acme Claims", "", "Great partner, fast and flexible.", "yes",
             "company", "partner", "FB-1"],
            ["home-1", "Direct", "2026-07-01", "5", "Verified guest", "Tampa, FL", "Lovely home, very attentive hosts.", "yes",
             "anonymous", "monthly_guest", "FB-2"],
            ["home-1", "Direct", "2026-06-01", "2", "Sam Secretname", "Oxford, United Kingdom", "Private complaint text.", "yes",
             "private", "guest", "FB-3"],
        ])
        cfg = dict(CONFIG, public={**CONFIG["public"], "feature_codes": []})
        (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        stats, pub = build_stats.main(["--exports", str(d), "--config", str(d / "config.json"), "--out", str(d / "out"),
                                       "--public-out", str(d / "out" / "stats.json"), "--today", "2026-09-26", "--offline"])
        pub_text = (d / "out" / "stats.json").read_text(encoding="utf-8")
    names = [r["name"] for r in pub["reviews"]]
    check("feedback: company name published as chosen", "Acme Claims" in names, names)
    check("feedback: anonymous published as chosen", "Verified guest" in names, names)
    check("feedback: private feedback never published", "Private complaint" not in pub_text and "Secretname" not in pub_text)
    check("feedback: private still counts in the rating", stats["ratings"]["count"] == 3, stats["ratings"])
    check("feedback: reviewer's city reaches the map, private city doesn't",
          "Florida" in stats["origins"]["us_states"] and "United Kingdom" not in stats["origins"]["countries"], stats["origins"])


def write_config(d):
    p = d / "config.json"
    p.write_text(json.dumps(CONFIG), encoding="utf-8")
    return p


def run_sample():
    """The committed sample: every platform format parses and nothing lands in site/."""
    site_stats = HERE.parent / "site" / "data" / "stats.json"
    before = site_stats.read_text(encoding="utf-8") if site_stats.exists() else None
    with tempfile.TemporaryDirectory() as tmp:
        stats, pub = build_stats.main(["--exports", str(HERE / "sample"), "--out", tmp, "--today", "2026-09-26", "--offline"])
    after = site_stats.read_text(encoding="utf-8") if site_stats.exists() else None
    check("sample: all four platforms parsed", set(stats["sources"]) == {"Airbnb", "Booking.com", "Vrbo", "Direct"},
          stats["sources"])
    check("sample: no warnings", not stats["warnings"], stats["warnings"])
    check("sample: never written to site/data/stats.json", pub is None and before == after)


def run_hide_names():
    h = lambda t: build_stats.hide_names(t, ["Ha"])
    check("host names hidden in published reviews", h("Ha's home was cozy. Thank you Ha!") == "[Our host]'s home was cozy. Thank you [our host]!",
          h("Ha's home was cozy. Thank you Ha!"))
    check("only whole names are hidden", h("Hawaii, Hannah, ha ha") == "Hawaii, Hannah, ha ha")


def run_marketing():
    """Airbnb performance reports and a HubSpot contacts export -> the dashboard's marketing section."""
    perf_header = ["Listing ID", "Listing title", "Internal name", "Region", "Currency", "Bookings", "Bookings YoY",
                   "Booking value", "Booking value YoY", "Nights booked", "Nights booked YoY", "Average daily rate",
                   "Average daily rate YoY", "Average length of stay", "Average length of stay YoY", "Average booking window",
                   "Average booking window YoY", "View to contact rate", "View to contact rate YoY", "Contact to book rate",
                   "Contact to book rate YoY"]

    def perf(path, first_line, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(first_line + "\n")
            w = csv.writer(f)
            w.writerow(perf_header)
            w.writerows(rows)
    row = lambda lid, title, b, value, n, v2c, c2b: [lid, title, "", "Boston", "USD", b, "", value, "", n, "", "", "", "", "",
                                                     "", "", v2c, "'-85.64%", c2b, ""]
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        small_fixture(d)
        perf(d / "perf-aug.csv", "Monthly report from 2026-08-01 to 2026-08-31",
             [row("1", "Lakeview room", "2", "500", "4", "14.22%", "9.09%"), row("2", "Loft studio", "0", "0", "0", "", ""),
              row("3", "Mystery cabin", "0", "0", "0", "", "")])
        perf(d / "perf-sep.csv", "Monthly report from 2026-09-01 to 2026-09-20",
             [row("1", "Lakeview room", "1", "300", "3", "2.65%", "106.67%")])
        perf(d / "perf-sep-again.csv", "Monthly report from 2026-09-01 to 2026-09-25",
             [row("1", "Lakeview room", "2", "450", "5", "3%", "100%")])
        write_csv(d / "hubspot-contacts.csv", ["Record ID", "First Name", "Email", "Create Date", "Lead Status", "Lifecycle Stage",
                                               "NTStays source", "NTStays medium", "NTStays campaign", "Heard about us", "NTStays lead type"], [
            ["1", "Ann", "a@x.com", "2026-09-01 10:00", "New", "Lead", "facebook", "social", "nurses-2026-09", "hospital_agency", "travel_nurse"],
            ["2", "Bo", "b@x.com", "2026-09-02 11:00", "In progress", "Lead", "facebook", "social", "nurses-2026-09", "", "travel_nurse"],
            ["3", "Cy", "c@x.com", "2026-08-15", "Connected", "Customer", "google", "organic", "", "friend", "insurance"],
            ["4", "Di", "d@x.com", "2026-09-03", "", "Subscriber", "google", "organic", "", "", ""],   # newsletter only
            ["5", "Ed", "e@x.com", "2024-01-01", "New", "Lead", "flyer", "print", "old", "", ""],       # older than 12 months
        ])
        stats, _ = build_stats.main(["--exports", tmp, "--config", str(write_config(d)), "--out", tmp, "--no-public",
                                     "--today", "2026-09-26", "--offline"])
    a, pl = stats["marketing"]["airbnb"], stats["marketing"]["pipeline"]
    check("marketing: Airbnb months found from the first line", a["months"] == ["2026-08", "2026-09"], a["months"])
    check("marketing: a month downloaded twice keeps the later file", next(r for r in a["by_home"]
          if r["month"] == "2026-09" and r["property"] == "home-1")["bookings"] == 2, a["by_home"])
    check("marketing: unfinished month flagged", a["partial"] == {"2026-09": "2026-09-25"}, a["partial"])
    lake = next(l for l in a["listings"] if l["title"] == "Lakeview room")
    check("marketing: listing rates as fractions (YoY columns ignored)", lake["months"]["2026-08"]["view_to_contact"] == 0.1422
          and lake["months"]["2026-08"]["contact_to_book"] == 0.0909, lake["months"])
    check("marketing: listings map to homes by title", lake["property"] == "home-1"
          and any("Mystery cabin" in w for w in stats["warnings"]), stats["warnings"])
    check("marketing: pipeline counts inquiries, quotes and bookings (12 months, no subscribers)",
          pl["total"] == {"key": "all", "inquiries": 3, "quoted": 2, "booked": 1}, pl["total"])
    fb = next(x for x in pl["by_source"] if x["key"] == "facebook / social")
    check("marketing: by source and campaign", fb["inquiries"] == 2 and fb["quoted"] == 1
          and pl["by_campaign"][0]["key"] == "nurses-2026-09", pl["by_source"])
    check("marketing: 'heard about us' shown as words", {x["key"] for x in pl["by_heard"]} == {"Hospital or staffing agency", "Friend or colleague"},
          pl["by_heard"])
    check("marketing: no names or emails in the stats", "a@x.com" not in json.dumps(stats) and "Ann" not in json.dumps(stats["marketing"]))
    t = stats["team"]
    check("team page: 12 months ending this month", len(t["months"]) == 12 and t["months"][-1] == "2026-09", t["months"])
    nurses = [r for r in t["pipeline"]["rows"] if r["lead_type"] == "travel_nurse"]
    check("team page: pipeline counts by audience and source", sum(r["inquiries"] for r in nurses) == 2
          and sum(r["quoted"] for r in nurses) == 1 and all(r["source"] == "facebook" for r in nurses), t["pipeline"]["rows"])
    check("team page: channel nights and stays per home, no money", t["channels"]["rows"] and all(set(r) == {"month", "channel", "property", "nights", "stays"}
          for r in t["channels"]["rows"]), t["channels"]["rows"][:2])
    check("team page: Airbnb bookings made per month and home (later download wins)", t["airbnb_perf"] == [
          {"month": "2026-08", "property": "home-1", "bookings": 2, "nights": 4},
          {"month": "2026-09", "property": "home-1", "bookings": 2, "nights": 5}], t["airbnb_perf"])
    team_json = json.dumps(t)
    check("team page: booking value and fees per month, channel and home (for percentages)", t["money"]
          and all(set(r) == {"month", "channel", "property", "value", "fees"} for r in t["money"])
          and all(r["fees"] <= r["value"] for r in t["money"]), t["money"][:2])
    check("team page: no names, emails or reservation codes", not any(x in team_json for x in ("a@x.com", "Ann", "HMAAA", "gross", "payout")))


if __name__ == "__main__":
    site_team = ROOT_SITE_TEAM = HERE.parent / "site" / "team" / "marketing-data.json"
    team_before = site_team.read_text(encoding="utf-8") if site_team.exists() else None
    run_small()
    run_formats()
    run_feedback()
    run_sample()
    run_hide_names()
    run_marketing()
    check("tests never write the marketing manager's data (site/team/marketing-data.json)",
          (site_team.read_text(encoding="utf-8") if site_team.exists() else None) == team_before)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nAll checks passed")
    sys.exit(1 if FAILS else 0)
