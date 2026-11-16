"""
First-run seed content. When the database is empty, the sample news, white papers and reports are written to it.
After that, everything is managed in Admin. To start over, delete instance/site.db and restart.
"""
import config as cfg
import content
import data as d
import db


def _chart(kind, title, unit, header, rows, source="Meridian sample data"):
    lines = ["```chart", f"type: {kind}", f"title: {title}", f"unit: {unit}", f"source: {source}", ", ".join(header)]
    lines += [", ".join(str(x) for x in r) for r in rows]
    lines.append("```")
    return "\n".join(lines)


def _revenue_chart(slug):
    rows = [(f"{r['year']}{'E' if r['status'] == 'E' else ''}", round(r["revenue"])) for r in d.STORE.fin[slug]]
    return _chart("bar", "Revenue", "US$ m", ["Year", "Revenue"], rows, "Company filings (sample data)")


def _market_chart(country, sub):
    vals = d.market_series({"country": country, "subsector": sub})
    rows = [(y, round(v, 1)) for y, v in zip(d.YEARS, vals)]
    title = f"{d.SUB[sub]['name']} market, {d.COUNTRY[country]['name']}"
    return _chart("line", title, "US$ bn", ["Year", "Market size"], rows, "Meridian market model (sample data)")


def news_body(n):
    co = d.STORE.companies.get(n["company"]) if n["company"] else None
    country = d.COUNTRY.get(n["country"])
    sub = d.SUB.get(n["subsector"]) if n["subsector"] else None
    vert = d.VERT.get(n["vertical"]) if n["vertical"] else None
    parts = []   # the summary is shown in the article header, so the body starts with new information
    if n["type"] == "Earnings" and co:
        last = d.STORE.fin[co["slug"]][-1]
        parts.append(f"{n['headline']}. Over the past five years {co['name']} has grown revenue from US${d.STORE.fin[co['slug']][0]['revenue']:,.0f} million "
                     f"to an estimated US${last['revenue']:,.0f} million in {last['year']}. EBITDA margin stands at "
                     f"{last['ebitda_margin'] * 100:.1f}%, and the company employs about {last['employees']:,} people.")
        parts.append(_revenue_chart(co["slug"]))
        parts.append(f"Analysts will watch {SUB_NAME(sub)} demand and cost discipline into the fourth quarter. "
                     f"See the full financial summary on the company profile.")
    elif n["type"] == "Market" and country and sub:
        parts.append(f"{n['headline']}. The {sub['name']} market in {country['name']} is estimated at US${d.market_series({'country': n['country'], 'subsector': n['subsector']})[d.IDX2026]:,.1f} billion in {cfg.ESTIMATE_YEAR}.")
        parts.append(_market_chart(n["country"], n["subsector"]))
        parts.append("Providers and buyers should expect the effects to build gradually through 2027, with the largest impact on the most regulated or cost-sensitive customers.")
    else:
        who = co["name"] if co else "The market"
        parts.append(f"The move fits a wider pattern in {sub['name'] if sub else 'the sector'}"
                     f"{' and ' + vert['name'] if vert else ''}, where companies are repositioning toward faster-growing activities "
                     f"and customers that value scale and reliability.")
        parts.append(f"{who} did not disclose further financial terms. We will update this story as more detail is published.")
    return "\n\n".join(parts)


def SUB_NAME(sub):
    return sub["name"] if sub else "core"


def seed_news():
    items = []
    for n in d.STORE.seed_news:
        items.append({
            "title": n["headline"], "summary": n["summary"], "body": news_body(n), "date": str(n["date"]),
            "author": n["source"], "tags": [n["type"]], "status": "published",
            "meta": {"type": n["type"], "company": n["company"] or "", "country": n["country"] or "",
                     "subsector": n["subsector"] or "", "vertical": n["vertical"] or "", "impact": n["impact"],
                     "source": n["source"]},
        })
    return items


def _paper_charts():
    subs = []
    for s in cfg.SUBSECTORS:
        v = d.market_series({"subsector": s["id"]})
        subs.append((s["name"], round(100 * d.cagr(v[d.IDX2026], v[-1], len(v) - 1 - d.IDX2026), 1)))
    subs.sort(key=lambda r: r[1], reverse=True)
    hbar = _chart("hbar", "Expected growth to 2030 by sub-sector", "% a year", ["Sub-sector", "Growth"], subs)
    years = [2021, 2023, 2026, 2028, 2030]
    rows = []
    for y in years:
        i = d.YEARS.index(y)
        rows.append([y] + [round(d.market_series({"subsector": s["id"]})[i]) for s in cfg.SUBSECTORS[:3]])
    line = _chart("bar", "Market size by sub-sector", "US$ bn", ["Year"] + [s["name"] for s in cfg.SUBSECTORS[:3]], rows)
    return {0: hbar, 1: line}


def seed_papers():
    out = []
    for i, p in enumerate(content.WHITE_PAPERS):
        extras = _paper_charts() if i == 0 else {}
        md = []
        for k, (h, paras) in enumerate(p["sections"]):
            md.append(f"## {h}\n")
            md.append("\n\n".join(paras))
            if k in extras:
                md.append("\n" + extras[k] + "\n")
        out.append({"slug": p["slug"], "title": p["title"], "summary": p["summary"], "body": "\n\n".join(md), "date": p["date"],
                    "author": p["author"], "tags": p["tags"], "status": "published",
                    "meta": {"takeaways": p["takeaways"], "pages": p["pages"]}})
    return out


def seed_reports():
    out = []
    for i, r in enumerate(content.REPORTS):
        body = f"{r['summary']}\n\n"
        if i == 0:
            rows = [(y, round(v)) for y, v in zip(d.YEARS, d.market_series({}))]
            body += _chart("bar", "Global market size, 2021 to 2030", "US$ bn", ["Year", "Market size"], rows, "Global Market Outlook 2027 (sample)") + "\n\n"
            body += "The chart above is a sample finding from the report. The full report breaks the market down by country, sub-sector and vertical.\n"
        out.append({"slug": r["slug"], "title": r["title"], "summary": r["summary"], "body": body, "date": r["date"], "author": "Meridian Research",
                    "tags": [r["category"]], "status": "published",
                    "meta": {"subtitle": r["subtitle"], "price": r["price"], "pages": r["pages"], "coverage": r["coverage"],
                             "category": r["category"], "highlights": r["highlights"], "toc": r["toc"]}})
    return out


def run():
    db.init()
    if db.count() > 0:
        return False
    db.bulk_insert("paper", seed_papers())
    db.bulk_insert("report", seed_reports())
    db.bulk_insert("news", seed_news())
    return True
