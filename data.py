"""
Data layer: the dashboard's in-memory view of the database (taxonomy, market sizes, companies, financials,
custom page sections) plus the query helpers the pages use.

`reload()` rebuilds everything from the database. It updates the module-level dicts and lists in place,
so every other module that holds a reference sees the new data. Edit the data in Admin > Dashboard data.

    STORE.market[(country, subsector, vertical)] -> market size per year in YEARS (US$ bn)
    STORE.companies[slug]                        -> company profile dict
    STORE.company_cells[slug][(c, s, v)]         -> company revenue per year in that market cell (US$ m)
    STORE.fin[slug]                              -> list of financial dicts, one per reported year
"""
import config as cfg
import dataio

YEARS = cfg.YEARS
NY = len(YEARS)
IDX2026 = YEARS.index(cfg.ESTIMATE_YEAR)
IDX2025 = IDX2026 - 1

COUNTRY, SUB, VERT = {}, {}, {}
DIM_LOOKUP = {"country": COUNTRY, "subsector": SUB, "vertical": VERT}
DIM_ORDER = ["country", "subsector", "vertical", "company"]
_LISTS = {"country": cfg.COUNTRIES, "subsector": cfg.SUBSECTORS, "vertical": cfg.VERTICALS}


def year_status(y):
    if y <= cfg.LAST_ACTUAL:
        return "A"
    if y == cfg.ESTIMATE_YEAR:
        return "E"
    return "F"


def cagr(a, b, n):
    if a is None or b is None or a <= 0 or b <= 0 or n <= 0:
        return None
    return (b / a) ** (1.0 / n) - 1


def slugify(s):
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


class Store:
    def __init__(self):
        self.market, self.companies, self.company_cells, self.fin, self.market_conf = {}, {}, {}, {}, {}


STORE = Store()
SECTIONS = {"defs": [], "values": {}}
LOADED_VERSION = None


# ----------------------------------------------------------------------
# Loading from the database
# ----------------------------------------------------------------------
def _revenue_series(known, cells, market):
    """Company revenue per year (US$ m). Years you reported are used as given, gaps are interpolated, and years
    outside your data follow the growth of the markets the company sells into."""
    idxs = sorted(known)
    if not idxs:
        return None
    r = [None] * NY
    for i in idxs:
        r[i] = known[i]
    for a, b in zip(idxs, idxs[1:]):
        va, vb = known[a], known[b]
        for i in range(a + 1, b):
            t = (i - a) / (b - a)
            r[i] = va * (vb / va) ** t if va > 0 and vb > 0 else va + (vb - va) * t
    index = [sum(sh * market[k][i] for k, sh in cells.items() if k in market) for i in range(NY)]
    for i in range(idxs[-1] + 1, NY):
        r[i] = r[i - 1] * (index[i] / index[i - 1] if index[i - 1] > 0 else 1.0)
    for i in range(idxs[0] - 1, -1, -1):
        r[i] = r[i + 1] * (index[i] / index[i + 1] if index[i + 1] > 0 else 1.0)
    return r


def normalise_alloc(raw):
    """{id: pct} -> {id: fraction} that sums to 1, or {} when empty."""
    clean = {k: float(v) for k, v in (raw or {}).items() if v and float(v) > 0}
    tot = sum(clean.values())
    return {k: v / tot for k, v in clean.items()} if tot > 0 else {}


