"""
Markdown rendering with two extras for publishing:

1. Images: ![Caption text](/uploads/photo.png "Optional caption") render as figures.
2. Charts: a fenced block starting with ```chart renders an interactive chart plus a data table.

    ```chart
    type: bar            (bar, hbar or line)
    title: Market size by region
    unit: US$ bn
    source: Company estimates
    Region, 2025, 2026
    Americas, 410, 445
    Europe, 280, 295
    ```

The first data row is the header: the first cell labels the categories, the others name the series.
"""
import csv
import html
import io
import json
import re

import markdown
from markupsafe import Markup

CHART_TYPES = ("bar", "hbar", "line")
KEY_RE = re.compile(r"^(type|title|unit|source|decimals)\s*:\s*(.*)$", re.I)
FENCE_RE = re.compile(r"^```chart[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)
IMG_RE = re.compile(r'<p><img alt="([^"]*)" src="([^"]*)"(?: title="([^"]*)")? ?/?></p>')


def _num(s):
    s = s.strip().replace(",", "").replace("%", "").replace("$", "").replace("US", "")
    return float(s)


def parse_chart(spec):
    """Return (chart dict, None) or (None, error message)."""
    meta, rows = {}, []
    for line in spec.splitlines():
        if not line.strip():
            continue
        m = KEY_RE.match(line.strip())
        if m and not rows:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            rows.append(line)
    if len(rows) < 2:
        return None, "add a header row and at least one data row"
    table = list(csv.reader(io.StringIO("\n".join(rows)), skipinitialspace=True))
    header = [c.strip() for c in table[0]]
    if len(header) < 2:
        return None, "the header row needs a category label and at least one series name"
    cats, series = [], [{"name": n or f"Series {i + 1}", "values": []} for i, n in enumerate(header[1:])]
    for n, row in enumerate(table[1:], start=2):
        if len(row) < len(header):
            return None, f"row {n} has {len(row)} columns, expected {len(header)}"
        cats.append(row[0].strip())
        for i in range(len(series)):
            try:
                series[i]["values"].append(_num(row[i + 1]))
            except ValueError:
                return None, f'row {n}: "{row[i + 1].strip()}" is not a number'
    ctype = (meta.get("type") or "bar").lower()
    if ctype in ("column", "columns"):
        ctype = "bar"
    if ctype not in CHART_TYPES:
        return None, f"type must be one of: {', '.join(CHART_TYPES)}"
    try:
        dec = int(meta.get("decimals", ""))
    except ValueError:
        dec = None
    if dec is None:
        top = max(abs(v) for s in series for v in s["values"]) or 1
        dec = 0 if top >= 100 else 1 if top >= 10 else 2
    return {"type": ctype, "title": meta.get("title", ""), "unit": meta.get("unit", ""),
            "source": meta.get("source", ""), "decimals": dec, "label": header[0],
            "categories": cats, "series": series}, None


def _fmt(v, dec):
    return f"{v:,.{dec}f}"


def chart_html(ch):
    payload = html.escape(json.dumps({k: ch[k] for k in ("type", "unit", "decimals", "categories", "series", "title")}), quote=True)
    head = f'<figcaption class="chart-title">{html.escape(ch["title"])}</figcaption>' if ch["title"] else ""
    cols = "".join(f"<th>{html.escape(s['name'])}</th>" for s in ch["series"])
    body = ""
    for i, c in enumerate(ch["categories"]):
        tds = "".join(f"<td>{_fmt(s['values'][i], ch['decimals'])}</td>" for s in ch["series"])
        body += f"<tr><th scope=\"row\">{html.escape(c)}</th>{tds}</tr>"
    unit = f" ({html.escape(ch['unit'])})" if ch["unit"] else ""
    src = f'<div class="chart-src">Source: {html.escape(ch["source"])}</div>' if ch["source"] else ""
    return (f'<figure class="chart-fig">{head}<div class="mi-chart" data-chart="{payload}"></div>'
            f'<details class="chart-data"><summary>View data{unit}</summary><div class="table-scroll"><table class="data">'
            f'<thead><tr><th>{html.escape(ch["label"])}</th>{cols}</tr></thead><tbody>{body}</tbody></table></div></details>{src}</figure>')


def render(text):
    """Markdown to safe-ish HTML (authors are trusted admins) with chart and figure support."""
    charts = []
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")   # browsers submit CRLF line endings

    def stash(m):
        ch, err = parse_chart(m.group(1))
        if err:
            charts.append(f'<div class="chart-error">Chart could not be drawn: {html.escape(err)}.</div>')
        else:
            charts.append(chart_html(ch))
        return f"\n\n@@CHART{len(charts) - 1}@@\n\n"

    text = FENCE_RE.sub(stash, text or "")
    out = markdown.markdown(text, extensions=["extra", "sane_lists", "toc"], extension_configs={"toc": {"permalink": False}})
    for i, c in enumerate(charts):
        out = out.replace(f"<p>@@CHART{i}@@</p>", c)

    def fig(m):
        alt, src, title = m.group(1), m.group(2), m.group(3)
        cap = title or ""
        capHtml = f"<figcaption>{cap}</figcaption>" if cap else ""
        return f'<figure class="img-fig"><img alt="{alt}" src="{src}" loading="lazy">{capHtml}</figure>'

    out = IMG_RE.sub(fig, out)
    return Markup(out)


def read_minutes(text):
    text = (text or "").replace("\r\n", "\n")
    words = len(re.findall(r"\w+", re.sub(r"```chart.*?```", "", text or "", flags=re.S)))
    return max(1, round(words / 200))


CHART_SNIPPETS = {
    "bar": "```chart\ntype: bar\ntitle: Market size by region\nunit: US$ bn\nsource: Company estimates\nRegion, 2025, 2026\nAmericas, 410, 445\nEurope, 280, 295\nAsia-Pacific, 360, 405\n```\n",
    "hbar": "```chart\ntype: hbar\ntitle: Growth by sub-sector\nunit: % a year\nSub-sector, Growth\nDigital platforms, 11.2\nServices, 6.7\nCore products, 4.9\n```\n",
    "line": "```chart\ntype: line\ntitle: Market size by region, 2024 to 2028\nunit: US$ bn\nYear, Americas, Europe\n2024, 120, 80\n2025, 132, 86\n2026, 146, 91\n2027, 160, 96\n2028, 175, 101\n```\n",
}
