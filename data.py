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
import timeline

YEARS = cfg.YEARS      # the same list object as config.YEARS: the timeline updates it in place
NY = len(YEARS)
IDX2026 = YEARS.index(cfg.ESTIMATE_YEAR)     # index of the current (headline) year, whichever year that is
IDX2025 = IDX2026 - 1                        # ... and of the year before it


def _sync_timeline():
    global NY, IDX2026, IDX2025
    timeline.apply()
    NY = len(YEARS)
    IDX2026 = YEARS.index(cfg.ESTIMATE_YEAR)
    IDX2025 = IDX2026 - 1

COUNTRY, SUB, VERT = {}, {}, {}
DIM_LOOKUP = {"country": COUNTRY, "subsector": SUB, "vertical": VERT}
DIM_ORDER = ["country", "subsector", "vertical", "company"]
_LISTS = {"country": cfg.COUNTRIES, "subsector": cfg.SUBSECTORS, "vertical": cfg.VERTICALS}


def year_status(y):
    return timeline.year_status(y)


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
        self.fin_q, self.fin_raw = {}, {}


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


_FLOWS = ("revenue", "ebitda", "net_income", "capex")


def _qconf(r):
    """Resolved confidence level of a quarterly row: reported up to the last reported quarter, otherwise a high estimate."""
    if r.get("conf") in dataio.LEVEL:
        return r["conf"]
    return "reported" if timeline.quarter_status(r["year"], r["quarter"]) == "A" else "high"


