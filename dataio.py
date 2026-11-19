"""
Dashboard data in the database: taxonomy (countries, sub-sectors, verticals), market sizes, companies,
financials and the custom page sections. The first run fills it with the sample dataset; after that it is
edited in Admin > Dashboard data.
"""
import html
import json
import re
from urllib.parse import urlparse

from markupsafe import Markup

import config as cfg
import db
import richtext
import sample_data
import timeline

SCHEMA = """
CREATE TABLE IF NOT EXISTS dims (
    kind TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS market (
    country TEXT NOT NULL, subsector TEXT NOT NULL, vertical TEXT NOT NULL, vals TEXT NOT NULL, conf TEXT, real TEXT,
    PRIMARY KEY (country, subsector, vertical)
);
CREATE TABLE IF NOT EXISTS companies (
    slug TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS fin (
    slug TEXT NOT NULL, year INTEGER NOT NULL, revenue REAL, gross_margin REAL, ebitda REAL,
    net_income REAL, capex REAL, employees INTEGER, conf TEXT, PRIMARY KEY (slug, year)
);
CREATE TABLE IF NOT EXISTS fin_q (
    slug TEXT NOT NULL, year INTEGER NOT NULL, quarter INTEGER NOT NULL, revenue REAL, ebitda REAL,
    net_income REAL, capex REAL, conf TEXT, PRIMARY KEY (slug, year, quarter)
);
CREATE TABLE IF NOT EXISTS products (
    slug TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT '', vols TEXT NOT NULL DEFAULT '{}',
    sort INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (slug, name)
);
CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY, entity TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text',
    position TEXT NOT NULL DEFAULT 'top', sort INTEGER NOT NULL DEFAULT 0, visible INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS section_values (
    section_id TEXT NOT NULL, entity_id TEXT NOT NULL, value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (section_id, entity_id)
);
"""

ENTITIES = [("company", "Company pages"), ("country", "Country pages"), ("subsector", "Sub-sector pages"), ("vertical", "Vertical pages")]
ENTITY_LABEL = dict(ENTITIES)
KINDS = [("text", "Text", "Paragraphs. Markdown works."),
         ("list", "List", "One item per line, shown as bullets."),
         ("links", "Links", "One link per line: Label | https://example.com"),
         ("fact", "Short fact", "A single line shown in the About box, such as a website or founder.")]
DIM_KINDS = ("country", "subsector", "vertical")
OWNERSHIP = ["Public", "Private", "Private (PE-backed)", "Private (founder-owned)", "Subsidiary", "Government-owned"]
FIN_YEARS = timeline.FIN_YEARS          # years company financials can be entered for; kept in step with the timeline
_LEGACY_YEARS = list(cfg.YEARS)         # market values used to be stored as a list for these years
# Panels built into the pages that can be switched off (id, label)
BLOCKS = {
    "dashboard": [("news", "Latest news"), ("chart", "Market size chart"), ("sizing", "Market sizing table"), ("trend", "Top items over time"), ("heatmap", "Sub-sector by vertical grid")],
    "company": [("news", "Latest news"), ("charts", "Revenue and margin charts"), ("financials", "Financial summary table"),
                ("volumes", "Product volumes"), ("splits", "Revenue by country, sub-sector and vertical"), ("peers", "Peers")],
}


def slug_of(text):
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return out[:60] or "item"


def unique_id(base, taken):
    base, n, cand = slug_of(base), 2, slug_of(base)
    while cand in taken:
        cand = f"{base}-{n}"
        n += 1
    return cand


# ----------------------------------------------------------------------
# Number helpers
# ----------------------------------------------------------------------
def fill_series(raw, growth=None, n=None):
    """Turn a list of numbers and blanks (None) into a full series.
    Gaps between numbers are filled smoothly; years before or after follow `growth`
    (default: the growth between the first and last number you gave, or 3.5% if you gave one)."""
    n = n or len(raw)
    known = [i for i, v in enumerate(raw) if v is not None]
    if not known:
        return None
    out = list(raw)
    if growth is None:
        if len(known) >= 2 and raw[known[0]] > 0 and raw[known[-1]] > 0:
            growth = (raw[known[-1]] / raw[known[0]]) ** (1.0 / (known[-1] - known[0])) - 1
            growth = max(-0.2, min(0.3, growth))
        else:
            growth = 0.035
    for a, b in zip(known, known[1:]):
        va, vb = raw[a], raw[b]
        for i in range(a + 1, b):
            t = (i - a) / (b - a)
            out[i] = va * (vb / va) ** t if va > 0 and vb > 0 else va + (vb - va) * t
    for i in range(known[-1] + 1, n):
        out[i] = out[i - 1] * (1 + growth)
    for i in range(known[0] - 1, -1, -1):
        out[i] = out[i + 1] / (1 + growth)
    return out


