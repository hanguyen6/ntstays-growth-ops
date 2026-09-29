"""Turns Airbnb, Vrbo and Booking.com exports into NTStays stats.

Put the CSV exports in stats/exports/ (git-ignored: they contain guest names), then:  python stats/build_stats.py

  stats/out/dashboard.html  PRIVATE: revenue, occupancy, channels, guest origins, reviews. Never deployed.
  site/data/stats.json      PUBLIC: only what config.json "public" allows. No guest names, no revenue.

Options: --exports DIR (default stats/exports), --today YYYY-MM-DD, --no-public (skip stats.json).
The platforms have no API for small hosts and forbid scraping, so this reads the exports you download yourself.
See SETUP.md, "Stats from Airbnb, Vrbo and Booking.com".
"""
import argparse
import csv
import datetime as dt
import html
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("WARNING:", msg, file=sys.stderr)


# ---------------------------------------------------------------- parsing helpers
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"]


def parse_date(v):
    v = (v or "").strip()
    if not v:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", v):  # "2025-03-01 14:22:10"
        v = v[:10]
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognized date {v!r}")


def parse_money(v):
    """'$1,234.50', '1 234,50 USD'-free US style, '(12.00)' -> float. Blank -> 0."""
    v = (v or "").strip()
    if not v:
        return 0.0
    neg = v.startswith("(") and v.endswith(")") or v.startswith("-")
    num = re.sub(r"[^0-9.]", "", v)
    if not num:
        return 0.0
    return -float(num) if neg else float(num)


def parse_int(v):
    v = re.sub(r"[^0-9]", "", v or "")
    return int(v) if v else None


def norm(h):
    return re.sub(r"\s+", " ", (h or "").strip().lower().lstrip("﻿"))


def pick(row, *names):
    """First non-empty value among header aliases (row keys are already normalized)."""
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v.strip()
    return ""


COUNTRIES = {
    "US": "United States", "CA": "Canada", "MX": "Mexico", "GB": "United Kingdom", "UK": "United Kingdom",
    "IE": "Ireland", "FR": "France", "DE": "Germany", "ES": "Spain", "IT": "Italy", "NL": "Netherlands",
    "BE": "Belgium", "CH": "Switzerland", "AT": "Austria", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "PL": "Poland", "PT": "Portugal", "BR": "Brazil", "AR": "Argentina", "CO": "Colombia",
    "CL": "Chile", "PE": "Peru", "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "KR": "South Korea",
    "CN": "China", "TW": "Taiwan", "HK": "Hong Kong", "SG": "Singapore", "VN": "Vietnam", "TH": "Thailand",
    "PH": "Philippines", "IN": "India", "IL": "Israel", "AE": "United Arab Emirates", "ZA": "South Africa",
}
COUNTRY_ALIASES = {"usa": "United States", "u.s.": "United States", "united states of america": "United States"}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}


def norm_country(v):
    v = (v or "").strip()
    if not v:
        return ""
    if len(v) == 2:
        return COUNTRIES.get(v.upper(), v.upper())
    return COUNTRY_ALIASES.get(v.lower(), v.title() if v.islower() or v.isupper() else v)


def norm_region(v, country):
    v = (v or "").strip()
    if country == "United States" and len(v) == 2:
        return US_STATES.get(v.upper(), v.upper())
    return v


