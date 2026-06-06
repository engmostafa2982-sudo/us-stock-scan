import csv, datetime, os

rows = []
with open('master_ranked.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

rows.sort(key=lambda x: float(x.get('final',0) or 0), reverse=True)
scored = [r for r in rows if float(r.get('final',0) or 0) > 0]

print(f"Total scanned : {len(rows)}")
print(f"Total scored  : {len(scored)}")
strong = [r for r in scored if 'confidence' in str(r.get('action',''))]
print(f"STRONG BUY    : {len(strong)}")
print(f"Score >= 60   : {sum(1 for r in scored if float(r.get('final',0) or 0)>=60)}")
print(f"Score >= 70   : {sum(1 for r in scored if float(r.get('final',0) or 0)>=70)}")
print()
print("=== TOP 30 RANKED ===")
print(f"{'#':<4} {'Ticker':<8} {'Name':<32} {'Price':>6}  {'Score':>5}  {'Signal':<14} {'Sector':<22}")
print("-"*100)
for i, r in enumerate(scored[:30], 1):
    code    = r.get('code','')
    name    = r.get('name','')[:31]
    price   = float(r.get('price',0) or 0)
    final   = float(r.get('final',0) or 0)
    action  = r.get('action','')
    sector  = r.get('sector','')[:21]
    signal = "STRONG BUY" if 'confidence' in action else "BUY" if 'caution' in action else action[:10]
    print(f"{i:<4} {code:<8} {name:<32} ${price:>5.2f}  {final:>5.1f}  {signal:<14} {sector:<22}")

print()
print("=== TOP 10 STRONG BUY ===")
for i, r in enumerate(strong[:10], 1):
    code  = r.get('code','')
    name  = r.get('name','')[:30]
    price = float(r.get('price',0) or 0)
    final = float(r.get('final',0) or 0)
    sector= r.get('sector','')
    trend = float(r.get('trend',0) or 0)
    mom   = float(r.get('momentum',0) or 0)
    vol   = float(r.get('volume',0) or 0)
    pat   = float(r.get('pattern',0) or 0)
    print(f"{i}. {code:<8} ${price:.2f}  Score:{final:.0f}  T:{trend:.0f} M:{mom:.0f} V:{vol:.0f} P:{pat:.0f}  {sector}  {name}")

# ── Build HTML report ──────────────────────────────────────────────────────────
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

date_str = datetime.date.today().strftime('%B %d, %Y')
date_tag = datetime.date.today().strftime('%Y%m%d')

sectors = sorted(set(r.get('sector','') for r in scored if r.get('sector') and r.get('sector') != 'nan'))
sector_opts = ''.join(f'<option value="{s}">{s}</option>' for s in sectors)

rows_html_parts = []
for i, r in enumerate(scored, 1):
    code   = r.get('code','')
    name   = r.get('name','')[:35]
    price  = float(r.get('price',0) or 0)
    final  = float(r.get('final',0) or 0)
    trend  = float(r.get('trend',0) or 0)
    mom    = float(r.get('momentum',0) or 0)
    volume = float(r.get('volume',0) or 0)
    pattern= float(r.get('pattern',0) or 0)
    action = r.get('action','')
    sector = r.get('sector','')
    mcap_raw = float(r.get('mcap',0) or 0)
    mcap   = f"${mcap_raw/1e9:.2f}B" if mcap_raw >= 1e9 else f"${mcap_raw/1e6:.0f}M" if mcap_raw >= 1e6 else "N/A"
    vol_raw = float(r.get('avgvol',0) or 0)
    avgvol = f"{vol_raw/1e6:.1f}M" if vol_raw >= 1e6 else f"{vol_raw/1e3:.0f}K" if vol_raw >= 1e3 else "N/A"

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

rows_html = '\n'.join(rows_html_parts)
strong_count = len(strong)
ge60 = sum(1 for r in scored if float(r.get('final',0) or 0)>=60)
top_score = float(scored[0].get('final',0)) if scored else 0

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>US Market Scan $1-$5 | {date_str}</title>
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
</style>
</head>
<body>
<div class="header">
  <h1>&#127482;&#127480; US MARKET SCAN &mdash; $1 to $5 STOCKS</h1>
  <h2>30-Point Technical Scoring System v2 with MCT/CQ/MHM &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; Powered by EODHD</h2>
</div>
<div class="stats">
  <div class="stat"><div class="val">{len(rows)}</div><div class="lbl">Stocks Scanned</div></div>
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
  Generated by Claude AI &nbsp;|&nbsp; EODHD Financial Data &nbsp;|&nbsp; 30-Point Scoring System v2 with MCT / CQ / MHM / Penalty Cap<br>
  All {len(scored)} scored stocks &nbsp;|&nbsp; {date_str}
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
  rows.sort(function(a,b) {{
    var av = a.getElementsByTagName('td')[col].textContent.replace(/[^\\d.\\-]/g,'');
    var bv = b.getElementsByTagName('td')[col].textContent.replace(/[^\\d.\\-]/g,'');
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an-bn : bn-an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(function(r) {{ tbody.appendChild(r); }});
  table.setAttribute('data-sort-col', col);
  table.setAttribute('data-sort-dir', asc ? 'desc' : 'asc');
}}
</script>
</body>
</html>"""

fname = f"US_Stock_Scan_{date_tag}.html"
with open(fname, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\nHTML report saved: {fname}")
print(f"File size: {os.path.getsize(fname)/1024:.0f} KB")
