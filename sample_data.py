"""
Sample dataset generator. Runs once, on first start, to fill the database with fictional demonstration data
(taxonomy, market sizes, companies and financials). After that everything is edited in Admin > Dashboard data.
All companies, people and events are fictional.
"""
import copy
import math
import random
from datetime import date, timedelta

import config as cfg

YEARS = list(cfg.YEARS)          # a snapshot of the default timeline: the sample is always built for it
LAST_ACTUAL = cfg.LAST_ACTUAL
ESTIMATE_YEAR = cfg.ESTIMATE_YEAR
NY = len(YEARS)
COUNTRIES = copy.deepcopy(cfg.COUNTRIES)
SUBSECTORS = copy.deepcopy(cfg.SUBSECTORS)
VERTICALS = copy.deepcopy(cfg.VERTICALS)
def year_status(y):
    if y <= LAST_ACTUAL:
        return "A"
    if y == ESTIMATE_YEAR:
        return "E"
    return "F"


def slugify(s):
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


COUNTRY = {c["id"]: c for c in COUNTRIES}
SUB = {s["id"]: s for s in SUBSECTORS}
VERT = {v["id"]: v for v in VERTICALS}

# ----------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------
NAME_A = ["Alder", "Brightmoor", "Corvane", "Daymark", "Eastlake", "Fenwick", "Grayhawk", "Halden", "Ironbridge",
          "Juniper", "Kestrel", "Lumen", "Marlow", "Northgate", "Oakhurst", "Pinnacle", "Quillon", "Redwater",
          "Silverline", "Tarn", "Umbra", "Vantor", "Westerly", "Xenith", "Yarrow", "Zephyr", "Ardent", "Beacon",
          "Cobalt", "Drayton", "Elmstead", "Foxglove", "Garnet", "Harbor", "Indigo", "Jasper", "Kinetic",
          "Larkspur", "Monarch", "Nimbus", "Orison", "Paragon", "Quartzite", "Ridgeway", "Stonebridge",
          "Thornfield", "Unity Bay", "Verity", "Wexmoor", "Yondermark"]
NAME_B = ["Group", "Holdings", "Systems", "Partners", "Technologies", "Solutions", "Industries", "Global", "Labs", "Networks"]
FIRST = ["Amara", "Daniel", "Elena", "Farid", "Grace", "Hiro", "Isabel", "Jonas", "Kavya", "Liam", "Mei", "Noah",
         "Olivia", "Priya", "Rafael", "Sofia", "Tomas", "Uma", "Victor", "Wen", "Yara", "Zoe"]
LAST = ["Abbott", "Bianchi", "Chen", "Dubois", "Eriksen", "Fischer", "Gupta", "Haas", "Ibrahim", "Jansen", "Kim",
        "Larsen", "Moreau", "Nakamura", "Okafor", "Petrov", "Quinn", "Reyes", "Silva", "Tanaka", "Voss", "Walker"]
ROLES = ["Chief Executive Officer", "Chief Financial Officer", "Chief Operating Officer", "Chief Technology Officer",
         "Chief Commercial Officer", "Chief Strategy Officer"]
PRODUCTS = ["Horizon", "Vector", "Atlas", "Prism", "Summit", "Catalyst", "Fusion", "Pathway", "Nexus", "Apex", "Relay", "Lattice"]
OUTLETS = ["Meridian Newsroom", "Company press release", "Regulatory filing", "Industry wire"]


class Store:
    pass


def _market_cells(rng):
    """Market size cube: (country, subsector, vertical) -> list per year (US$ bn)."""
    year_shock = {2022: 0.010, 2023: -0.015, 2024: 0.000, 2025: 0.005, 2026: 0.003}
    tot_c = sum(c["weight"] for c in COUNTRIES)
    tot_s = sum(s["weight"] for s in SUBSECTORS)
    tot_v = sum(v["weight"] for v in VERTICALS)
    market, growth = {}, {}
    for c in COUNTRIES:
        for s in SUBSECTORS:
            for v in VERTICALS:
                base = cfg.GLOBAL_BASE_2021 * (c["weight"] / tot_c) * (s["weight"] / tot_s) * (v["weight"] / tot_v)
                base *= rng.uniform(0.82, 1.18)
                g = max(0.005, cfg.BASE_GROWTH + c["growth"] + s["growth"] + v["growth"])
                vals = [base]
                for i, y in enumerate(YEARS[1:], start=1):
                    if y <= ESTIMATE_YEAR:
                        gy = g + year_shock.get(y, 0) + rng.uniform(-0.010, 0.010)
                    else:
                        gy = g * (0.97 ** (y - ESTIMATE_YEAR)) + rng.uniform(-0.004, 0.004)
                    vals.append(vals[-1] * (1 + gy))
                market[(c["id"], s["id"], v["id"])] = vals
                growth[(c["id"], s["id"], v["id"])] = g
    return market