def parse_num(text):
    """'1,234.5' -> 1234.5, '' -> None. Raises ValueError for anything else."""
    t = (text or "").strip().replace(",", "").replace("_", "")
    if t == "":
        return None
    t = t.replace("%", "").replace("$", "").replace("US", "")
    v = float(t)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(text)
    return v


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
# Confidence levels (see config.CONFIDENCE). Score 4 = reported ... 1 = low.
LEVELS = [{**lv, "score": len(cfg.CONFIDENCE) - i} for i, lv in enumerate(cfg.CONFIDENCE)]
LEVEL = {lv["id"]: lv for lv in LEVELS}
BY_SCORE = {lv["score"]: lv["id"] for lv in LEVELS}


def level_from_score(x):
    """Nearest level id for an average score (rounds half up)."""
    x = int(x + 0.5)
    return BY_SCORE[max(1, min(len(LEVELS), x))]


def parse_level(text):
    """Level id from an id, name or short name (any case). Blank gives None; unknown raises ValueError."""
    t = (text or "").strip().casefold()
    if not t:
        return None
    for lv in LEVELS:
        if t in (lv["id"].casefold(), lv["name"].casefold(), lv["short"].casefold()):
            return lv["id"]
    raise ValueError(text)


def fin_default_conf(year):
    """A financial year with no level set: reported up to the last actual year, otherwise a high-confidence estimate."""
    return "reported" if year <= cfg.LAST_ACTUAL else "high"


def init():
    with db.conn() as c:
        c.executescript(SCHEMA)
        for table in ("market", "fin"):   # databases made before confidence levels existed
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
            if "conf" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN conf TEXT")
        if "real" not in [r["name"] for r in c.execute("PRAGMA table_info(market)")]:     # real (constant-price) sizes
            c.execute("ALTER TABLE market ADD COLUMN real TEXT")
        for r in c.execute("SELECT country, subsector, vertical, vals FROM market WHERE vals LIKE '[%'").fetchall():
            c.execute("UPDATE market SET vals=? WHERE country=? AND subsector=? AND vertical=?",
                      (json.dumps(_vals_dict(r["vals"])), r["country"], r["subsector"], r["vertical"]))


def _vals_dict(text):
    """Stored market values as {"year": value}. Older databases hold a plain list for the original years."""
    j = json.loads(text)
    if isinstance(j, list):
        return {str(y): v for y, v in zip(_LEGACY_YEARS, j)}
    return {str(k): v for k, v in j.items()}


def _window(stored):
    """Market series for the years on the timeline. Years you have not entered are filled in: gaps are smoothed and
    years beyond your numbers follow their growth, so moving the timeline forward gives a sensible first estimate."""
    raw = [stored.get(str(y)) for y in cfg.YEARS]
    return fill_series(raw, None, len(raw)) if any(v is not None for v in raw) else None


def load_dims():
    out = {k: [] for k in DIM_KINDS}
    with db.conn() as c:
        for r in c.execute("SELECT * FROM dims ORDER BY kind, sort, name").fetchall():
            if r["kind"] in out:
                out[r["kind"]].append({**json.loads(r["data"] or "{}"), "id": r["id"], "name": r["name"], "sort": r["sort"]})
    return out


def load_market():
    with db.conn() as c:
        out = {}
        for r in c.execute("SELECT * FROM market"):
            series = _window(_vals_dict(r["vals"]))
            if series is not None:
                out[(r["country"], r["subsector"], r["vertical"])] = series
        return out