def reload():
    global LOADED_VERSION
    ver = dataio.db.version()
    dims = dataio.load_dims()
    for kind, lookup in DIM_LOOKUP.items():
        lookup.clear()
        for r in dims[kind]:
            lookup[r["id"]] = r
        _LISTS[kind][:] = dims[kind]
    market = {k: v for k, v in dataio.load_market().items()
              if k[0] in COUNTRY and k[1] in SUB and k[2] in VERT and len(v) == NY}
    mconf = {k: v for k, v in dataio.load_market_conf().items() if k in market}
    profiles, fins = dataio.load_companies(), dataio.load_fin()

    companies, fin, cells_all = {}, {}, {}
    for slug, p in profiles.items():
        alloc = {dim: normalise_alloc(p.get("alloc", {}).get(dim)) for dim in ("country", "subsector", "vertical")}
        alloc = {dim: {k: v for k, v in a.items() if k in DIM_LOOKUP[dim]} for dim, a in alloc.items()}
        rows = []
        for r in fins.get(slug, []):
            if r["year"] not in YEARS or r["revenue"] is None:
                continue
            prev = rows[-1] if rows and rows[-1]["year"] == r["year"] - 1 else None
            rev = r["revenue"]
            rows.append({"year": r["year"], "status": year_status(r["year"]), "revenue": rev,
                         "growth": (rev / prev["revenue"] - 1) if prev and prev["revenue"] else None,
                         "gross_margin": r["gross_margin"], "ebitda": r["ebitda"],
                         "ebitda_margin": (r["ebitda"] / rev) if r["ebitda"] is not None and rev else None,
                         "net_income": r["net_income"], "capex": r["capex"], "employees": r["employees"],
                         "conf_raw": r.get("conf") if r.get("conf") in dataio.LEVEL else None,
                         "conf": r.get("conf") if r.get("conf") in dataio.LEVEL else dataio.fin_default_conf(r["year"])})
        order = lambda a: sorted(a, key=lambda k: -a[k])
        subs, verts, pres = order(alloc["subsector"]), order(alloc["vertical"]), order(alloc["country"])
        hq = p.get("hq") if p.get("hq") in COUNTRY else (pres[0] if pres else "")
        cells = {}
        for c in alloc["country"]:
            for s in alloc["subsector"]:
                for v in alloc["vertical"]:
                    cells[(c, s, v)] = alloc["country"][c] * alloc["subsector"][s] * alloc["vertical"][v]
        series = _revenue_series({YEARS.index(r["year"]): r["revenue"] for r in rows}, cells, market)
        cells_all[slug] = {k: [series[i] * sh for i in range(NY)] for k, sh in cells.items()} if series else {}
        companies[slug] = {
            "slug": slug, "name": p["name"], "hq": hq, "city": p.get("city") or (COUNTRY[hq].get("city", "") if hq else ""),
            "ownership": p.get("ownership") or "Private", "ticker": p.get("ticker") or None,
            "exchange": p.get("exchange") or None, "founded": p.get("founded"), "market_cap": p.get("market_cap"),
            "description": p.get("description") or "", "alloc": p.get("alloc", {}),
            "primary": subs[0] if subs else None, "subsectors": subs, "verticals": verts, "presence": pres,
            "has_split": bool(cells),
        }
        fin[slug] = rows

    for store_dict, new in ((STORE.market, market), (STORE.market_conf, mconf), (STORE.companies, companies), (STORE.company_cells, cells_all), (STORE.fin, fin)):
        store_dict.clear()
        store_dict.update(new)
    defs, vals = dataio.load_sections()
    SECTIONS["defs"], SECTIONS["values"] = defs, vals
    LOADED_VERSION = ver


def last_fin(slug):
    """Latest financial row, or an empty row when the company has none yet."""
    rows = STORE.fin.get(slug) or []
    if rows:
        return rows[-1]
    return {"year": cfg.ESTIMATE_YEAR, "status": "E", "revenue": None, "growth": None, "gross_margin": None, "ebitda": None,
            "ebitda_margin": None, "net_income": None, "capex": None, "employees": None, "conf": None, "conf_raw": None}


def prev_fin(slug):
    rows = STORE.fin.get(slug) or []
    return rows[-2] if len(rows) > 1 else {"year": cfg.ESTIMATE_YEAR - 1}


# ----------------------------------------------------------------------
# Custom page sections
# ----------------------------------------------------------------------
def section_blocks(entity, entity_id):
    """Custom sections with a value for this entity: {'facts': [...], 'top': [...], 'bottom': [...]}."""
    out = {"facts": [], "top": [], "bottom": []}
    vals = SECTIONS["values"].get(entity_id, {})
    for s in SECTIONS["defs"]:
        if s["entity"] != entity or not s["visible"]:
            continue
        raw = vals.get(s["id"], "")
        if not raw.strip():
            continue
        item = {"id": s["id"], "title": s["title"], "kind": s["kind"], "html": dataio.render_value(s["kind"], raw)}
        out["facts" if s["kind"] == "fact" else ("bottom" if s["position"] == "bottom" else "top")].append(item)
    return out