def project_quarters(reported):
    """Quarters you have not entered, from the first reported quarter to the end of the current year: {(year, quarter): row}.
    A missing quarter is the same quarter a year earlier (reported or itself projected) times the recent growth: the latest
    four reported quarters against the same quarters a year before, limited to between 0.5x and 2x. With no year-earlier
    figures it repeats the quarter before. EBITDA, net income and capex keep the share of revenue they had over the latest
    four reported quarters, and are left blank if any of those quarters lacks them."""
    keys = sorted(reported)
    if not keys:
        return {}
    chain = {k: reported[k]["revenue"] for k in keys}
    out = {}
    for n in range(timeline.qkey(keys[0][0], 1), timeline.qkey(cfg.ESTIMATE_YEAR, 4) + 1):
        y, q = n // 4, n % 4 + 1
        if (y, q) in reported:
            continue
        prior = [k for k in keys if timeline.qkey(*k) < n][-4:]
        pairs = [k for k in prior if (k[0] - 1, k[1]) in reported]
        num = sum(reported[k]["revenue"] for k in pairs)
        den = sum(reported[(k[0] - 1, k[1])]["revenue"] for k in pairs)
        g = max(0.5, min(2.0, num / den)) if den > 0 else None
        base, before = chain.get((y - 1, q)), chain.get(((n - 1) // 4, (n - 1) % 4 + 1))
        rev = base * g if base is not None and g is not None else (before if before is not None else reported[keys[0]]["revenue"])
        chain[(y, q)] = rev
        row = {"year": y, "quarter": q, "revenue": rev, "conf": "low"}
        rsum = sum(reported[k]["revenue"] for k in prior)
        for f in _FLOWS[1:]:
            row[f] = rev * sum(reported[k][f] for k in prior) / rsum if prior and rsum > 0 and all(reported[k].get(f) is not None for k in prior) else None
        out[(y, q)] = row
    return out


def derive_years(reported):
    """Annual figures from quarterly rows, for every year from the first reported quarter to the current year: reported
    quarters plus projected ones (see project_quarters). A year's confidence is the lowest of its reported quarters, capped
    by how many quarters were projected (one: high, two: medium, three or four: low)."""
    proj = project_quarters(reported)
    out = {}
    for y in sorted({k[0] for k in list(reported) + list(proj)}):
        comps = [reported.get((y, q)) or proj.get((y, q)) for q in range(1, 5)]
        if any(c is None for c in comps):
            continue
        nrep = sum(1 for q in range(1, 5) if (y, q) in reported)
        row = {"year": y, "q_reported": nrep, "q_projected": 4 - nrep}
        for f in _FLOWS:
            row[f] = None if any(c.get(f) is None for c in comps) else sum(c[f] for c in comps)
        score = min([dataio.LEVEL[_qconf(reported[(y, q)])]["score"] for q in range(1, 5) if (y, q) in reported] or [1])
        row["conf_level"] = dataio.BY_SCORE[min(score, {0: 4, 1: 3, 2: 2, 3: 1, 4: 1}[4 - nrep])]
        out[y] = row
    return out


def build_quarters(reported):
    """Quarterly rows for display, oldest first, up to the current quarter: reported ones plus projected ones, with growth on
    the same quarter a year earlier and on the quarter before."""
    proj = project_quarters(reported)
    cur = timeline.qkey(cfg.ESTIMATE_YEAR, timeline.CURRENT["q"])
    idx = {**{k: {**r, "projected": False} for k, r in reported.items()},
           **{k: {**r, "projected": True} for k, r in proj.items() if timeline.qkey(*k) <= cur}}
    rows = []
    for (y, q), r in sorted(idx.items()):
        py, pq = idx.get((y - 1, q)), idx.get((y - 1, 4) if q == 1 else (y, q - 1))
        rev = r["revenue"]
        rows.append({"year": y, "quarter": q, "label": timeline.qlabel(y, q), "short": timeline.qlabel(y, q, True),
                     "status": timeline.quarter_status(y, q), "revenue": rev, "projected": r["projected"],
                     "yoy": (rev / py["revenue"] - 1) if py and py["revenue"] else None,
                     "qoq": (rev / pq["revenue"] - 1) if pq and pq["revenue"] else None,
                     "ebitda": r["ebitda"], "ebitda_margin": (r["ebitda"] / rev) if r["ebitda"] is not None and rev else None,
                     "net_income": r["net_income"], "capex": r["capex"],
                     "conf_raw": None if r["projected"] else (r.get("conf") if r.get("conf") in dataio.LEVEL else None),
                     "conf": "low" if r["projected"] else _qconf(r)})
    return rows


def reload():
    global LOADED_VERSION
    ver = dataio.db.version()
    _sync_timeline()
    dims = dataio.load_dims()
    for kind, lookup in DIM_LOOKUP.items():
        lookup.clear()
        for r in dims[kind]:
            lookup[r["id"]] = r
        _LISTS[kind][:] = dims[kind]
    market = {k: v for k, v in dataio.load_market().items()
              if k[0] in COUNTRY and k[1] in SUB and k[2] in VERT and len(v) == NY}
    mconf = {k: v for k, v in dataio.load_market_conf().items() if k in market}
    profiles, fins, fins_q = dataio.load_companies(), dataio.load_fin(), dataio.load_fin_q()

    companies, fin, cells_all, fin_q, fin_raw = {}, {}, {}, {}, {}
    for slug, p in profiles.items():
        alloc = {dim: normalise_alloc(p.get("alloc", {}).get(dim)) for dim in ("country", "subsector", "vertical")}
        alloc = {dim: {k: v for k, v in a.items() if k in DIM_LOOKUP[dim]} for dim, a in alloc.items()}
        raw = [{"year": r["year"], "revenue": r["revenue"], "gross_margin": r["gross_margin"], "ebitda": r["ebitda"],
                "net_income": r["net_income"], "capex": r["capex"], "employees": r["employees"],
                "conf_raw": r.get("conf") if r.get("conf") in dataio.LEVEL else None}
               for r in fins.get(slug, []) if r["year"] in YEARS]
        by_year = {r["year"]: dict(r) for r in raw if r["revenue"] is not None}
        rep_q = {(r["year"], r["quarter"]): r for r in fins_q.get(slug, []) if r["year"] in YEARS and r["revenue"] is not None}
        qrows = build_quarters(rep_q)
        for y, dr in derive_years(rep_q).items():
            if y in YEARS and y <= cfg.ESTIMATE_YEAR:        # quarterly figures replace the annual row for that year
                base = by_year.get(y, {"year": y, "gross_margin": None, "employees": None})
                base.update({f: dr[f] for f in _FLOWS})
                base.update({"conf_raw": None, "conf_level": dr["conf_level"], "q_reported": dr["q_reported"], "q_projected": dr["q_projected"]})
                by_year[y] = base
        rows = []
        for y in sorted(by_year):
            r = by_year[y]
            prev = rows[-1] if rows and rows[-1]["year"] == y - 1 else None
            rev = r["revenue"]
            rows.append({"year": y, "status": year_status(y), "revenue": rev,
                         "growth": (rev / prev["revenue"] - 1) if prev and prev["revenue"] else None,
                         "gross_margin": r["gross_margin"], "ebitda": r["ebitda"],
                         "ebitda_margin": (r["ebitda"] / rev) if r["ebitda"] is not None and rev else None,
                         "net_income": r["net_income"], "capex": r["capex"], "employees": r["employees"],
                         "conf_raw": r["conf_raw"],
                         "conf": r["conf_level"] if "conf_level" in r else (r["conf_raw"] or dataio.fin_default_conf(y)),
                         "q_reported": r.get("q_reported"), "q_projected": r.get("q_projected")})
        fin_q[slug], fin_raw[slug] = qrows, raw
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
        if rows and series and rows[-1]["year"] < cfg.ESTIMATE_YEAR:
            # No figures for the latest years: show them anyway, so the company moves with the timeline. Revenue follows the
            # markets the company sells into; EBITDA keeps the latest margin; everything else is left blank.
            hold = next((r["ebitda_margin"] for r in reversed(rows) if r["ebitda_margin"] is not None), None)
            for y in range(rows[-1]["year"] + 1, cfg.ESTIMATE_YEAR + 1):
                rev, prev = series[YEARS.index(y)], rows[-1]
                rows.append({"year": y, "status": year_status(y), "revenue": rev, "growth": (rev / prev["revenue"] - 1) if prev["revenue"] else None,
                             "gross_margin": None, "ebitda": rev * hold if hold is not None else None, "ebitda_margin": hold,
                             "net_income": None, "capex": None, "employees": None, "conf_raw": None, "conf": dataio.LEVELS[-1]["id"],
                             "q_reported": None, "q_projected": None, "extrapolated": True, "hold_year": None})
        companies[slug] = {
            "slug": slug, "name": p["name"], "hq": hq, "city": p.get("city") or (COUNTRY[hq].get("city", "") if hq else ""),
            "ownership": p.get("ownership") or "Private", "ticker": p.get("ticker") or None,
            "exchange": p.get("exchange") or None, "website": p.get("website") or "", "founded": p.get("founded"), "market_cap": p.get("market_cap"),
            "description": p.get("description") or "", "alloc": p.get("alloc", {}),
            "primary": subs[0] if subs else None, "subsectors": subs, "verticals": verts, "presence": pres,
            "has_split": bool(cells), "has_quarterly": bool(qrows),
        }
        fin[slug] = rows

    for store_dict, new in ((STORE.market, market), (STORE.market_conf, mconf), (STORE.companies, companies), (STORE.company_cells, cells_all), (STORE.fin, fin), (STORE.fin_q, fin_q), (STORE.fin_raw, fin_raw)):
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


def cagr_windows():
    """Indexes for the two growth columns: the last CAGR_YEARS years up to the current year (fewer if the timeline starts
    later), and the CAGR_YEARS years after it (fewer if the forecast ends sooner)."""
    return max(0, IDX2026 - cfg.CAGR_YEARS), IDX2026, min(NY - 1, IDX2026 + cfg.CAGR_YEARS)


def cagr_years():
    """The two growth windows as year pairs, for labels: ((from, to), (from, to))."""
    h0, h1, f1 = cagr_windows()
    return {"from": YEARS[h0], "to": YEARS[h1]}, {"from": YEARS[h1], "to": YEARS[f1]}


def hist_cagr(vals):
    h0, h1, _ = cagr_windows()
    return cagr(vals[h0], vals[h1], h1 - h0)


def summarize(vals):
    h0, h1, f1 = cagr_windows()
    return {
        "size": vals[IDX2026],
        "prev": vals[IDX2025],
        "yoy": cagr(vals[IDX2025], vals[IDX2026], 1),
        "cagr_hist": hist_cagr(vals),
        "cagr_fc": cagr(vals[IDX2026], vals[f1], f1 - IDX2026),
        "fc_end": vals[f1],
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


HEAT_MAX = 6      # most sub-sectors (rows) and verticals (columns) the grid shows


def heatmap(f):
    """Sub-sector by vertical grid for the current selection. With many of either, only the largest are shown
    (plus the one currently selected, if any)."""
    g = {"country": f.get("country")}

    def top(items, dim):
        ranked = sorted(items, key=lambda x: market_series({**g, dim: x["id"]})[IDX2026], reverse=True)
        keep = ranked[:HEAT_MAX]
        sel = f.get(dim)
        if sel and all(x["id"] != sel for x in keep):
            keep = keep[:HEAT_MAX - 1] + [x for x in ranked if x["id"] == sel]
        return keep

    subs, verts = top(cfg.SUBSECTORS, "subsector"), top(cfg.VERTICALS, "vertical")
    grid, mx = [], 0
    for s in subs:
        row = []
        for v in verts:
            val = market_series({**g, "subsector": s["id"], "vertical": v["id"]})[IDX2026]
            mx = max(mx, val)
            row.append({"sub": s["id"], "vert": v["id"], "value": val})
        grid.append({"sub": s, "cells": row})
    for r in grid:
        for c in r["cells"]:
            c["intensity"] = c["value"] / mx if mx else 0
            c["active"] = (f.get("subsector") in (None, c["sub"]) and f.get("vertical") in (None, c["vert"])
                           and (f.get("subsector") or f.get("vertical")) is not None)
    return {"rows": grid, "cols": verts, "total_sub": len(cfg.SUBSECTORS), "total_vert": len(cfg.VERTICALS),
            "trimmed": len(subs) < len(cfg.SUBSECTORS) or len(verts) < len(cfg.VERTICALS)}


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
                 "cagr": hist_cagr(vals)} for mid, vals in agg.items()]
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