# ---------------------------------------------------------------- reading exports
def read_grid(path):
    """Rows of cells from a .csv, .xls or .xlsx file. Excel cells keep their type (numbers, datetimes)."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd  # pip install xlrd
        sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
        return [[c.value for c in sh.row(i)] for i in range(sh.nrows)]
    if suffix == ".xlsx":
        import openpyxl  # pip install openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True)
        try:
            return [list(r) for r in wb.active.iter_rows(values_only=True)]
        finally:
            wb.close()  # read-only mode keeps the file open until closed
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # 3058369731.0 -> "3058369731"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    return str(v)


def table(grid):
    """Header row + dicts keyed by normalized header, all values as text."""
    if not grid:
        return [], []
    headers = [norm(cell_text(h)) for h in grid[0]]
    rows = []
    for r in grid[1:]:
        vals = [cell_text(c) for c in r]
        if any(v.strip() for v in vals):
            rows.append(dict(zip(headers, vals)))
    return headers, rows


def read_csv(path):
    return table(read_grid(path))


def booking(platform, code, prop, booked_on, check_in, check_out, nights, guests, gross, payout, status,
            country="", region="", city="", currency=""):
    if check_in and check_out and not nights:
        nights = (check_out - check_in).days
    if check_in and nights and not check_out:
        check_out = check_in + dt.timedelta(days=nights)
    return {"platform": platform, "code": code, "property": prop, "booked_on": booked_on, "check_in": check_in,
            "check_out": check_out, "nights": nights or 0, "guests": guests, "gross": round(gross, 2),
            "payout": round(payout, 2), "status": status, "country": country, "region": region, "city": city,
            "currency": currency}


def parse_airbnb(rows, fallback_prop):
    """Airbnb transaction history (Earnings > Export CSV). One row per money movement; group by confirmation code."""
    seen, by_code = set(), {}
    extras = {}  # code -> [amount, listing, date, kinds]
    for r in rows:
        key = tuple(sorted(r.items()))
        if key in seen:  # the same row in two overlapping exports
            continue
        seen.add(key)
        kind = pick(r, "type").lower()
        code = pick(r, "confirmation code")
        if kind == "payout" or not code:
            continue
        amount = parse_money(pick(r, "amount"))
        if kind != "reservation":  # adjustments, resolution payouts, cancellation fees (negative) and refunds
            e = extras.setdefault(code, [0.0, "", None, set()])
            e[0] += amount
            e[1] = e[1] or pick(r, "listing")
            e[2] = e[2] or parse_date(pick(r, "date")) or parse_date(pick(r, "start date"))
            e[3].add(kind)
            continue
        gross = parse_money(pick(r, "gross earnings")) or amount + parse_money(pick(r, "service fee"))
        b = by_code.get(code)
        start, end = parse_date(pick(r, "start date")), parse_date(pick(r, "end date"))
        nights = parse_int(pick(r, "nights")) or 0
        if b:  # long stays are paid in monthly pieces
            b["gross"] += gross
            b["payout"] += amount
            b["nights"] += nights
            b["check_in"] = min(d for d in (b["check_in"], start) if d) if b["check_in"] or start else None
            b["check_out"] = max(d for d in (b["check_out"], end) if d) if b["check_out"] or end else None
            continue
        by_code[code] = booking("Airbnb", code, pick(r, "listing") or fallback_prop,
                                parse_date(pick(r, "booking date")), start, end, nights, None, gross, amount,
                                "ok", currency=pick(r, "currency"))
        # first name only, used to link reviews to stays; never leaves this script
        by_code[code]["guest_first"] = (pick(r, "guest").split() or [""])[0].lower()
    for b in by_code.values():
        if b["nights"] == 0:
            b["status"] = "cancelled"
    for code, (amt, listing, day, kinds) in extras.items():
        if code in by_code:
            by_code[code]["payout"] += amt
            by_code[code]["gross"] += amt
        else:  # money with no stay behind it: a resolution payout, or a fee for a stay that was cancelled
            status = "cancelled" if any("cancel" in k for k in kinds) else "other"
            # check_in holds the transaction date so the money lands in the right month; 0 nights
            by_code[code] = booking("Airbnb", code, listing or fallback_prop, None, day, None, 0, None, amt, amt,
                                    status)
    return list(by_code.values())


def parse_booking_com(rows, fallback_prop):
    """Booking.com extranet: Reservations > Download (.xls or .csv). Cancelled and no-show rows count no money."""
    out = []
    for r in rows:
        status_raw = pick(r, "status").lower()
        cancelled = "cancel" in status_raw or "no show" in status_raw or "no_show" in status_raw
        price = parse_money(pick(r, "price", "total payment", "total price", "final amount"))
        commission = parse_money(pick(r, "commission amount", "commission"))
        country = norm_country(pick(r, "booker country", "guest country", "country"))
        prop = " ".join(filter(None, [pick(r, "property name", "property", "property id", "hotel name"),
                                      pick(r, "location")]))  # location (city) helps match room listings
        out.append(booking(
            "Booking.com", pick(r, "book number", "reservation number", "booking number"),
            prop or fallback_prop,
            parse_date(pick(r, "booked on", "booking date")), parse_date(pick(r, "check-in", "arrival")),
            parse_date(pick(r, "check-out", "departure")), parse_int(pick(r, "duration (nights)", "nights")),
            parse_int(pick(r, "people", "persons", "guests")),
            0.0 if cancelled else price, 0.0 if cancelled else price - commission,
            "cancelled" if cancelled else "ok", country=country))
    return out


VRBO = {
    "code": ["reservation id", "reservation #", "reservation number", "confirmation number", "booking id"],
    "prop": ["property name", "property", "listing", "listing name", "property id", "unit", "unit name"],
    "booked": ["booked on", "booking date", "reservation date", "date booked", "created"],
    "in": ["check-in", "check-in date", "check in", "arrival", "arrival date", "start date"],
    "out": ["check-out", "check-out date", "check out", "departure", "departure date", "end date"],
    "nights": ["nights", "number of nights", "stay length"],
    "guests": ["guests", "number of guests", "adults"],
    "gross": ["total amount", "booking total", "total", "gross booking amount", "gross", "reservation total"],
    "payout": ["payout", "your payout", "estimated payout", "owner payout", "net payout", "net"],
    "status": ["booking status", "status", "reservation status"],
    "country": ["country", "guest country", "traveler country"],
    "region": ["state", "guest state", "region"],
    "city": ["city", "guest city"],
}


def parse_vrbo(rows, fallback_prop):
    """Vrbo Financial Reporting (payout summary) or reservation export. Column names vary; add yours to VRBO
    above if a column is missed. The payout summary has one row per money movement (payment, reversal, refund),
    so rows are summed per reservation. A cancelled stay keeps whatever money it kept, with 0 nights; a stay
    refunded to zero counts as cancelled."""
    by_code, order = {}, []
    for r in rows:
        code = pick(r, *VRBO["code"]) or f"row{len(order)}"
        if code not in by_code:
            by_code[code] = {"rows": [], "gross": 0.0, "payout": 0.0}
            order.append(code)
        g = by_code[code]
        g["rows"].append(r)
        gross = parse_money(pick(r, *VRBO["gross"]))
        g["gross"] += gross
        g["payout"] += parse_money(pick(r, *VRBO["payout"])) if pick(r, *VRBO["payout"]) else gross
    out = []
    for code in order:
        g = by_code[code]
        r = g["rows"][-1]
        status = pick(r, *VRBO["status"]).lower()
        cancelled = "cancel" in status or "declin" in status or round(g["gross"], 2) <= 0
        country = norm_country(pick(r, *VRBO["country"]))
        # property id and address both go in, so either can be used in config.json "match"
        prop = " ".join(filter(None, [pick(r, "property id"), pick(r, "unit id"), pick(r, "address"),
                                      pick(r, "property name", "property", "listing", "listing name", "unit name")]))
        b = booking(
            "Vrbo", code if not code.startswith("row") else "", prop or fallback_prop,
            parse_date(pick(r, *VRBO["booked"])), parse_date(pick(r, *VRBO["in"])),
            parse_date(pick(r, *VRBO["out"])), None if cancelled else parse_int(pick(r, *VRBO["nights"])),
            parse_int(pick(r, *VRBO["guests"])), max(g["gross"], 0.0), max(g["payout"], 0.0),
            "cancelled" if cancelled else "ok", country=country,
            region=norm_region(pick(r, *VRBO["region"]), country), city=pick(r, *VRBO["city"]),
            currency=pick(r, "payout currency", "currency"))
        if cancelled:
            b["nights"], b["check_out"] = 0, None
        out.append(b)
    return out


def parse_generic(rows, fallback_prop):
    """Our own format, for direct bookings and medium-term leases: see stats/sample/direct-bookings.csv and
    stats/leases-template.csv. With monthly_rent instead of gross, gross = monthly rent x nights / 30.44."""
    out = []
    for r in rows:
        country = norm_country(pick(r, "guest_country"))
        check_in, check_out = parse_date(pick(r, "check_in")), parse_date(pick(r, "check_out"))
        nights = parse_int(pick(r, "nights")) or ((check_out - check_in).days if check_in and check_out else 0)
        gross = parse_money(pick(r, "gross"))
        if not gross and pick(r, "monthly_rent"):
            gross = round(parse_money(pick(r, "monthly_rent")) * nights / 30.44, 2)
        fees = parse_money(pick(r, "fees"))
        payout = parse_money(pick(r, "payout")) if pick(r, "payout") else gross - fees
        out.append(booking(
            pick(r, "platform") or "Direct", pick(r, "confirmation"), pick(r, "property") or fallback_prop,
            parse_date(pick(r, "booked_on")), check_in, check_out, nights, parse_int(pick(r, "guests")), gross,
            payout, "cancelled" if "cancel" in pick(r, "status").lower() else "ok", country=country,
            region=norm_region(pick(r, "guest_region"), country), city=pick(r, "guest_city")))
        out[-1]["segment"] = pick(r, "segment")  # e.g. nurse, insurance, corporate
    return out


def review(platform, prop, code, date, rating, name, text, origin="", feature=False):
    """rating is out of 5. name becomes "First L." so a full name never reaches the website."""
    parts = (name or "").replace(",", " ").split()
    display = parts[0].capitalize() + (f" {parts[-1][0].upper()}." if len(parts) > 1 and parts[-1][0].isalpha() else "") if parts else ""
    return {"platform": platform, "property": prop, "code": code, "date": date.isoformat() if date else "",
            "rating": round(rating, 2), "display_name": display, "origin": origin, "text": (text or "").strip(),
            "feature": feature}


def parse_manual_reviews(rows):
    """stats/exports/reviews.csv: property,platform,date,rating(1-5),display_name,origin,text,feature
    plus optional publish_as (initial | company | anonymous | private), role and code, as in the line the feedback
    form's email gives you. Private rows count in the ratings but are never published."""
    out = []
    for r in rows:
        rating = parse_money(pick(r, "rating"))
        if rating:
            publish_as = pick(r, "publish_as").lower() or "initial"
            rv = review(pick(r, "platform"), pick(r, "property"), pick(r, "code", "confirmation"),
                        parse_date(pick(r, "date")), rating, "", pick(r, "text"), pick(r, "origin"),
                        pick(r, "feature").lower() in ("yes", "y", "true", "1") and publish_as != "private")
            rv["display_name"] = pick(r, "display_name")  # as the reviewer chose; checked again in public_stats
            rv["publish_as"], rv["role"] = publish_as, pick(r, "role")
            if rv["origin"] and publish_as != "private":  # "Tampa, FL" -> the guest map
                rv["country"], rv["region"], rv["city"] = parse_place(rv["origin"])
            out.append(rv)
    return out