def load_market_real():
    """Real (constant-price) market sizes, only for the cells that have them."""
    with db.conn() as c:
        out = {}
        for r in c.execute("SELECT country, subsector, vertical, real FROM market WHERE real IS NOT NULL"):
            series = _window(_vals_dict(r["real"]))
            if series is not None:
                out[(r["country"], r["subsector"], r["vertical"])] = series
        return out


def load_market_conf():
    with db.conn() as c:
        return {(r["country"], r["subsector"], r["vertical"]): r["conf"] for r in c.execute("SELECT country, subsector, vertical, conf FROM market")
                if r["conf"] in LEVEL}


def load_companies():
    with db.conn() as c:
        return {r["slug"]: {**json.loads(r["data"] or "{}"), "slug": r["slug"], "name": r["name"]} for r in c.execute("SELECT * FROM companies ORDER BY name")}


UNITS = ["units", "thousand units", "million units", "tonnes", "kilotonnes", "MWh", "GWh", "barrels", "litres", "kg",
         "subscribers", "users", "transactions", "vehicles", "square metres", "shipments"]      # suggestions; any text can be typed


def load_products():
    """{slug: [{name, unit, vols: {year: volume}}]} in the order they were entered."""
    out = {}
    with db.conn() as c:
        for r in c.execute("SELECT * FROM products ORDER BY slug, sort, name"):
            out.setdefault(r["slug"], []).append({"name": r["name"], "unit": r["unit"], "vols": {int(k): v for k, v in json.loads(r["vols"] or "{}").items()}})
    return out


def known_units():
    """Units already used, then the suggestions."""
    with db.conn() as c:
        used = [r["unit"] for r in c.execute("SELECT unit, COUNT(*) n FROM products WHERE unit != '' GROUP BY unit ORDER BY n DESC")]
    return used + [u for u in UNITS if u not in used]


def save_products(slug, items, window=None):
    """Replace a company's products. items: [{name, unit, vols: {year: volume}}]. Volumes for years outside `window`
    (the years the form shows) are kept for a product of the same name."""
    with db.conn() as c:
        old = {r["name"].lower(): json.loads(r["vols"] or "{}") for r in c.execute("SELECT name, vols FROM products WHERE slug=?", (slug,))}
        c.execute("DELETE FROM products WHERE slug=?", (slug,))
        for i, it in enumerate(items):
            vols = {str(y): v for y, v in it["vols"].items()}
            if window is not None:
                vols.update({k: v for k, v in old.get(it["name"].lower(), {}).items() if int(k) not in window})
            c.execute("INSERT INTO products (slug, name, unit, vols, sort) VALUES (?,?,?,?,?)", (slug, it["name"], it["unit"], json.dumps(vols), i))
        db.bump(c)


def load_fin():
    out = {}
    with db.conn() as c:
        for r in c.execute("SELECT * FROM fin ORDER BY slug, year"):
            out.setdefault(r["slug"], []).append(dict(r))
    return out


def load_fin_q():
    out = {}
    with db.conn() as c:
        for r in c.execute("SELECT * FROM fin_q ORDER BY slug, year, quarter"):
            out.setdefault(r["slug"], []).append(dict(r))
    return out


def save_fin_q(slug, rows, replace=True, clear=None):
    """rows: dicts with year, quarter, revenue and optional ebitda, net_income, capex, conf (a row without 'conf'
    keeps the level it had). clear: (year, quarter) pairs to delete first; see save_fin."""
    with db.conn() as c:
        if clear is not None:
            c.executemany("DELETE FROM fin_q WHERE slug=? AND year=? AND quarter=?", [(slug, y, q) for y, q in clear])
        elif replace:
            c.execute("DELETE FROM fin_q WHERE slug=?", (slug,))
        for r in rows:
            base = (slug, r["year"], r["quarter"], r.get("revenue"), r.get("ebitda"), r.get("net_income"), r.get("capex"))
            keep = ("ON CONFLICT(slug, year, quarter) DO UPDATE SET revenue=excluded.revenue, ebitda=excluded.ebitda, "
                    "net_income=excluded.net_income, capex=excluded.capex")
            if "conf" in r:
                c.execute("INSERT INTO fin_q (slug, year, quarter, revenue, ebitda, net_income, capex, conf) VALUES (?,?,?,?,?,?,?,?) "
                          + keep + ", conf=excluded.conf", base + (r["conf"],))
            else:
                c.execute("INSERT INTO fin_q (slug, year, quarter, revenue, ebitda, net_income, capex) VALUES (?,?,?,?,?,?,?) " + keep, base)
        db.bump(c)


