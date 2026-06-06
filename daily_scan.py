"""
daily_scan.py  —  Full automated daily scan: $1–$5 US stocks, 30-point scoring
Runs every day at 2:00 AM (Saudi time).
"""

import os, sys, json, csv, glob, time, datetime, shutil, subprocess
import math, statistics

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
PARTS = os.path.join(BASE, "parts")
LOGS  = os.path.join(BASE, "logs")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(PARTS,  exist_ok=True)
os.makedirs(LOGS,   exist_ok=True)

TODAY     = datetime.date.today().strftime('%Y%m%d')
DATE_STR  = datetime.date.today().strftime('%B %d, %Y')
LOG_FILE  = os.path.join(LOGS, f"scan_{TODAY}.log")

def log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + "\n")

# ── Step 1: Clear old cache (>1 day old) and old parts ────────────────────────
def clear_stale():
    log("Clearing yesterday's cache and parts...")
    removed = 0
    cutoff = time.time() - 20 * 3600  # older than 20 hours
    for fn in glob.glob(os.path.join(CACHE, "*.json")):
        if os.path.getmtime(fn) < cutoff:
            os.remove(fn)
            removed += 1
    for fn in glob.glob(os.path.join(PARTS, "*.json")):
        os.remove(fn)
    log(f"  Removed {removed} stale cache files, cleared parts.")

# ── Step 2: Re-collect universe ────────────────────────────────────────────────
def refresh_universe():
    log("Refreshing $1–$5 US stock universe from EODHD screener...")
    import score_engine as se
    tickers = se.collect_universe()
    log(f"  Universe: {len(tickers)} stocks")
    return tickers

# ── Step 3: Run all chunks sequentially ───────────────────────────────────────
def run_all_chunks():
    log("Starting scoring in 8 chunks (sequential, 8 workers each)...")
    import score_engine as se

    universe = []
    universe_path = os.path.join(BASE, "universe.csv")
    if not os.path.exists(universe_path):
        log("  universe.csv not found — re-collecting...")
        se.collect_universe()

    with open(universe_path, encoding='utf-8') as f:
        universe = [row['code'] for row in csv.DictReader(f)]

    total = len(universe)
    chunk_size = max(1, math.ceil(total / 8))
    log(f"  {total} stocks → 8 chunks of ~{chunk_size} each")

    for chunk_num in range(8):
        offset = chunk_num * chunk_size
        actual_size = min(chunk_size, total - offset)
        if actual_size <= 0:
            break
        log(f"  Chunk {chunk_num+1}/8: stocks {offset}–{offset+actual_size-1} ...")
        try:
            se.run_chunk(offset, actual_size, workers=8)
            log(f"  Chunk {chunk_num+1}/8: done ✓")
        except Exception as e:
            log(f"  Chunk {chunk_num+1}/8: ERROR — {e}")

