"""Writes made-up exports (fake guests, fake money) to stats/sample/ in each platform's format.

Used by test_build_stats.py and for trying the dashboard:  python stats/sample/make_sample.py
"""
import csv
import datetime as dt
import pathlib
import random

random.seed(7)
D = pathlib.Path(__file__).parent
homes = [(185, "Property name #1"), (140, "Property name #2"), (260, "Property name #3")]
first = ["Jordan", "Taylor", "Sam", "Alex", "Riley", "Casey", "Morgan", "Jamie", "Avery", "Drew", "Quinn", "Parker"]
last = ["Smith", "Nguyen", "Garcia", "Patel", "Kim", "Brown", "Lopez", "Chen", "Miller", "Davis"]
states = [("Austin", "TX"), ("Chicago", "IL"), ("Denver", "CO"), ("Seattle", "WA"), ("Boston", "MA"), ("Atlanta", "GA"),
          ("Portland", "OR"), ("San Diego", "CA"), ("Minneapolis", "MN"), ("Nashville", "TN")]
today = dt.date(2026, 9, 26)


def stays(seed, count, start=dt.date(2024, 10, 1)):
    out, d = [], start + dt.timedelta(days=seed * 3)
    while len(out) < count and d < today + dt.timedelta(days=80):
        n = random.choice([2, 2, 3, 3, 4, 5, 7])
        out.append((d, n, d - dt.timedelta(days=random.randint(5, 90))))
        d += dt.timedelta(days=n + random.randint(1, 9))
    return out


def fmt(d):
    return d.strftime("%m/%d/%Y")


def write(name, rows):
    with open(D / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# Airbnb transaction history: one row per reservation plus payout rows.
air, origins, k = [], [], 0
for i, (rate, listing) in enumerate(homes):
    for d, n, booked in stays(i, 999):
        if random.random() < .45:
            continue
        k += 1
        code = f"HM{k:06d}XK"
        gross = round(n * rate * random.uniform(.9, 1.2) + 95, 2)
        fee = round(gross * .03, 2)
        air.append({"Date": fmt(d + dt.timedelta(days=1)), "Arriving by date": fmt(d + dt.timedelta(days=3)),
                    "Type": "Reservation", "Confirmation Code": code, "Booking date": fmt(booked), "Start date": fmt(d),
                    "End date": fmt(d + dt.timedelta(days=n)), "Nights": n,
                    "Guest": f"{random.choice(first)} {random.choice(last)}", "Listing": listing, "Details": "",
                    "Reference code": "", "Currency": "USD", "Amount": f"{gross - fee:.2f}", "Paid out": "",
                    "Service fee": f"{fee:.2f}", "Fast pay fee": "", "Cleaning fee": "95.00",
                    "Gross earnings": f"{gross:.2f}", "Occupancy taxes": "", "Earnings year": d.year})
        if random.random() < .6:
            c, s = random.choice(states)
            origins.append({"confirmation": code, "city": c, "region": s, "country": "US"})
air.append({**{key: "" for key in air[0]}, "Date": "09/01/2026", "Type": "Payout", "Details": "Transfer to Bank ****1234",
            "Currency": "USD", "Paid out": "4210.55", "Earnings year": 2026})
write("airbnb-transaction-history.csv", air)
write("guest_origins.csv", origins)

# Booking.com: one file per property, named so the property can be matched.
countries = ["us", "us", "us", "ca", "gb", "de", "mx", "au", "fr", "jp"]
for i, (rate, _) in enumerate(homes[:2]):
    rows = []
    for j, (d, n, booked) in enumerate(stays(i + 5, 14, dt.date(2025, 6, 1))):
        price = round(n * rate * 1.1 + 95, 2)
        rows.append({"Book number": 4000000000 + i * 1000 + j, "Booked by": f"{random.choice(last)}, {random.choice(first)}",
                     "Guest name(s)": f"{random.choice(first)} {random.choice(last)}", "Check-in": d.isoformat(),
                     "Check-out": (d + dt.timedelta(days=n)).isoformat(), "Booked on": booked.isoformat() + " 10:12:00",
                     "Status": "cancelled_by_guest" if j % 9 == 4 else "ok", "Rooms": 1, "People": random.randint(1, 5),
                     "Price": f"{price} USD", "Commission %": 15, "Commission amount": f"{price * .15:.2f} USD",
                     "Payment status": "Paid", "Booker country": random.choice(countries), "Travel purpose": "Leisure",
                     "Duration (nights)": n})
    write(f"booking-home-{i + 1}.csv", rows)

# Vrbo reservations.
rows = []
for j, (d, n, booked) in enumerate(stays(9, 18, dt.date(2025, 3, 1))):
    total = round(n * 260 * 1.05 + 120, 2)
    rows.append({"Reservation ID": f"HA-{8800 + j}", "Property name": "Property name #3",
                 "Status": "Cancelled" if j == 6 else "Booked", "Guest name": f"{random.choice(first)} {random.choice(last)}",
                 "Check-in": fmt(d), "Check-out": fmt(d + dt.timedelta(days=n)), "Nights": n, "Guests": random.randint(2, 8),
                 "Booked on": fmt(booked), "Total amount": f"${total:,.2f}", "Payout": f"${total * .92:,.2f}"})
write("vrbo-reservations.csv", rows)

# Direct bookings in our own format.
with open(D / "direct-bookings.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["platform", "confirmation", "property", "booked_on", "check_in", "check_out", "nights", "guests", "gross",
                "payout", "status", "guest_city", "guest_region", "guest_country"])
    w.writerow(["Direct", "D-001", "home-1", "2026-05-02", "2026-06-12", "2026-06-16", 4, 3, "820.00", "820.00", "ok", "Toronto", "ON", "CA"])
    w.writerow(["Direct", "D-002", "home-3", "2026-07-20", "2026-10-09", "2026-10-12", 3, 6, "960.00", "960.00", "ok", "Dallas", "TX", "US"])

# Reviews are copied in by hand; only feature=yes rows can reach the website.
rev = [("home-1", "Airbnb", "2026-08-18", 5, "Jordan S.", "Austin, TX", "Spotless, quiet, and the lake view at sunrise was worth the trip. Check-in was easy and the hosts answered within minutes.", "yes"),
       ("home-2", "Booking.com", "2026-07-02", 5, "Emma", "United Kingdom", "Perfect base for exploring downtown. Great bed, fast Wi-Fi, and a kitchen with everything we needed.", "yes"),
       ("home-3", "Vrbo", "2026-06-21", 5, "Priya P.", "Chicago, IL", "Room for our whole family and then some. The kids loved the backyard. We are already planning next summer.", "yes"),
       ("home-1", "Airbnb", "2026-05-10", 4, "Casey", "Denver, CO", "Lovely home. The driveway is steep, so take it slow in winter.", "no"),
       ("home-2", "Airbnb", "2026-04-03", 5, "Riley B.", "Seattle, WA", "Exactly as pictured and very clean.", "yes"),
       ("home-3", "Vrbo", "2026-03-15", 3, "Sam", "Boston, MA", "Nice house, but the hot tub was out of service during our stay.", "no")]
with open(D / "reviews.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["property", "platform", "date", "rating", "display_name", "origin", "text", "feature"])
    w.writerows(rev)
print(f"Wrote sample exports to {D}")