# Published news lives in the database; this in-memory list is what the dashboard and feeds query.
NEWS = []


def set_news(items):
    """Replace the news cache. Items: dicts with id, slug, date, headline, summary, type, company, country,
    subsector, vertical, impact, source, cover. Newest first."""
    global NEWS
    NEWS = sorted(items, key=lambda n: (str(n["date"]), n["id"]), reverse=True)


# ----------------------------------------------------------------------
# Query helpers
# ----------------------------------------------------------------------
def _match(key, f):
    c, s, v = key
    return ((not f.get("country") or f["country"] == c) and
            (not f.get("subsector") or f["subsector"] == s) and
            (not f.get("vertical") or f["vertical"] == v))


def market_series(f):
    tot = [0.0] * NY
    for k, vals in STORE.market.items():
        if _match(k, f):
            for i, x in enumerate(vals):
                tot[i] += x
    return tot


def market_conf(key):
    return STORE.market_conf.get(key) or cfg.CONFIDENCE_DEFAULT_MARKET


def market_confidence(f):
    """Confidence level id for a slice of the market: the average of its cells' levels, weighted by size."""
    num = den = 0.0
    for k, vals in STORE.market.items():
        if _match(k, f) and vals[IDX2026] > 0:
            num += dataio.LEVEL[market_conf(k)]["score"] * vals[IDX2026]
            den += vals[IDX2026]
    return dataio.level_from_score(num / den) if den else None


def company_confidence(slug):
    """Confidence in a company's current-year revenue: the level of that year's financials. With no entry for the
    year the figure is extrapolated from the market, so it is low."""
    for r in STORE.fin.get(slug, []):
        if r["year"] == cfg.ESTIMATE_YEAR:
            return r["conf"]
    return dataio.LEVELS[-1]["id"] if STORE.fin.get(slug) else None


def company_series(slug, f):
    tot = [0.0] * NY
    for k, vals in STORE.company_cells.get(slug, {}).items():
        if _match(k, f):
            for i, x in enumerate(vals):
                tot[i] += x
    return tot


def series_rows(vals, scale=1.0):
    return [{"year": y, "value": v * scale, "status": year_status(y)} for y, v in zip(YEARS, vals)]


def summarize(vals):
    return {
        "size": vals[IDX2026],
        "prev": vals[IDX2025],
        "yoy": cagr(vals[IDX2025], vals[IDX2026], 1),
        "cagr_hist": cagr(vals[0], vals[IDX2026], IDX2026),
        "cagr_fc": cagr(vals[IDX2026], vals[-1], NY - 1 - IDX2026),
        "series": vals,
    }


def breakdown(dim, f):
    """Rows for a breakdown dimension within filter f. Companies return revenue rows."""
    total = market_series(f)
    total_size = total[IDX2026] or 1
    rows = []
    if dim in ("country", "subsector", "vertical"):
        for mid, meta in DIM_LOOKUP[dim].items():
            g = dict(f)
            if g.get(dim) and g[dim] != mid:
                continue
            g[dim] = mid
            vals = market_series(g)
            if vals[IDX2026] <= 0:
                continue
            r = summarize(vals)
            r.update({"id": mid, "name": meta["name"], "share": r["size"] / total_size,
                      "region": meta.get("region"), "conf": market_confidence(g)})
            rows.append(r)
    else:
        for slug, co in STORE.companies.items():
            vals = company_series(slug, f)
            if vals[IDX2026] <= 0.001:
                continue
            r = summarize(vals)
            fin = last_fin(slug)
            r.update({"id": slug, "name": co["name"], "share": r["size"] / (total_size * 1000.0),
                      "ebitda_margin": fin["ebitda_margin"], "hq": COUNTRY[co["hq"]]["name"] if co["hq"] in COUNTRY else "",
                      "ownership": co["ownership"], "conf": company_confidence(slug)})
            rows.append(r)
    rows.sort(key=lambda r: r["size"], reverse=True)
    return rows, total