# ── Step 4: Combine parts + build HTML ────────────────────────────────────────
def build_report():
    log("Combining results and building HTML report...")

    part_files = sorted(glob.glob(os.path.join(PARTS, "part_*.json")))
    if not part_files:
        log("  ERROR: No part files found. Scoring may have failed.")
        return None

    all_results = []
    for f in part_files:
        with open(f, encoding='utf-8') as fh:
            all_results.extend(json.load(fh))

    all_results.sort(key=lambda x: float(x.get('final', 0) or 0), reverse=True)
    scored = [r for r in all_results if float(r.get('final', 0) or 0) > 0]

    log(f"  Total scored: {len(scored)} stocks")

    # Save master CSV
    master_csv = os.path.join(BASE, f"master_ranked_{TODAY}.csv")
    if scored:
        keys = list(scored[0].keys())
        with open(master_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(scored)
        log(f"  CSV saved: master_ranked_{TODAY}.csv")

    # Build HTML
    def score_color(s):
        s = float(s or 0)
        if s >= 70: return '#00c853'
        if s >= 60: return '#64dd17'
        if s >= 50: return '#ffd600'
        if s >= 40: return '#ff6d00'
        return '#d50000'

    def action_badge(a):
        a = str(a or '')
        if 'confidence' in a:
            return '<span style="background:#00c853;color:#000;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">STRONG BUY</span>'
        if 'caution' in a:
            return '<span style="background:#ffd600;color:#000;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">BUY</span>'
        return '<span style="background:#455a64;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">WATCH</span>'

    def _clean_sector(s):
        if s is None: return ''
        s = str(s)
        return '' if s in ('nan', 'None', 'NaN', '') else s
    sectors = sorted(set(_clean_sector(r.get('sector')) for r in scored if _clean_sector(r.get('sector'))))
    sector_opts = ''.join(f'<option value="{s}">{s}</option>' for s in sectors)

    rows_html_parts = []
    for i, r in enumerate(scored, 1):
        code    = r.get('code', '')
        name    = r.get('name', '')[:35]
        price   = float(r.get('price', 0) or 0)
        final   = float(r.get('final', 0) or 0)
        trend   = float(r.get('trend', 0) or 0)
        mom     = float(r.get('momentum', 0) or 0)
        volume  = float(r.get('volume', 0) or 0)
        pattern = float(r.get('pattern', 0) or 0)
        action  = r.get('action', '')
        sector  = _clean_sector(r.get('sector'))
        mcap_raw = float(r.get('mcap', 0) or 0)
        mcap    = f"${mcap_raw/1e9:.2f}B" if mcap_raw >= 1e9 else f"${mcap_raw/1e6:.0f}M" if mcap_raw >= 1e6 else "N/A"
        vol_raw  = float(r.get('avgvol', 0) or 0)
        avgvol  = f"{vol_raw/1e6:.1f}M" if vol_raw >= 1e6 else f"{vol_raw/1e3:.0f}K" if vol_raw >= 1e3 else "N/A"
        sc = score_color(final)
        row_bg = '#1a2332' if i % 2 == 0 else '#151e2d'

        rows_html_parts.append(
            f'<tr style="background:{row_bg}" onmouseover="this.style.background=\'#1e3a5f\'" onmouseout="this.style.background=\'{row_bg}\'">'
            f'<td style="text-align:center;color:#607d8b;font-size:12px">{i}</td>'
            f'<td style="font-weight:bold;color:#4fc3f7;font-size:14px">{code}</td>'
            f'<td style="color:#cfd8dc;font-size:12px">{name}</td>'
            f'<td style="text-align:right;color:#80cbc4">${price:.2f}</td>'
            f'<td style="text-align:center"><span style="color:{sc};font-size:18px;font-weight:bold">{final:.0f}</span></td>'
            f'<td style="text-align:center;color:#aaa;font-size:11px">{trend:.0f}</td>'
            f'<td style="text-align:center;color:#aaa;font-size:11px">{mom:.0f}</td>'
            f'<td style="text-align:center;color:#aaa;font-size:11px">{volume:.0f}</td>'
            f'<td style="text-align:center;color:#aaa;font-size:11px">{pattern:.0f}</td>'
            f'<td style="text-align:center">{action_badge(action)}</td>'
            f'<td style="color:#90a4ae;font-size:11px">{sector[:20]}</td>'
            f'<td style="text-align:right;color:#78909c;font-size:11px">{mcap}</td>'
            f'<td style="text-align:right;color:#78909c;font-size:11px">{avgvol}</td>'
            f'</tr>'
        )

    rows_html   = '\n'.join(rows_html_parts)
    strong_count = sum(1 for r in scored if 'confidence' in str(r.get('action', '')))
    ge60        = sum(1 for r in scored if float(r.get('final', 0) or 0) >= 60)
    top_score   = float(scored[0].get('final', 0)) if scored else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>US Market Scan $1-$5 | {DATE_STR}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0d1421; color:#eceff1; font-family:'Segoe UI',Arial,sans-serif; padding:20px; }}
.header {{ text-align:center; margin-bottom:30px; }}
.header h1 {{ font-size:28px; color:#4fc3f7; letter-spacing:2px; }}
.header h2 {{ font-size:16px; color:#78909c; font-weight:normal; margin-top:6px; }}
.stats {{ display:flex; gap:20px; justify-content:center; margin:20px 0 30px; flex-wrap:wrap; }}
.stat {{ background:#1a2332; border:1px solid #263547; border-radius:12px; padding:16px 24px; text-align:center; min-width:140px; }}
.stat .val {{ font-size:28px; font-weight:bold; color:#4fc3f7; }}
.stat .lbl {{ font-size:11px; color:#78909c; margin-top:4px; text-transform:uppercase; letter-spacing:1px; }}
.legend {{ display:flex; gap:16px; justify-content:center; margin-bottom:20px; flex-wrap:wrap; }}
.leg {{ display:flex; align-items:center; gap:6px; font-size:12px; color:#90a4ae; }}
.dot {{ width:12px; height:12px; border-radius:50%; }}
.controls {{ margin-bottom:16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
.controls input {{ background:#1a2332; border:1px solid #37474f; color:#eceff1; padding:8px 14px; border-radius:8px; font-size:13px; width:240px; }}
.controls select {{ background:#1a2332; border:1px solid #37474f; color:#eceff1; padding:8px 14px; border-radius:8px; font-size:13px; }}
.controls label {{ color:#90a4ae; font-size:13px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#0a1628; color:#4fc3f7; padding:10px 8px; text-align:center; font-size:11px; text-transform:uppercase; letter-spacing:1px; border-bottom:2px solid #1e3a5f; position:sticky; top:0; cursor:pointer; user-select:none; white-space:nowrap; }}
th:hover {{ background:#1a2332; }}
td {{ padding:8px 8px; border-bottom:1px solid #1a2332; }}
.footer {{ text-align:center; margin-top:30px; color:#37474f; font-size:12px; }}
.run-btn {{ display:inline-block; margin-top:12px; padding:10px 28px; background:#00c853; color:#000;
  font-weight:bold; font-size:14px; border-radius:8px; text-decoration:none; letter-spacing:1px; }}
.run-btn:hover {{ background:#69f0ae; }}
</style>
</head>
<body>
<div class="header">
  <h1>&#127482;&#127480; US MARKET SCAN &mdash; $1 to $5 STOCKS</h1>
  <h2>30-Point Technical Scoring System v2 &nbsp;|&nbsp; {DATE_STR} &nbsp;|&nbsp; Powered by EODHD</h2>
  <a class="run-btn" href="https://github.com/engmostafa2982-sudo/us-stock-scan/actions/workflows/daily_scan.yml" target="_blank">&#9654; Run New Scan Now</a>
</div>
<div class="stats">
  <div class="stat"><div class="val">{len(all_results)}</div><div class="lbl">Stocks Scanned</div></div>
  <div class="stat"><div class="val">{len(scored)}</div><div class="lbl">Stocks Scored</div></div>
  <div class="stat"><div class="val">{strong_count}</div><div class="lbl">Strong Buy</div></div>
  <div class="stat"><div class="val">{ge60}</div><div class="lbl">Score &ge; 60</div></div>
  <div class="stat"><div class="val">{top_score:.0f}</div><div class="lbl">Top Score</div></div>
</div>
<div class="legend">
  <div class="leg"><div class="dot" style="background:#00c853"></div> &ge;70 Elite</div>
  <div class="leg"><div class="dot" style="background:#64dd17"></div> 60-69 Strong</div>
  <div class="leg"><div class="dot" style="background:#ffd600"></div> 50-59 Good</div>
  <div class="leg"><div class="dot" style="background:#ff6d00"></div> 40-49 Weak</div>
  <div class="leg"><div class="dot" style="background:#d50000"></div> &lt;40 Avoid</div>
</div>
<div class="controls">
  <input type="text" id="search" onkeyup="filterTable()" placeholder="Search ticker or name...">
  <label>Sector: <select id="sectorFilter" onchange="filterTable()">
    <option value="">All Sectors</option>{sector_opts}
  </select></label>
  <label>Min Score: <select id="scoreFilter" onchange="filterTable()">
    <option value="0">All</option>
    <option value="50">&ge;50</option>
    <option value="60">&ge;60</option>
    <option value="70">&ge;70</option>
  </select></label>
</div>
<table id="mainTable">
<thead>
<tr>
  <th onclick="sortTable(0)">#</th>
  <th onclick="sortTable(1)">Ticker</th>
  <th onclick="sortTable(2)">Name</th>
  <th onclick="sortTable(3)">Price</th>
  <th onclick="sortTable(4)">Score &#9660;</th>
  <th onclick="sortTable(5)">Trend</th>
  <th onclick="sortTable(6)">Momentum</th>
  <th onclick="sortTable(7)">Volume</th>
  <th onclick="sortTable(8)">Pattern</th>
  <th onclick="sortTable(9)">Signal</th>
  <th onclick="sortTable(10)">Sector</th>
  <th onclick="sortTable(11)">Mkt Cap</th>
  <th onclick="sortTable(12)">Avg Vol</th>
</tr>
</thead>
<tbody id="tableBody">
{rows_html}
</tbody>
</table>
<div class="footer">
  Generated automatically by Claude AI &nbsp;|&nbsp; EODHD Financial Data &nbsp;|&nbsp; 30-Point Scoring System v2 with MCT / CQ / MHM<br>
  All {len(scored)} scored stocks &nbsp;|&nbsp; {DATE_STR}
</div>
<script>
function filterTable() {{
  var search = document.getElementById('search').value.toLowerCase();
  var sector = document.getElementById('sectorFilter').value;
  var minScore = parseFloat(document.getElementById('scoreFilter').value) || 0;
  var rows = document.getElementById('tableBody').getElementsByTagName('tr');
  for (var i=0; i<rows.length; i++) {{
    var cells = rows[i].getElementsByTagName('td');
    var ticker = cells[1].textContent.toLowerCase();
    var name = cells[2].textContent.toLowerCase();
    var rowSector = cells[10].textContent;
    var score = parseFloat(cells[4].textContent) || 0;
    var matchSearch = !search || ticker.includes(search) || name.includes(search);
    var matchSector = !sector || rowSector.includes(sector);
    var matchScore = score >= minScore;
    rows[i].style.display = (matchSearch && matchSector && matchScore) ? '' : 'none';
  }}
}}
function sortTable(col) {{
  var table = document.getElementById('mainTable');
  var tbody = table.getElementsByTagName('tbody')[0];
  var rows = Array.from(tbody.getElementsByTagName('tr'));
  var asc = table.getAttribute('data-sort-col') == col && table.getAttribute('data-sort-dir') == 'asc';
  rows.sort(function(a, b) {{
    var av = a.getElementsByTagName('td')[col].textContent.replace(/[^\\d.\\-]/g, '');
    var bv = b.getElementsByTagName('td')[col].textContent.replace(/[^\\d.\\-]/g, '');
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(function(r) {{ tbody.appendChild(r); }});
  table.setAttribute('data-sort-col', col);
  table.setAttribute('data-sort-dir', asc ? 'desc' : 'asc');
}}
</script>
</body>
</html>"""

    html_path = os.path.join(BASE, f"US_Stock_Scan_{TODAY}.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    size_kb = os.path.getsize(html_path) // 1024
    log(f"  HTML report saved: US_Stock_Scan_{TODAY}.html ({size_kb} KB)")
    return html_path

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    log("=" * 60)
    log(f"DAILY SCAN STARTED — {DATE_STR}")
    log("=" * 60)

    t0 = time.time()

    try:
        clear_stale()
        run_all_chunks()
        html_path = build_report()

        elapsed = int(time.time() - t0)
        log(f"SCAN COMPLETE in {elapsed//60}m {elapsed%60}s")
        log(f"Report: {html_path}")
        log("=" * 60)

        # Auto-open the report (Windows only — not available on Linux/GitHub Actions)
        if html_path and os.path.exists(html_path) and sys.platform == 'win32':
            os.startfile(html_path)

    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)