def load_sections():
    with db.conn() as c:
        secs = [dict(r) for r in c.execute("SELECT * FROM sections ORDER BY entity, sort, title")]
        vals = {}
        for r in c.execute("SELECT * FROM section_values"):
            vals.setdefault(r["entity_id"], {})[r["section_id"]] = r["value"]
    return secs, vals


def hidden_blocks():
    try:
        return set(json.loads(db.get_meta("hidden_blocks", "[]")))
    except ValueError:
        return set()


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def save_dims(kind, rows):
    """rows: list of dicts with id, name, sort and other fields. Replaces the whole list for this kind."""
    with db.conn() as c:
        c.execute("DELETE FROM dims WHERE kind=?", (kind,))
        for i, r in enumerate(rows):
            extra = {k: v for k, v in r.items() if k not in ("id", "name", "sort")}
            c.execute("INSERT INTO dims (kind, id, name, sort, data) VALUES (?,?,?,?,?)",
                      (kind, r["id"], r["name"], r.get("sort", i), json.dumps(extra)))
        db.bump(c)


def delete_dim(kind, dim_id):
    """Remove a country/sub-sector/vertical and everything that depends on it."""
    col = kind
    with db.conn() as c:
        c.execute("DELETE FROM dims WHERE kind=? AND id=?", (kind, dim_id))
        c.execute(f"DELETE FROM market WHERE {col}=?", (dim_id,))
        c.execute("DELETE FROM section_values WHERE entity_id=? AND section_id IN (SELECT id FROM sections WHERE entity=?)", (dim_id, kind))
        for r in c.execute("SELECT slug, data FROM companies").fetchall():
            d = json.loads(r["data"] or "{}")
            changed = False
            if kind == "country" and d.get("hq") == dim_id:
                d["hq"] = ""
                changed = True
            al = d.get("alloc", {}).get(kind, {})
            if dim_id in al:
                al.pop(dim_id)
                changed = True
            if changed:
                c.execute("UPDATE companies SET data=? WHERE slug=?", (json.dumps(d), r["slug"]))
        db.bump(c)
    scrub_news(kind, dim_id)


def save_market(cells, conf=None, real=None):
    """cells: {(c, s, v): [vals]} to upsert; a value of None deletes the cell.
    conf: {(c, s, v): level id or None}. A cell missing from conf keeps the level it had.
    real: {(c, s, v): [vals] or None} the optional real (constant-price) series of cells that already have a nominal size."""
    conf = conf or {}
    with db.conn() as c:
        for (co, su, ve), vals in cells.items():
            if vals is None:
                c.execute("DELETE FROM market WHERE country=? AND subsector=? AND vertical=?", (co, su, ve))
                continue
            row = c.execute("SELECT vals FROM market WHERE country=? AND subsector=? AND vertical=?", (co, su, ve)).fetchone()
            stored = _vals_dict(row["vals"]) if row else {}       # years outside the timeline are kept
            stored.update({str(y): round(x, 6) for y, x in zip(cfg.YEARS, vals)})
            v = json.dumps(stored)
            if (co, su, ve) in conf:
                c.execute("INSERT INTO market (country, subsector, vertical, vals, conf) VALUES (?,?,?,?,?) "
                          "ON CONFLICT(country, subsector, vertical) DO UPDATE SET vals=excluded.vals, conf=excluded.conf",
                          (co, su, ve, v, conf[(co, su, ve)]))
            else:
                c.execute("INSERT INTO market (country, subsector, vertical, vals) VALUES (?,?,?,?) "
                          "ON CONFLICT(country, subsector, vertical) DO UPDATE SET vals=excluded.vals", (co, su, ve, v))
        for (co, su, ve), vals in (real or {}).items():
            row = c.execute("SELECT real FROM market WHERE country=? AND subsector=? AND vertical=?", (co, su, ve)).fetchone()
            if row is None:
                continue
            if vals is None:
                c.execute("UPDATE market SET real=NULL WHERE country=? AND subsector=? AND vertical=?", (co, su, ve))
                continue
            stored = _vals_dict(row["real"]) if row["real"] else {}
            stored.update({str(y): round(x, 6) for y, x in zip(cfg.YEARS, vals)})
            c.execute("UPDATE market SET real=? WHERE country=? AND subsector=? AND vertical=?", (json.dumps(stored), co, su, ve))
        db.bump(c)