def _companies(rng, market):
    used, companies = set(), {}
    names = NAME_A[:]
    rng.shuffle(names)
    country_ids = [c["id"] for c in COUNTRIES]
    cw = [c["weight"] ** 0.7 for c in COUNTRIES]
    sub_ids = [s["id"] for s in SUBSECTORS]
    sw = [s["weight"] for s in SUBSECTORS]
    vert_ids = [v["id"] for v in VERTICALS]
    structures = ["Public", "Public", "Public", "Public", "Private", "Private (PE-backed)", "Private (founder-owned)"]

    for n in range(46):
        name = f"{names[n]} {rng.choice(NAME_B)}"
        slug = slugify(name)
        if slug in used:
            continue
        used.add(slug)
        hq = rng.choices(country_ids, cw)[0]
        primary = rng.choices(sub_ids, sw)[0]
        subs = [primary]
        if rng.random() < 0.55:
            sec = rng.choice([s for s in sub_ids if s != primary])
            subs.append(sec)
        verts = rng.sample(vert_ids, rng.choice([2, 3, 3, 4]))
        others = [c for c in country_ids if c != hq]
        presence = [hq] + rng.sample(others, rng.choice([1, 2, 3, 4, 5]))
        structure = rng.choice(structures)
        public = structure == "Public"
        ticker = None
        if public:
            letters = "".join(ch for ch in names[n].upper() if ch.isalpha())
            ticker = letters[:3] + rng.choice("XQZTKP")
        companies[slug] = {
            "slug": slug, "name": name, "hq": hq, "city": COUNTRY[hq]["city"],
            "primary": primary, "subsectors": subs, "verticals": verts, "presence": presence,
            "ownership": structure, "ticker": ticker,
            "exchange": COUNTRY[hq]["exchange"] if public else None,
            "founded": rng.randint(1952, 2016),
            "scale": math.exp(rng.gauss(0, 0.65)),
            "drift": max(-0.035, min(0.045, rng.gauss(0.008, 0.02))),
            "margin0": rng.uniform(0.09, 0.32),
            "margin_trend": rng.uniform(-0.004, 0.006),
            "rev_per_emp": rng.uniform(190, 420),     # US$ k
            "multiple": rng.uniform(1.4, 6.5),
            "capex": rng.uniform(0.03, 0.09),
            "gm_gap": rng.uniform(0.22, 0.38),
        }
    return companies


def _company_cells(rng, companies, market):
    shares = {}
    for slug, co in companies.items():
        shares[slug] = {}
        for c in co["presence"]:
            for s in co["subsectors"]:
                for v in co["verticals"]:
                    sh = 0.06 * co["scale"] * rng.uniform(0.5, 1.5)
                    if c == co["hq"]:
                        sh *= 2.2
                    if s != co["primary"]:
                        sh *= 0.5
                    shares[slug][(c, s, v)] = sh
    # cap total share per market cell at 85%
    totals = {}
    for slug, cells in shares.items():
        for k, sh in cells.items():
            totals[k] = totals.get(k, 0) + sh
    for slug, cells in shares.items():
        for k in cells:
            if totals[k] > 0.85:
                cells[k] *= 0.85 / totals[k]
    out = {}
    for slug, co in companies.items():
        out[slug] = {}
        for k, sh in shares[slug].items():
            vals = []
            for i, y in enumerate(YEARS):
                drift = (1 + co["drift"] * 0.5) ** i * rng.uniform(0.985, 1.015)
                vals.append(market[k][i] * 1000.0 * sh * drift)  # US$ m
            out[slug][k] = vals
    return out