def heatmap(f):
    g = {"country": f.get("country")}
    grid, mx = [], 0
    for s in cfg.SUBSECTORS:
        row = []
        for v in cfg.VERTICALS:
            val = market_series({**g, "subsector": s["id"], "vertical": v["id"]})[IDX2026]
            mx = max(mx, val)
            row.append({"sub": s["id"], "vert": v["id"], "value": val})
        grid.append({"sub": s, "cells": row})
    for r in grid:
        for c in r["cells"]:
            c["intensity"] = c["value"] / mx if mx else 0
            c["active"] = (f.get("subsector") in (None, c["sub"]) and f.get("vertical") in (None, c["vert"])
                           and (f.get("subsector") or f.get("vertical")) is not None)
    return grid


def filter_news(f=None, company=None, ntype=None, q=None):
    f = f or {}
    out = []
    ql = q.lower().strip() if q else None
    for n in NEWS:
        # strict: when a filter is set, news must carry that exact value (market items may be unscoped on sub/vertical)
        ok = True
        if company and n["company"] != company:
            ok = False
        for dim in ("country", "subsector", "vertical"):
            if f.get(dim) and n[dim] != f[dim]:
                ok = False
        if ntype and n["type"] != ntype:
            ok = False
        if ql and ql not in (n["headline"] + " " + n["summary"]).lower():
            ok = False
        if ok:
            out.append(n)
    return out


def news_for_slice(f, limit=8):
    """News for a dashboard slice. If a narrow slice has few items, widen (vertical -> sub-sector -> country)."""
    picked, seen = [], set()
    levels = [dict(f)]
    g = dict(f)
    for drop in ("vertical", "subsector", "country"):
        if g.get(drop):
            g = {k: v for k, v in g.items() if k != drop}
            levels.append(dict(g))
    for i, lv in enumerate(levels):
        for n in filter_news(lv):
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            picked.append({**n, "broader": i > 0})
            if len(picked) >= limit:
                return picked
        if len(picked) >= limit:
            break
    return picked


def company_news(slug, limit=6):
    return [n for n in NEWS if n["company"] == slug][:limit]


def company_breakdowns(slug):
    cells = STORE.company_cells.get(slug, {})
    result = {}
    for dim, idx, lookup in (("country", 0, COUNTRY), ("subsector", 1, SUB), ("vertical", 2, VERT)):
        agg = {}
        for k, vals in cells.items():
            agg.setdefault(k[idx], [0.0] * NY)
            for i, x in enumerate(vals):
                agg[k[idx]][i] += x
        tot = sum(v[IDX2026] for v in agg.values()) or 1
        rows = [{"id": mid, "name": lookup[mid]["name"], "revenue": vals[IDX2026], "share": vals[IDX2026] / tot,
                 "cagr": cagr(vals[0], vals[IDX2026], IDX2026)} for mid, vals in agg.items()]
        rows.sort(key=lambda r: r["revenue"], reverse=True)
        result[dim] = rows
    return result


def peers(slug, limit=5):
    co = STORE.companies[slug]
    out = []
    for s, c in STORE.companies.items():
        if s == slug or not STORE.fin.get(s):
            continue
        overlap = len(set(c["subsectors"]) & set(co["subsectors"])) * 2 + len(set(c["verticals"]) & set(co["verticals"]))
        if c["primary"] == co["primary"]:
            overlap += 2
        if overlap:
            out.append((overlap, STORE.fin[s][-1]["revenue"], s))
    out.sort(reverse=True)
    return [STORE.companies[s] | {"revenue": STORE.fin[s][-1]["revenue"], "growth": STORE.fin[s][-1]["growth"],
                                  "ebitda_margin": STORE.fin[s][-1]["ebitda_margin"]} for _, _, s in out[:limit]]


def platform_stats():
    n_cells = len(STORE.market)
    return {
        "countries": len(cfg.COUNTRIES), "subsectors": len(cfg.SUBSECTORS), "verticals": len(cfg.VERTICALS),
        "companies": len(STORE.companies), "news": len(NEWS),
        "datapoints": n_cells * NY + sum(len(c) * NY for c in STORE.company_cells.values()),
        "global_2026": market_series({})[IDX2026],
    }