def clear_market(keep_countries=None):
    with db.conn() as c:
        c.execute("DELETE FROM market")
        db.bump(c)


def save_company(slug, name, data):
    with db.conn() as c:
        c.execute("INSERT INTO companies (slug, name, data) VALUES (?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name, data=excluded.data",
                  (slug, name, json.dumps(data)))
        db.bump(c)


def save_fin(slug, rows, replace=True, clear=None):
    """rows: list of dicts with year and optional revenue, gross_margin, ebitda, net_income, capex, employees, conf.
    A row without a 'conf' key keeps the level it had. clear: years to delete first (the years a form covers), which
    leaves rows for other years alone; without it, replace=True deletes them all."""
    with db.conn() as c:
        if clear is not None:
            c.executemany("DELETE FROM fin WHERE slug=? AND year=?", [(slug, y) for y in clear])
        elif replace:
            c.execute("DELETE FROM fin WHERE slug=?", (slug,))
        for r in rows:
            base = (slug, r["year"], r.get("revenue"), r.get("gross_margin"), r.get("ebitda"), r.get("net_income"), r.get("capex"), r.get("employees"))
            keep = ("ON CONFLICT(slug, year) DO UPDATE SET revenue=excluded.revenue, gross_margin=excluded.gross_margin, "
                    "ebitda=excluded.ebitda, net_income=excluded.net_income, capex=excluded.capex, employees=excluded.employees")
            if "conf" in r:
                c.execute("INSERT INTO fin (slug, year, revenue, gross_margin, ebitda, net_income, capex, employees, conf) VALUES (?,?,?,?,?,?,?,?,?) "
                          + keep + ", conf=excluded.conf", base + (r["conf"],))
            else:
                c.execute("INSERT INTO fin (slug, year, revenue, gross_margin, ebitda, net_income, capex, employees) VALUES (?,?,?,?,?,?,?,?) " + keep, base)
        db.bump(c)


def delete_company(slug):
    with db.conn() as c:
        c.execute("DELETE FROM companies WHERE slug=?", (slug,))
        c.execute("DELETE FROM fin WHERE slug=?", (slug,))
        c.execute("DELETE FROM fin_q WHERE slug=?", (slug,))
        c.execute("DELETE FROM products WHERE slug=?", (slug,))
        c.execute("DELETE FROM section_values WHERE entity_id=? AND section_id IN (SELECT id FROM sections WHERE entity='company')", (slug,))
        db.bump(c)
    scrub_news("company", slug)


def save_values(entity_kind, entity_id, values):
    """values: {section_id: text}. Empty text removes the value."""
    with db.conn() as c:
        for sid, val in values.items():
            if (val or "").strip():
                c.execute("INSERT INTO section_values (section_id, entity_id, value) VALUES (?,?,?) "
                          "ON CONFLICT(section_id, entity_id) DO UPDATE SET value=excluded.value", (sid, entity_id, val.strip()))
            else:
                c.execute("DELETE FROM section_values WHERE section_id=? AND entity_id=?", (sid, entity_id))
        db.bump(c)


def scrub_news(field, ref):
    """Clear a deleted company/country/sub-sector/vertical from the tags of published news."""
    for p in db.list_posts("news", published_only=False, with_body=True):
        if p["meta"].get(field) == ref:
            m = dict(p["meta"])
            m[field] = ""
            p["meta"] = m
            db.save("news", p, p["id"])


def scrub_all_company_news():
    for p in db.list_posts("news", published_only=False, with_body=True):
        if p["meta"].get("company"):
            m = dict(p["meta"])
            m["company"] = ""
            p["meta"] = m
            db.save("news", p, p["id"])


# ----------------------------------------------------------------------
# Section values -> HTML
# ----------------------------------------------------------------------
URL_OK = re.compile(r"^(https?://|mailto:)[^\s<>\"']+$", re.I)