def _financials(rng, companies, company_cells):
    fin = {}
    for slug, co in companies.items():
        rev = [sum(v[i] for v in company_cells[slug].values()) for i in range(NY)]
        rows, margin = [], co["margin0"]
        for i, y in enumerate(YEARS):
            margin = max(0.03, min(0.45, margin + co["margin_trend"] + rng.uniform(-0.010, 0.010)))
            if y > ESTIMATE_YEAR:
                rows.append(None)
                continue
            ebitda = rev[i] * margin
            net = ebitda * rng.uniform(0.42, 0.58)
            rows.append({
                "year": y, "status": year_status(y), "revenue": rev[i],
                "growth": (rev[i] / rev[i - 1] - 1) if i > 0 else None,
                "gross_margin": min(0.85, margin + co["gm_gap"]),
                "ebitda": ebitda, "ebitda_margin": margin, "net_income": net,
                "capex": rev[i] * co["capex"] * rng.uniform(0.9, 1.1),
                "employees": int(rev[i] * 1000 / (co["rev_per_emp"] * (1 + 0.012 * i))),
            })
        rows = [r for r in rows if r]
        co["market_cap"] = rows[-1]["revenue"] * co["multiple"] if co["ownership"] == "Public" else None
        fin[slug] = rows
    return fin