def parse_booking_reviews(rows):
    """Booking.com extranet: Guest reviews > download. Scores are out of 10; property comes from the reservation."""
    out = []
    for r in rows:
        score = parse_money(pick(r, "review score"))
        if not score:
            continue
        rv = review("Booking.com", "", pick(r, "reservation number"), parse_date(pick(r, "review date")),
                    score / 2, pick(r, "guest name"), pick(r, "positive review"))
        rv["title"] = pick(r, "review title")
        rv["negative"] = pick(r, "negative review")  # dashboard only
        out.append(rv)
    return out


def parse_vrbo_review_page(grid):
    """Vrbo's reviews page copied into a spreadsheet, one line per cell. Each stay starts with 'Res #HA-...',
    preceded by the guest's initials and name. Excel turns a '10/10' score into the date Oct 10, so a date whose
    day is 10 is read back as month/10."""
    lines = [c for r in grid for c in r if c not in (None, "")]
    starts = [i for i, v in enumerate(lines) if isinstance(v, str) and v.startswith("Res #")]
    out, stays = [], []
    for n, i in enumerate(starts):
        end = starts[n + 1] - 2 if n + 1 < len(starts) else len(lines)
        block = lines[i:end]
        name = lines[i - 1] if i else ""
        code = block[0].replace("Res #", "").strip()
        listing = block[2] if len(block) > 2 and isinstance(block[2], str) else ""
        stays.append({"code": code, "listing": listing})
        rating, posted, text = None, None, ""
        for j, v in enumerate(block):
            if rating is None and isinstance(v, (dt.datetime, dt.date)) and v.day == 10:
                rating = v.month / 2
            elif rating is None and isinstance(v, str) and re.fullmatch(r"\d{1,2}/10", v.strip()):
                rating = int(v.split("/")[0]) / 2
            elif isinstance(v, str) and v.startswith("Posted ") and posted is None:
                posted = parse_date(v[7:].strip())
                rest = [x for x in block[j + 1:j + 3] if isinstance(x, str) and x != "Show more"]
                title, text = (rest + ["", ""])[:2] if len(rest) > 1 else ("", rest[0] if rest else "")
                break
        if rating:
            rv = review("Vrbo", listing, code, posted, rating, str(name), text)
            rv["title"] = title
            out.append(rv)
    return out, stays


def docx_paragraphs(path):
    """Text paragraphs of a .docx (standard library only)."""
    import zipfile
    xml = zipfile.ZipFile(str(path)).read("word/document.xml").decode("utf-8")
    paras = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    return [p for p in paras if p]


def parse_place(text):
    """'Miami, FL' -> (United States, Florida, Miami); 'Oxford, United Kingdom' -> (United Kingdom, '', Oxford)."""
    city, _, rest = text.rpartition(", ")
    if not city:
        return "", "", ""
    if rest.upper() in US_STATES:
        return "United States", US_STATES[rest.upper()], city
    if rest in ("United States", "USA"):
        return "United States", city if city in US_STATES.values() else "", "" if city in US_STATES.values() else city
    return norm_country(rest), "", city


def parse_airbnb_review_page(paras):
    """Airbnb's reviews page copied into Word. Each guest review: profile link, first name, optional home city,
    'Rating N out of 5', month, text. 'Response from ...' blocks are the host's replies and are skipped."""
    out = []
    starts = [i for i, p in enumerate(paras) if p.startswith("HYPERLINK")] + [len(paras)]
    for a, b in zip(starts, starts[1:]):
        block = paras[a + 1:b]
        ri = next((i for i, p in enumerate(block) if re.fullmatch(r"Rating \d out of 5", p)), None)
        if ri is None or not block or block[0].startswith("Response from"):
            continue
        name = block[0]
        place = block[1] if ri == 2 else ""
        rest = [p for p in block[ri + 1:] if not re.fullmatch(r"[,\W]*", p)]
        month = parse_date("1 " + rest[0]) if rest and re.fullmatch(r"[A-Z][a-z]+ \d{4}", rest[0]) else None
        text = " ".join(p for p in rest[1:] if not p.startswith("Translated from"))
        rv = review("Airbnb", "", "", month, int(block[ri].split()[1]), name, text)
        rv["country"], rv["region"], rv["city"] = parse_place(place)
        rv["origin"] = place
        out.append(rv)
    return out