def _link(label, url):
    url = url.strip()
    if URL_OK.match(url):
        return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener nofollow">{html.escape(label.strip() or url)}</a>'
    return html.escape(label.strip() or url)


def render_value(kind, raw):
    raw = (raw or "").strip()
    if not raw:
        return Markup("")
    if kind == "text":
        return richtext.render(raw)
    lines = [ln.strip() for ln in raw.replace("\r", "").split("\n") if ln.strip()]
    if kind == "list":
        return Markup("<ul class=\"plain-list\">" + "".join(f"<li>{html.escape(ln.lstrip('-*• ').strip())}</li>" for ln in lines) + "</ul>")
    if kind == "links":
        items = []
        for ln in lines:
            label, _, url = ln.partition("|")
            if not url:
                label, url = "", label
            if "|" not in ln and not URL_OK.match(url.strip()):
                items.append(html.escape(ln))
            else:
                items.append(_link(label, url))
        return Markup("<ul class=\"plain-list\">" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
    # fact: one line, linked when it is a URL
    line = lines[0]
    return Markup(_link(re.sub(r"^https?://(www\.)?", "", line).rstrip("/"), line) if URL_OK.match(line) else html.escape(line))


# ----------------------------------------------------------------------
# Seeding with the sample dataset
# ----------------------------------------------------------------------
FLAG_FIX = {"uk": "gb"}
DEFAULT_SECTIONS = [
    ("products", "company", "Products and services", "list", "top", 1),
    ("country-overview", "country", "Overview", "text", "top", 0),
    ("subsector-overview", "subsector", "Overview", "text", "top", 0),
    ("vertical-overview", "vertical", "Overview", "text", "top", 0),
]


def clean_website(text):
    """A company website as a full http(s) address. 'example.com' becomes 'https://example.com'. Blank gives ''.
    Anything that is not a plain web address (other schemes, spaces, no dot in the host) raises ValueError."""
    t = (text or "").strip()
    if not t:
        return ""
    if not re.match(r"^https?://", t, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*://", t, re.I) or re.match(r"^(javascript|data|vbscript|mailto|file|tel):", t, re.I):
            raise ValueError(text)          # other schemes: ftp://, javascript:, mailto: and the like
        t = "https://" + t.lstrip("/")
    p = urlparse(t)
    try:
        p.port
    except ValueError:
        raise ValueError(text)
    if len(t) > 300 or re.search(r"[\s<>\"']", t) or not p.hostname or "." not in p.hostname:
        raise ValueError(text)
    return t


def website_label(url):
    """The address as shown to readers: no scheme, no www, no trailing slash."""
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")


def write_default_sections():
    with db.conn() as c:
        for sid, ent, title, kind, pos, sort in DEFAULT_SECTIONS:
            c.execute("INSERT OR IGNORE INTO sections (id, entity, title, kind, position, sort, visible) VALUES (?,?,?,?,?,?,1)",
                      (sid, ent, title, kind, pos, sort))


def wipe_all():
    with db.conn() as c:
        for t in ("dims", "market", "companies", "fin", "fin_q", "products", "sections", "section_values"):
            c.execute(f"DELETE FROM {t}")


def clear_figures():
    """Delete market sizes, companies and financials. Lists and sections are kept."""
    with db.conn() as c:
        for t in ("market", "companies", "fin", "fin_q", "products", "section_values"):
            c.execute(f"DELETE FROM {t}")
        db.bump(c)
    scrub_all_company_news()
    db.set_meta("sample_notice", "0")


def seed_sample():
    """Write the generated sample dataset (taxonomy, market, companies, financials) to the database."""
    st = sample_data.get()
    timeline.reset()           # the sample is built for the default timeline
    timeline.apply()
    wipe_all()
    with db.conn() as c:
        for i, ct in enumerate(sample_data.COUNTRIES):
            extra = {k: ct[k] for k in ("region", "city", "exchange", "lat", "lon")}
            extra["flag"] = FLAG_FIX.get(ct["id"], ct["id"])
            c.execute("INSERT INTO dims VALUES ('country',?,?,?,?)", (ct["id"], ct["name"], i, json.dumps(extra)))
        for i, s in enumerate(sample_data.SUBSECTORS):
            c.execute("INSERT INTO dims VALUES ('subsector',?,?,?,?)", (s["id"], s["name"], i, json.dumps({"phrase": s["phrase"]})))
        for i, v in enumerate(sample_data.VERTICALS):
            c.execute("INSERT INTO dims VALUES ('vertical',?,?,?,?)", (v["id"], v["name"], i, "{}"))
        for (co, su, ve), vals in st.market.items():
            h = sum(ord(ch) for ch in co + su + ve) % 8          # a spread of levels so the sample shows the feature
            lvl = "high" if h < 2 else ("low" if h == 7 else "medium")
            base_y = timeline.price_base()
            infl = 0.015 + (sum(ord(ch) for ch in co) % 30) / 1000.0      # 1.5% to 4.4% a year, so the sample has a price index
            real = {str(y): round(x / (1 + infl) ** (y - base_y), 4) for y, x in zip(sample_data.YEARS, vals)}
            c.execute("INSERT INTO market (country, subsector, vertical, vals, conf, real) VALUES (?,?,?,?,?,?)",
                      (co, su, ve, json.dumps({str(y): round(x, 4) for y, x in zip(sample_data.YEARS, vals)}), lvl, json.dumps(real)))
        for slug, co in st.companies.items():
            alloc = {"country": {}, "subsector": {}, "vertical": {}}
            idx = {"country": 0, "subsector": 1, "vertical": 2}
            tot = 0.0
            for k, vals in st.company_cells[slug].items():
                w = sum(vals)
                tot += w
                for dim, i in idx.items():
                    alloc[dim][k[i]] = alloc[dim].get(k[i], 0) + w
            for dim in alloc:
                alloc[dim] = {k: round(100 * v / tot, 2) for k, v in alloc[dim].items()}
            data = {"hq": co["hq"], "city": co["city"], "ownership": co["ownership"], "ticker": co["ticker"] or "",
                    "exchange": co["exchange"] or "", "founded": co["founded"], "market_cap": round(co["market_cap"], 1) if co.get("market_cap") else None,
                    "description": "", "alloc": alloc}
            c.execute("INSERT INTO companies VALUES (?,?,?)", (slug, co["name"], json.dumps(data)))
            for r in st.fin[slug]:
                h = sum(ord(ch) for ch in slug) % 5      # a spread of levels for the sample's current-year estimates
                lvl = (None if r["year"] <= sample_data.LAST_ACTUAL else ("medium" if h in (1, 2) else "low" if h == 3 else None))
                c.execute("INSERT INTO fin (slug, year, revenue, gross_margin, ebitda, net_income, capex, employees, conf) VALUES (?,?,?,?,?,?,?,?,?)",
                          (slug, r["year"], round(r["revenue"], 1), round(r["gross_margin"], 4), round(r["ebitda"], 1),
                           round(r["net_income"], 1), round(r["capex"], 1), r["employees"], lvl))
        sample_units = [("Core units", "thousand units"), ("Service contracts", "contracts"), ("Output", "tonnes"), ("Energy sold", "GWh"), ("Shipments", "shipments")]
        for slug in st.companies:
            h = sum(ord(ch) for ch in slug)
            if h % 5 == 4:
                continue                                       # some companies have no volumes
            for k in range(2 if h % 4 == 0 else 1):
                name, unit = sample_units[(h + k * 2) % len(sample_units)]
                per = 0.4 + (h % 7) * 0.15 + k * 0.5            # revenue per unit, so volumes move with revenue
                vols = {str(r["year"]): round(r["revenue"] / per * (1 + 0.01 * k) * (0.97 + 0.0006 * (h * (r["year"] - 2000) % 100)), 1) for r in st.fin[slug] if r["year"] <= sample_data.LAST_ACTUAL + 1}
                c.execute("INSERT INTO products (slug, name, unit, vols, sort) VALUES (?,?,?,?,?)", (slug, name, unit, json.dumps(vols), k))
    write_default_sections()
    db.set_meta("data_seeded", "1")
    db.set_meta("sample_notice", "1")
    db.bump()


def ensure_seeded():
    init()
    if db.get_meta("data_seeded") != "1":
        seed_sample()