def _news(rng, companies, fin):
    end = date.fromisoformat(cfg.TODAY) - timedelta(days=1)
    start = date(2026, 8, 15)
    span = (end - start).days
    news, nid = [], 0
    slugs = list(companies)

    def rand_date(lo=None):
        lo = lo or start
        return lo + timedelta(days=rng.randint(0, (end - lo).days))

    def add(d, headline, summary, ntype, company, country, sub, vert, impact):
        nonlocal nid
        nid += 1
        news.append({"id": nid, "date": d, "headline": headline, "summary": summary, "type": ntype,
                     "company": company, "country": country, "subsector": sub, "vertical": vert,
                     "impact": impact, "source": rng.choice(OUTLETS)})

    for slug, co in companies.items():
        name = co["name"]
        last = fin[slug][-1]
        for _ in range(rng.choice([3, 4, 4, 5])):
            t = rng.choices(["Earnings", "M&A", "Partnership", "Product launch", "Expansion", "Leadership", "Investment"],
                            [3, 1.4, 2, 2, 1.8, 1.2, 1.6])[0]
            sub = rng.choice(co["subsectors"])
            vert = rng.choice(co["verticals"])
            country = rng.choices(co["presence"], [3] + [1] * (len(co["presence"]) - 1))[0]
            cname = COUNTRY[country]["name"]
            vname = VERT[vert]["name"]
            if t == "Earnings":
                d = rand_date(date(2026, 10, 20)) if rng.random() < 0.8 else rand_date()
                q = "Q3 2026" if d >= date(2026, 10, 20) else "Q2 2026"
                g = round(last["growth"] * 100 + rng.uniform(-2.5, 2.5), 1)
                m = round(last["ebitda_margin"] * 100 + rng.uniform(-1.5, 1.5), 1)
                direction = "up" if g >= 0 else "down"
                add(d, f"{name} reports {q} results, revenue {direction} {abs(g)}% year on year",
                    f"Revenue growth of {g}% was supported by demand in {vname}. EBITDA margin came in at {m}%, "
                    f"and management reiterated its full-year outlook.", t, slug, country, sub, vert,
                    "positive" if g >= 4 else ("neutral" if g >= 0 else "negative"))
            elif t == "M&A":
                target = f"{rng.choice(NAME_A)} {rng.choice(['Analytics', 'Works', 'Digital', 'Services', 'Dynamics'])}"
                val = rng.choice([85, 140, 220, 310, 480, 650, 1100])
                if rng.random() < 0.7:
                    add(rand_date(), f"{name} to acquire {target} for US${val:,} million",
                        f"The deal expands {name}'s presence in {SUB[sub]['name']} and adds customers in {vname} across "
                        f"{cname}. Completion is expected in the first half of 2027, subject to regulatory approval.",
                        t, slug, country, sub, vert, "positive")
                else:
                    buyer = COMPANIES_REF[rng.choice([s for s in slugs if s != slug])]["name"]
                    add(rand_date(), f"{name} agrees to sell {SUB[sub]['name']} unit to {buyer}",
                        f"The divestment, valued at around US${val:,} million, sharpens {name}'s focus on its core "
                        f"portfolio and is expected to be margin-accretive from 2027.",
                        t, slug, country, sub, vert, "neutral")
            elif t == "Partnership":
                other = COMPANIES_REF[rng.choice([s for s in slugs if s != slug])]["name"]
                add(rand_date(), f"{name} and {other} form strategic partnership in {vname}",
                    f"The multi-year agreement combines both companies' capabilities to serve {vname} customers in "
                    f"{cname} and neighbouring markets, with first joint offerings planned for 2027.",
                    t, slug, country, sub, vert, "positive")
            elif t == "Product launch":
                prod = f"{name.split()[0]} {rng.choice(PRODUCTS)}"
                add(rand_date(), f"{name} launches {prod} for {vname} customers",
                    f"The new offering targets {SUB[sub]['phrase']} and is available in {cname} from this quarter, "
                    f"with wider rollout planned over the next twelve months.",
                    t, slug, country, sub, vert, "positive")
            elif t == "Expansion":
                add(rand_date(), f"{name} opens new regional hub in {COUNTRY[country]['city']}",
                    f"The site will serve customers in {cname} and add roles over the next two years as {name} scales "
                    f"its {SUB[sub]['name']} activities.", t, slug, country, sub, vert, "positive")
            elif t == "Leadership":
                person = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                role = rng.choice(ROLES)
                add(rand_date(), f"{name} appoints {person} as {role}",
                    f"{person} joins from a senior role in the sector and will lead the company's priorities in "
                    f"{SUB[sub]['name']}, effective January 2027.", t, slug, country, sub, vert, "neutral")
            else:
                amt = rng.choice([40, 75, 120, 200, 350, 500])
                add(rand_date(), f"{name} commits US${amt:,} million to expand capacity in {cname}",
                    f"The investment will fund new capacity and talent for {SUB[sub]['name']}, targeting growth "
                    f"in {vname}.", t, slug, country, sub, vert, "positive")

    # market-level news
    mk = [
        ("{c} proposes new compliance framework affecting {v}", "Draft rules would raise reporting and data requirements for providers serving {v}. A consultation runs until early 2027.", "negative"),
        ("{c} announces stimulus programme for {s}", "The programme earmarks multi-year funding to accelerate adoption and local capacity in {s}.", "positive"),
        ("Demand for {s} accelerates across {c}", "Buyers in {v} are bringing forward spending, according to recent procurement data.", "positive"),
        ("{c} trade measures raise input costs for {s}", "New tariffs and customs checks are expected to add cost pressure through 2027.", "negative"),
        ("{v} budgets in {c} hold steady into 2027", "Planning surveys point to flat-to-modest growth in spending on {s}.", "neutral"),
        ("Talent shortage slows {s} projects in {c}", "Providers report longer delivery times and rising wage costs in {v}.", "negative"),
    ]
    for _ in range(46):
        c = rng.choice(COUNTRIES)
        s = rng.choice(SUBSECTORS)
        v = rng.choice(VERTICALS)
        h, summ, imp = rng.choice(mk)
        fmt = dict(c=c["name"], s=s["name"], v=v["name"])
        sub = s["id"] if rng.random() < 0.8 else None
        vert = v["id"] if rng.random() < 0.8 else None
        add(rand_date(), h.format(**fmt), summ.format(**fmt), "Market", None, c["id"], sub, vert, imp)

    news.sort(key=lambda n: (n["date"], n["id"]), reverse=True)
    return news


COMPANIES_REF = {}


def build_store():
    rng = random.Random(cfg.SEED)
    st = Store()
    st.market = _market_cells(rng)
    st.companies = _companies(rng, st.market)
    COMPANIES_REF.clear()
    COMPANIES_REF.update(st.companies)
    st.company_cells = _company_cells(rng, st.companies, st.market)
    st.fin = _financials(rng, st.companies, st.company_cells)
    st.seed_news = _news(rng, st.companies, st.fin)   # used once to seed the database
    return st




_CACHE = []


def get():
    """The generated sample store (built once per process)."""
    if not _CACHE:
        _CACHE.append(build_store())
    return _CACHE[0]