def link_airbnb_reviews(reviews, bookings):
    """Airbnb reviews carry no reservation code: match on guest first name + a checkout in the review month or the
    month before. Linked reviews give the stay its home and the guest's home city."""
    pool = [b for b in bookings if b["platform"] == "Airbnb" and b.get("guest_first") and b["check_out"]]
    linked = 0
    for rv in reviews:
        if rv["platform"] != "Airbnb" or rv["code"] or not rv["date"]:
            continue
        month = dt.date.fromisoformat(rv["date"])
        prev = (month.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        end = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        first = rv["display_name"].split()[0].lower() if rv["display_name"] else ""
        hits = [b for b in pool if b["guest_first"] == first and prev <= b["check_out"] < end]
        if len(hits) == 1:
            b = hits[0]
            rv["code"] = b["code"]
            linked += 1
            if rv.get("country") and not b["country"]:
                b["country"], b["region"], b["city"] = rv["country"], rv["region"], rv["city"]
    return linked


# ---------------------------------------------------------------- marketing: Airbnb performance, CRM pipeline
def parse_pct(v):
    """'14.22%' -> 0.1422; blank -> None."""
    m = re.fullmatch(r"(-?[0-9.]+)%", (v or "").strip().lstrip("'"))
    return round(float(m.group(1)) / 100, 4) if m else None


def parse_airbnb_performance(grid, matcher):
    """Airbnb Performance monthly report (CSV). First line "Monthly report from 2025-10-01 to 2025-10-31", then one row
    per listing: bookings, booking value, nights, view-to-contact and contact-to-book rates."""
    m = re.search(r"from (\d{4}-\d{2})-\d{2} to (\d{4}-\d{2}-\d{2})", cell_text(grid[0][0]))
    if not m:
        raise ValueError("no report month in the first line")
    _, rows = table(grid[1:])
    out = []
    for r in rows:
        if not pick(r, "listing id"):
            continue
        title, internal = pick(r, "listing title"), pick(r, "internal name")
        out.append({"month": m.group(1), "through": m.group(2), "listing_id": pick(r, "listing id"), "title": title,
                    "internal_name": internal,
                    "property": matcher.from_text(title) or matcher.from_text(internal) or "?" + title,
                    "bookings": parse_int(pick(r, "bookings")) or 0, "value": parse_money(pick(r, "booking value")),
                    "nights": parse_int(pick(r, "nights booked")) or 0,
                    "view_to_contact": parse_pct(pick(r, "view to contact rate")),
                    "contact_to_book": parse_pct(pick(r, "contact to book rate"))})
    return out


HEARD_LABELS = {"google": "Google search", "social": "Social media", "booking_site": "Airbnb, Vrbo or Booking.com",
                "hospital_agency": "Hospital or staffing agency", "insurance": "Insurance company or adjuster",
                "friend": "Friend or colleague", "stayed_before": "Stayed before", "flyer": "Flyer or sign", "other": "Other"}


def parse_crm_contacts(rows):
    """HubSpot contacts export (Contacts > Export) with the NTStays tracking columns. Keeps only the create date, the
    pipeline stage and the source: never names or emails. Stages set by the automations: lead status New (inquiry),
    In progress (reply sent), lifecycle Customer (paid)."""
    out = []
    for r in rows:
        try:
            created = parse_date(pick(r, "create date", "created date"))
        except ValueError:
            created = None
        status = re.sub(r"[\s_]+", "", pick(r, "lead status").lower())
        stage = re.sub(r"[\s_]+", "", pick(r, "lifecycle stage").lower())
        heard = pick(r, "heard about us", "ntstays heard about")
        out.append({"created": created,
                    "inquiry": bool(status) or stage in ("lead", "opportunity", "customer"),
                    "quoted": status in ("inprogress", "connected", "opendeal") or stage in ("opportunity", "customer"),
                    "booked": stage == "customer",
                    "source": pick(r, "ntstays source") or "not tracked", "medium": pick(r, "ntstays medium"),
                    "campaign": pick(r, "ntstays campaign"), "heard_about": HEARD_LABELS.get(heard, heard),
                    "lead_type": pick(r, "ntstays lead type")})
    return out


def end_of_month(month):
    y, m = map(int, month.split("-"))
    return ((dt.date(y + m // 12, m % 12 + 1, 1)) - dt.timedelta(days=1)).isoformat()


def marketing_stats(mk, today):
    """Private dashboard only: Airbnb's own listing funnel next to our website pipeline."""
    perf = {}
    for r in mk["airbnb"]:  # a month downloaded twice: the later download wins
        key = (r["month"], r["listing_id"])
        if key not in perf or r["through"] >= perf[key]["through"]:
            perf[key] = r
    months = sorted({r["month"] for r in perf.values()})[-13:]
    rows = [r for r in perf.values() if r["month"] in months]
    by_home = defaultdict(lambda: {"bookings": 0, "nights": 0, "value": 0.0})
    listings = {}
    for r in sorted(rows, key=lambda r: (r["property"], r["title"], r["month"])):
        h = by_home[(r["month"], r["property"])]
        h["bookings"] += r["bookings"]
        h["nights"] += r["nights"]
        h["value"] += r["value"]
        lst = listings.setdefault(r["listing_id"], {"title": r["title"], "internal_name": r["internal_name"],
                                                    "property": r["property"], "months": {}})
        lst["months"][r["month"]] = {k: r[k] for k in ("bookings", "nights", "view_to_contact", "contact_to_book")}
    airbnb = {"months": months,
              "partial": {r["month"]: r["through"] for r in rows if r["through"] < end_of_month(r["month"])},
              "by_home": [{"month": m, "property": p, "bookings": v["bookings"], "nights": v["nights"],
                           "value": round(v["value"], 2)} for (m, p), v in sorted(by_home.items())],
              "listings": list(listings.values())}

    start = today - dt.timedelta(days=365)
    leads = [c for c in mk["contacts"] if c["inquiry"] and c["created"] and start <= c["created"] <= today]

    def funnel(group):
        out = defaultdict(lambda: {"inquiries": 0, "quoted": 0, "booked": 0})
        for c in leads:
            g = out[group(c)]
            g["inquiries"] += 1
            g["quoted"] += c["quoted"]
            g["booked"] += c["booked"]
        return sorted(({"key": k, **v} for k, v in out.items() if k), key=lambda x: (-x["booked"], -x["inquiries"], x["key"]))

    pipeline = {"contacts_file": bool(mk["contacts"]), "window": [start.isoformat(), today.isoformat()],
                "total": funnel(lambda c: "all")[0] if leads else {"inquiries": 0, "quoted": 0, "booked": 0},
                "by_month": sorted(funnel(lambda c: month_key(c["created"])), key=lambda x: x["key"]),
                "by_source": funnel(lambda c: c["source"] + (f" / {c['medium']}" if c["medium"] else "")),
                "by_campaign": funnel(lambda c: c["campaign"]),
                "by_heard": funnel(lambda c: c["heard_about"])}
    return {"airbnb": airbnb, "pipeline": pipeline}


def detect(headers, filename):
    h = set(headers)
    if {"confirmation code", "type"} <= h:
        return "airbnb", parse_airbnb
    if "book number" in h or "booker country" in h or ({"reservation number", "arrival"} <= h):
        return "booking", parse_booking_com
    if {"platform", "check_in"} <= h:
        return "generic", parse_generic
    if "vrbo" in filename.lower() or h & set(VRBO["code"]):
        return "vrbo", parse_vrbo
    return None, None


class PropertyMatcher:
    def __init__(self, properties):
        self.props = properties

    def from_text(self, text):
        t = (text or "").lower()
        for p in self.props:
            if any(m.lower() in t for m in [p["id"]] + p.get("match", []) if m):
                return p["id"]
        return None


def load_exports(folder, matcher):
    bookings, reviews, origins = [], [], {}
    marketing = {"airbnb": [], "contacts": []}
    files = sorted(p for p in pathlib.Path(folder).iterdir() if p.suffix.lower() in (".csv", ".xls", ".xlsx", ".docx"))
    if not files:
        warn(f"no CSV or Excel files in {folder}")
    for path in files:
        if path.suffix.lower() == ".docx":
            paras = docx_paragraphs(path)
            if any(re.fullmatch(r"Rating \d out of 5", p) for p in paras):
                got = parse_airbnb_review_page(paras)
                print(f"{path.name}: Airbnb reviews page, {len(got)} reviews")
                reviews += got
            else:
                warn(f"{path.name}: Word file without Airbnb reviews; skipped")
            continue
        grid = read_grid(path)
        headers, rows = table(grid)
        name = path.name.lower()
        if grid and grid[0] and cell_text(grid[0][0]).startswith("Monthly report from"):
            try:
                got = parse_airbnb_performance(grid, matcher)
            except ValueError as e:
                warn(f"{path.name}: {e}; file skipped")
                continue
            print(f"{path.name}: Airbnb performance report {got[0]['month'] if got else ''}, {len(got)} listings")
            for t in sorted({r["title"] for r in got if r["property"].startswith("?")}):
                warn(f"{path.name}: Airbnb listing {t!r} matches no property in config.json")
            marketing["airbnb"] += got
            continue
        if {"lead status", "lifecycle stage"} <= set(headers):
            got = parse_crm_contacts(rows)
            print(f"{path.name}: HubSpot contacts export, {len(got)} contacts")
            if got and "ntstays source" not in headers:
                warn(f"{path.name}: no \"NTStays source\" column; add the tracking columns to the export (SETUP.md)")
            marketing["contacts"] += got
            continue
        if name.startswith("reviews"):
            reviews += parse_manual_reviews(rows)
            continue
        if "review score" in headers:
            got = parse_booking_reviews(rows)
            print(f"{path.name}: Booking.com reviews, {len(got)}")
            reviews += got
            continue
        if any(isinstance(c, str) and c.startswith("Res #HA-") for r in grid[:40] for c in r):
            got, _ = parse_vrbo_review_page(grid)
            print(f"{path.name}: Vrbo reviews page, {len(got)} reviews")
            reviews += got
            continue
        if name.startswith("guest_origins"):
            for r in rows:
                if pick(r, "confirmation"):
                    origins[pick(r, "confirmation")] = r
            continue
        kind, parser = detect(headers, name)
        if not parser:
            warn(f"{path.name}: not recognized as an Airbnb, Vrbo, Booking.com or generic export "
                 f"(headers: {', '.join(headers[:12])})")
            continue
        fallback = matcher.from_text(path.stem) or ""
        try:
            got = parser(rows, fallback)
        except ValueError as e:
            warn(f"{path.name}: {e}; file skipped")
            continue
        print(f"{path.name}: {kind}, {len(got)} bookings")
        bookings += got
    # Resolve properties, merge guest origins, drop duplicates across files.
    uniq = {}
    for b in bookings:
        b["property"] = matcher.from_text(b["property"]) or ("?" + b["property"] if b["property"] else "?unknown")
        o = origins.get(b["code"])
        if o:
            b["country"] = norm_country(pick(o, "country")) or b["country"] or ""
            b["region"] = norm_region(pick(o, "region", "state"), b["country"]) or b["region"]
            b["city"] = pick(o, "city") or b["city"]
        key = (b["platform"], b["code"]) if b["code"] else id(b)
        uniq[key] = b
    bookings = list(uniq.values())
    for p in sorted({b["property"] for b in bookings if b["property"].startswith("?")}):
        warn(f"listing {p[1:]!r} matches no property in config.json; add it to that property's \"match\" list")
    currencies = {b["currency"] for b in bookings if b["currency"]}
    if len(currencies) > 1:
        warn(f"exports mix currencies {sorted(currencies)}; totals add them as if they were the same")
    # Reviews: property from the reservation they belong to, else from the listing text.
    linked = link_airbnb_reviews(reviews, bookings)
    prop_by_code = {b["code"]: b["property"] for b in bookings if b["code"] and not b["property"].startswith("?")}
    unmatched = 0
    for rv in reviews:
        rv["property"] = prop_by_code.get(rv["code"]) or matcher.from_text(rv["property"]) or "?unmatched"
        unmatched += rv["property"] == "?unmatched"
    airbnb_page = sum(1 for rv in reviews if rv["platform"] == "Airbnb" and "country" in rv)
    if airbnb_page:
        print(f"Airbnb reviews linked to a stay: {linked} of {airbnb_page}")
    if unmatched:
        warn(f"{unmatched} review(s) couldn't be linked to a stay, so their home is unknown; they count in the "
             f"overall rating but not per home")
    return bookings, reviews, marketing


# ---------------------------------------------------------------- metrics
def month_key(d):
    return f"{d.year}-{d.month:02d}"


def nights_ledger(bookings):
    """One entry per booked night, with that night's share of the money. Cancellation fees land on check-in/booking day."""
    ledger = []
    for b in bookings:
        if b["status"] == "ok" and b["nights"] and b["check_in"]:
            n = b["nights"]
            for i in range(n):
                ledger.append((b["check_in"] + dt.timedelta(days=i), b, b["gross"] / n, b["payout"] / n, 1))
        elif b["gross"] or b["payout"]:
            day = b["check_in"] or b["booked_on"]
            if day:
                ledger.append((day, b, b["gross"], b["payout"], 0))
    return ledger


def summarize(entries, stays, available):
    gross = sum(e[2] for e in entries)
    payout = sum(e[3] for e in entries)
    nights = sum(e[4] for e in entries)  # booked nights; two rooms in one home on the same night = 2
    occupied = len({(e[1]["property"], e[0]) for e in entries if e[4]})  # home-nights with at least one guest
    lead = [(s["check_in"] - s["booked_on"]).days for s in stays if s["booked_on"] and s["check_in"]]
    guests = [s["guests"] for s in stays if s["guests"]]
    return {
        "gross": round(gross, 2), "payout": round(payout, 2), "fees": round(gross - payout, 2),
        "nights": nights, "occupied": occupied, "stays": len(stays), "available": available,
        "occupancy": round(occupied / available, 4) if available else None,
        "adr": round(gross / nights, 2) if nights else None,
        "revpar": round(gross / available, 2) if available else None,
        "avg_stay": round(sum(s["nights"] for s in stays) / len(stays), 1) if stays else None,
        "avg_lead_days": round(sum(lead) / len(lead)) if lead else None,
        "avg_guests": round(sum(guests) / len(guests), 1) if guests else None,
    }


def available_nights(prop, start, end):
    since = parse_date(prop.get("hosting_since")) or start
    s = max(start, since)
    return max((end - s).days, 0)


def place_homes(guests):
    """[(city, US state or '', country, [home ids guests from there stayed at])], for the map's routes."""
    homes = defaultdict(set)
    for g in guests:
        if g["country"] and g.get("city"):
            key = (g["city"], g.get("region", "") if g["country"] == "United States" else "", g["country"])
            prop = g.get("property") or ""
            homes[key].update([prop] if prop and not prop.startswith("?") else [])
    return [(*k, sorted(v)) for k, v in sorted(homes.items())]


def compute(bookings, reviews, config, today, marketing=None):
    props = config["properties"]
    prop_ids = [p["id"] for p in props] + sorted({b["property"] for b in bookings} - {p["id"] for p in props})
    names = {p["id"]: p.get("name", p["id"]) for p in props}
    ok = [b for b in bookings if b["status"] == "ok" and b["nights"]]
    ledger = nights_ledger(bookings)
    w_start, w_end = today - dt.timedelta(days=365), today

    def in_window(d):
        return w_start <= d < w_end

    past = [e for e in ledger if e[0] < today]
    l12 = [e for e in ledger if in_window(e[0])]
    stays_l12 = [b for b in ok if b["check_in"] and in_window(b["check_in"])]
    stays_all = [b for b in ok if b["check_in"] and b["check_in"] < today]
    avail_l12 = {p["id"]: available_nights(p, w_start, w_end) for p in props}

    per_property = []
    for pid in prop_ids:
        per_property.append({
            "id": pid, "name": names.get(pid, pid.lstrip("?")),
            "l12m": summarize([e for e in l12 if e[1]["property"] == pid],
                              [s for s in stays_l12 if s["property"] == pid], avail_l12.get(pid, 0)),
            "all_time": summarize([e for e in past if e[1]["property"] == pid],
                                  [s for s in stays_all if s["property"] == pid], None),
        })

    # Monthly, last 24 months, by property.
    months = []
    y, m = today.year, today.month
    for _ in range(24):
        months.append(f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    monthly = {mk: {pid: {"gross": 0.0, "nights": 0} for pid in prop_ids} for mk in months}
    for d, b, g, _, n in ledger:
        mk = month_key(d)
        if mk in monthly:
            monthly[mk][b["property"]]["gross"] += g
            monthly[mk][b["property"]]["nights"] += n
    monthly_rows = [{"month": mk, **{pid: {"gross": round(v["gross"], 2), "nights": v["nights"]}
                                     for pid, v in monthly[mk].items()}} for mk in months]

    channels = defaultdict(lambda: {"gross": 0.0, "payout": 0.0, "nights": 0, "stays": 0})
    for _, b, g, p, n in l12:
        c = channels[b["platform"]]
        c["gross"] += g
        c["payout"] += p
        c["nights"] += n
    for s in stays_l12:
        channels[s["platform"]]["stays"] += 1
    channel_rows = sorted(({"platform": k, **{kk: round(vv, 2) for kk, vv in v.items()}}
                           for k, v in channels.items()), key=lambda r: -r["gross"])

    def stay_type(b):
        return "Medium-term (28+ nights)" if b["nights"] >= 28 else "Short-term"

    def by_type(entries, stays):
        out = {}
        for t in ("Short-term", "Medium-term (28+ nights)"):
            es = [e for e in entries if stay_type(e[1]) == t]
            ss = [s for s in stays if stay_type(s) == t]
            out[t] = {"gross": round(sum(e[2] for e in es), 2), "nights": sum(e[4] for e in es), "stays": len(ss),
                      "avg_stay": round(sum(s["nights"] for s in ss) / len(ss), 1) if ss else None}
        return out
    stay_types = {"l12m": by_type(l12, stays_l12), "all_time": by_type(past, stays_all)}

    ahead = [e for e in ledger if today <= e[0] < today + dt.timedelta(days=90)]
    on_books = {"nights": sum(e[4] for e in ahead), "gross": round(sum(e[2] for e in ahead), 2),
                "stays": len({id(e[1]) for e in ahead if e[4]})}
    cancelled = [b for b in bookings if b["status"] == "cancelled"]

    # Where guests come from: US guests by state, everyone else by country.
    origin_counter, countries, states = Counter(), set(), set()
    known = 0
    # stays, plus guests known only from a review that couldn't be linked to a stay
    stay_codes = {s["code"] for s in stays_all if s["code"]}
    guests = stays_all + [r for r in reviews if r.get("country") and r["code"] not in stay_codes]
    for s in guests:
        if not s["country"]:
            continue
        known += 1
        countries.add(s["country"])
        if s["country"] == "United States" and s["region"]:
            states.add(s["region"])
            origin_counter[s["region"]] += 1
        elif s["country"] == "United States":
            origin_counter["United States (state unknown)"] += 1
        else:
            origin_counter[s["country"]] += 1
    origins = {"stays_with_origin": known, "stays_total": len(guests), "countries": sorted(countries),
               "us_states": sorted(states), "top": [{"name": k, "stays": v} for k, v in origin_counter.most_common(12)],
               "by_state": {k: v for k, v in origin_counter.items() if k in states},
               "by_country": {k: v for k, v in origin_counter.items() if k in countries and k != "United States"},
               "places": place_homes(guests)}

    feature_codes = set(config.get("public", {}).get("feature_codes", []))
    review_rows = [{**r, "feature": r["feature"] or (r["code"] in feature_codes)} for r in reviews]
    rating_by_prop = {}
    for pid in prop_ids:
        rs = [r["rating"] for r in review_rows if r["property"] == pid]
        if rs:
            rating_by_prop[pid] = {"avg": round(sum(rs) / len(rs), 2), "count": len(rs),
                                   "dist": {str(k): sum(1 for x in rs if round(x) == k) for k in range(5, 0, -1)}}
    all_ratings = [r["rating"] for r in review_rows]

    return {
        "today": today.isoformat(), "window": [w_start.isoformat(), w_end.isoformat()],
        "currency": config.get("currency", "USD"),
        "properties": [{"id": pid, "name": names.get(pid, pid.lstrip("?"))} for pid in prop_ids],
        "total_l12m": summarize(l12, stays_l12, sum(avail_l12.values())),
        "total_all_time": summarize(past, stays_all, None),
        "per_property": per_property, "monthly": monthly_rows, "channels": channel_rows, "stay_types": stay_types,
        "on_the_books_90d": on_books, "cancelled": len(cancelled), "origins": origins,
        "ratings": {"avg": round(sum(all_ratings) / len(all_ratings), 2) if all_ratings else None,
                    "count": len(all_ratings), "by_property": rating_by_prop},
        "reviews": review_rows, "warnings": WARNINGS,
        "sources": dict(Counter(b["platform"] for b in bookings)),
        "marketing": marketing_stats(marketing or {"airbnb": [], "contacts": []}, today),
    }


GEOCACHE = HERE / "geocache.json"  # place name -> [lat, lon]; only city names, safe to commit
OFFLINE = False


def geocode(city, region, country):
    """City coordinates from OpenStreetMap's Nominatim, cached in geocache.json (one lookup per new city)."""
    import time
    import urllib.parse
    import urllib.request
    key = ", ".join(x for x in (city, region, country) if x)
    cache = json.loads(GEOCACHE.read_text(encoding="utf-8")) if GEOCACHE.exists() else {}
    if key in cache:
        return cache[key]
    if OFFLINE:
        return None
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": key, "format": "json", "limit": 1})
    try:
        time.sleep(1.1)  # Nominatim usage policy: at most one request per second
        req = urllib.request.Request(url, headers={"User-Agent": "NTStays-stats/1.0 (hello@ntstays.com)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            hits = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # offline or blocked: skip this place, try again next run
        warn(f"couldn't look up {key!r} for the map ({e}); it will be retried next run")
        return None
    ll = [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None
    cache[key] = ll
    GEOCACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=1) + "\n", encoding="utf-8")
    if not ll:
        warn(f"no map location found for {key!r}")
    return ll


def hide_names(text, names):
    """Replaces our own names in a guest's words with "[our host]" (the brackets show it's our edit)."""
    for n in names:
        text = re.sub(rf"\b{re.escape(n)}'s\b", "[our host]'s", text)
        text = re.sub(rf"\b{re.escape(n)}\b", "[our host]", text)
    return re.sub(r"(^|[.!?]\s+)\[our host\]", lambda m: m.group(1) + "[Our host]", text)


def public_stats(stats, config):
    """The only data that reaches the public website. Aggregates and hand-picked reviews, nothing else."""
    pub = config.get("public", {})
    out = {"generated": stats["today"]}
    if pub.get("stays_hosted"):
        out["stays_hosted"] = stats["total_all_time"]["stays"]
    if pub.get("occupancy") and stats["total_l12m"]["occupancy"] is not None:
        out["occupancy_12m"] = stats["total_l12m"]["occupancy"]
    if pub.get("guest_origins"):
        o = stats["origins"]
        out["guest_countries"] = len(o["countries"])
        out["guest_us_states"] = len(o["us_states"])
        out["top_origins"] = [t["name"] for t in o["top"] if "unknown" not in t["name"]][:8]
        # For the "where guests come from" map: which places, not how many guests (no counts, no names).
        out["origin_states"] = sorted(o["by_state"])
        out["origin_countries"] = sorted(o["by_country"])
        places = []
        for city, region, country, homes in o["places"]:
            ll = geocode(city, region, country)
            if ll:
                abbr = next((k for k, v in US_STATES.items() if v == region), region)
                places.append({"name": f"{city}, {abbr if country == 'United States' else country}",
                               "lat": round(ll[0], 1), "lon": round(ll[1], 1),  # ~10 km, city level only
                               "to": homes})  # which of our homes (for the route lines); empty = not known
        out["origin_places"] = places
    if pub.get("ratings") and stats["ratings"]["count"]:
        out["rating"] = {"avg": stats["ratings"]["avg"], "count": stats["ratings"]["count"]}
        out["properties"] = {pid: {"rating": v["avg"], "reviews": v["count"]}
                             for pid, v in stats["ratings"]["by_property"].items() if not pid.startswith("?")}
    if pub.get("featured_reviews"):
        featured = sorted((r for r in stats["reviews"] if r["feature"] and r["rating"] >= 4 and r["text"]
                           and r.get("publish_as") != "private"),
                          key=lambda r: r["date"], reverse=True)[:pub.get("max_reviews", 6)]
        out["reviews"] = []
        for r in featured:
            name = r["display_name"].split()
            if r.get("publish_as") in ("company", "anonymous"):
                pass  # the reviewer chose this exact name ("Acme Claims", "Verified guest")
            elif len(name) > 2 or (len(name) == 2 and len(name[1].rstrip(".")) > 1):
                warn(f"review display_name {r['display_name']!r} looks like a full name; use a first name "
                     f"and initial (only the first word is published)")
                name = name[:1]
            text = hide_names(r["text"], pub.get("hide_names", []))
            if len(text) > 420:  # end on a whole sentence
                cut = max(text.rfind(". ", 0, 400), text.rfind("! ", 0, 400))
                text = text[:cut + 1] if cut > 80 else text[:400].rsplit(" ", 1)[0] + "..."
            date = parse_date(r["date"]) if r["date"] else None
            out["reviews"].append({"property": r["property"], "platform": r["platform"], "rating": r["rating"],
                                   "name": " ".join(name), "origin": r["origin"], "text": text,
                                   "when": date.strftime("%B %Y") if date else ""})
    return out


# ---------------------------------------------------------------- marketing manager's dashboard (site/team, sign-in only)
LEAD_TYPES = {"travel_nurse": "Travel nurses", "insurance": "Insurance housing", "professional": "Professionals",
              "family": "Families", "owner": "Property owners", "guest": "Other guests", "other": "Other"}


def team_stats(bookings, marketing, config, today):
    """The three marketing metrics, as small count tables the page filters itself: pipeline conversion (HubSpot
    export), direct booking share (booking exports, nights and stays, never money) and where bookings come from.
    Counts only: no names, emails, reservation codes or revenue."""
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append(f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    start = dt.date(int(months[0][:4]), int(months[0][5:]), 1)

    cube = defaultdict(lambda: [0, 0, 0])
    for c in marketing["contacts"]:
        if c["inquiry"] and c["created"] and start <= c["created"] <= today:
            k = (month_key(c["created"]), c.get("lead_type") or "unknown", c["source"],
                 c["medium"], c["campaign"])
            cube[k][0] += 1
            cube[k][1] += c["quoted"]
            cube[k][2] += c["booked"]

    nights = defaultdict(int)
    # Booking value and platform fees per month, channel and home, for the page's percentages (revenue share, fee %).
    # The page shows only percentages; these amounts sit behind the sign-in.
    money = defaultdict(lambda: [0.0, 0.0])
    for d, b, g, p, n in nights_ledger(bookings):
        if month_key(d) in months:
            if n:
                nights[(month_key(d), b["platform"], b["property"])] += n
            m = money[(month_key(d), b["platform"], b["property"])]
            m[0] += g
            m[1] += g - p
    stays = Counter((month_key(b["check_in"]), b["platform"], b["property"]) for b in bookings
                    if b["status"] == "ok" and b["nights"] and b["check_in"] and month_key(b["check_in"]) in months)

    # Airbnb bookings made per month, from the performance reports (a month downloaded twice: the later file wins)
    perf = {}
    for r in marketing["airbnb"]:
        k = (r["month"], r["listing_id"])
        if k not in perf or r["through"] >= perf[k]["through"]:
            perf[k] = r
    airbnb_perf = defaultdict(lambda: {"bookings": 0, "nights": 0})
    for (mo, _), r in perf.items():
        if mo in months and (r["bookings"] or r["nights"]):
            airbnb_perf[(mo, r["property"])]["bookings"] += r["bookings"]
            airbnb_perf[(mo, r["property"])]["nights"] += r["nights"]

    return {
        "generated": today.isoformat(), "months": months,
        "lead_types": LEAD_TYPES,
        "airbnb_perf": [{"month": mo, "property": pid, **v} for (mo, pid), v in sorted(airbnb_perf.items())],
        "pipeline": {"has_data": bool(marketing["contacts"]),
                     "rows": [{"month": k[0], "lead_type": k[1], "source": k[2], "medium": k[3], "campaign": k[4],
                               "inquiries": v[0], "quoted": v[1], "booked": v[2]} for k, v in sorted(cube.items())]},
        "money": [{"month": k[0], "channel": k[1], "property": k[2], "value": round(v[0], 2), "fees": round(v[1], 2)}
                  for k, v in sorted(money.items()) if v[0]],
        "channels": {"has_direct": any(b["platform"] == "Direct" for b in bookings),
                     "rows": [{"month": k[0], "channel": k[1], "property": k[2], "nights": nights[k], "stays": stays.get(k, 0)}
                              for k in sorted(set(nights) | set(stays))]},
        # What each campaign or source cost, for cost per booking (config.json "marketing_costs", USD, whole window)
        "costs": {k: v for k, v in config.get("marketing_costs", {}).items() if not k.startswith("_")},
    }


def team_html(team):
    """A copy of the team page with its data inside, to preview on this computer (stats/out/marketing.html)."""
    tpl = (ROOT / "site" / "team" / "marketing.html").read_text(encoding="utf-8")
    return tpl.replace("/*__TEAM_DATA__*/null", json.dumps(team).replace("</", "<\\/"))


# ---------------------------------------------------------------- private dashboard
def dashboard_html(stats):
    tpl = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    data = json.dumps(stats, default=str).replace("</", "<\\/")
    return tpl.replace("/*__STATS__*/null", data).replace("__TITLE__", html.escape(f"NTStays stats {stats['today']}"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exports", default=str(HERE / "exports"))
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--public-out", help="default site/data/stats.json (not written for the sample data)")
    ap.add_argument("--no-public", action="store_true")
    ap.add_argument("--team-out", help="default site/team/marketing-data.json (the marketing manager's sign-in page)")
    ap.add_argument("--no-team", action="store_true", help="don't write the marketing manager's data")
    ap.add_argument("--today")
    ap.add_argument("--offline", action="store_true", help="don't look up new map locations")
    a = ap.parse_args(argv)
    WARNINGS.clear()
    if pathlib.Path(a.exports).resolve() == (HERE / "sample").resolve():
        if a.config == str(HERE / "config.json"):
            a.config = str(HERE / "sample" / "config.json")  # the sample's made-up listing names
        if not a.public_out:
            a.no_public = True  # never put made-up reviews on the live site
        if not a.team_out:
            a.no_team = True
    # The marketing manager's page only ever gets numbers from the real exports folder (never from tests or other
    # folders), unless --team-out names another file.
    if pathlib.Path(a.exports).resolve() != (HERE / "exports").resolve() and not a.team_out:
        a.no_team = True
    if not a.public_out:
        a.public_out = str(ROOT / "site" / "data" / "stats.json")
    if not a.team_out:
        a.team_out = str(ROOT / "site" / "team" / "marketing-data.json")

    config = json.loads(pathlib.Path(a.config).read_text(encoding="utf-8"))
    today = parse_date(a.today) if a.today else dt.date.today()
    bookings, reviews, marketing = load_exports(a.exports, PropertyMatcher(config["properties"]))
    stats = compute(bookings, reviews, config, today, marketing)

    global OFFLINE
    OFFLINE = a.offline
    pub = None if a.no_public else public_stats(stats, config)  # before the dashboard, so its warnings show there
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.html").write_text(dashboard_html(stats), encoding="utf-8")
    print(f"Private dashboard: {out / 'dashboard.html'}")
    team = team_stats(bookings, marketing, config, today)
    stats["team"] = team
    (out / "marketing.html").write_text(team_html(team), encoding="utf-8")
    print(f"Marketing preview: {out / 'marketing.html'}")
    if not a.no_team:
        tp = pathlib.Path(a.team_out)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps(team, indent=1) + "\n", encoding="utf-8")
        print(f"Marketing data:    {tp}  (sign-in page ntstays.com/team/marketing; commit and push to update)")
    if pub is not None:
        p = pathlib.Path(a.public_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(pub, indent=2) + "\n", encoding="utf-8")
        print(f"Public stats:      {p}  (review it, then commit and push to publish)")
    t = stats["total_l12m"]
    print(f"Last 12 months: {t['stays']} stays, {t['nights']} nights, gross {t['gross']:,.0f} {stats['currency']}, "
          f"occupancy {t['occupancy'] or 0:.0%}")
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s) above; they also show at the top of the dashboard.")
    return stats, pub


if __name__ == "__main__":
    main()
