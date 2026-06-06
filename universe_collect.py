"""Collect the full US $1-5 universe via the EODHD screener.
Buckets the price range into narrow slices so we never hit the screener's
offset cap, and paginates each slice to exhaustion."""
import os, json, time, requests, csv

def load_key():
    with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
        for line in f:
            if line.startswith("EODHD_API_KEY"):
                return line.strip().split("=", 1)[1]

KEY = load_key()
BASE = "https://eodhd.com/api/screener"

# narrow price buckets (lo inclusive, hi exclusive) to stay under any result cap.
# Dense low-price region gets 0.05-wide slices; upper region 0.25-wide.
low = [round(1.0 + 0.05 * i, 2) for i in range(0, 20)]      # 1.00 .. 1.95
high = [round(2.0 + 0.25 * i, 2) for i in range(0, 12)]     # 2.00 .. 4.75
edges = low + high + [5.0001]
buckets = list(zip(edges[:-1], edges[1:]))

seen = {}
calls = 0
for lo, hi in buckets:
    offset = 0
    while True:
        filters = [["exchange", "=", "us"],
                   ["adjusted_close", ">=", lo],
                   ["adjusted_close", "<", hi]]
        params = {
            "api_token": KEY,
            "filters": json.dumps(filters),
            "sort": "market_capitalization.desc",
            "limit": 100,
            "offset": offset,
        }
        r = requests.get(BASE, params=params, timeout=60)
        calls += 1
        if r.status_code != 200:
            print(f"  ! {lo}-{hi} offset {offset} -> HTTP {r.status_code}: {r.text[:150]}")
            break
        rows = r.json().get("data", [])
        if not rows:
            break
        for x in rows:
            code = x.get("code")
            if code and code not in seen:
                seen[code] = x
        print(f"  bucket {lo:.2f}-{hi:.2f} offset {offset}: +{len(rows)} (total {len(seen)})")
        if len(rows) < 100:
            break
        offset += 100
        if offset >= 1000:   # screener hard cap safeguard
            print(f"  ! bucket {lo:.2f}-{hi:.2f} hit offset cap — slice may be incomplete")
            break

out = os.path.join(os.path.dirname(__file__), "universe.csv")
cols = ["code", "name", "adjusted_close", "market_capitalization", "avgvol_200d",
        "avgvol_1d", "earnings_share", "dividend_yield", "sector", "industry",
        "exchange", "refund_5d_p", "refund_1d_p"]
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for x in seen.values():
        w.writerow(x)

print(f"\nDONE: {len(seen)} unique tickers, {calls} screener calls (~{calls*5} credits)")
print(f"Saved -> {out}")
