"""Meridian Market Intelligence: Flask application (public site, dashboard, admin)."""
import hmac
import os
import secrets
import time
import uuid
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlencode

from flask import (Flask, g, Response, abort, flash, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)

import config as cfg
import content
import data as d
import dataio
import timeline
import datamgr
import db
import members
import richtext
import seed
import settings

ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.path.join(ROOT, "instance")
UPLOADS = os.path.join(INSTANCE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)


def _secret_key():
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(INSTANCE, "secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    return key


app = Flask(__name__)
app.config["SECRET_KEY"] = _secret_key()
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

KIND_OF = {"news": "news", "papers": "paper", "reports": "report"}      # admin section -> db kind
SECTION_LABEL = {"news": "News", "papers": "White papers", "reports": "Reports"}
SECTION_SINGULAR = {"news": "news article", "papers": "white paper", "reports": "report"}


# ----------------------------------------------------------------------
# Content cache (news feeds the dashboard)
# ----------------------------------------------------------------------
def post_to_news(p):
    m = p["meta"]
    return {"id": p["id"], "slug": p["slug"], "date": p["date"], "headline": p["title"], "summary": p["summary"],
            "type": m.get("type") or "Market", "company": m.get("company") if m.get("company") in d.STORE.companies else None,
            "country": m.get("country") if m.get("country") in d.COUNTRY else None,
            "subsector": m.get("subsector") if m.get("subsector") in d.SUB else None,
            "vertical": m.get("vertical") if m.get("vertical") in d.VERT else None,
            "impact": m.get("impact") or "neutral", "source": m.get("source") or p.get("author") or "", "cover": p["cover"]}


def refresh_news():
    d.set_news([post_to_news(p) for p in db.list_posts("news")])


def reload_all():
    d.reload()
    refresh_news()


db.init()
dataio.ensure_seeded()
d.reload()
seed.run()
refresh_news()
_loaded = {"v": db.version()}


@app.before_request
def sync_workers():
    """When data or content changed (in this or another worker), rebuild the in-memory copy."""
    if request.endpoint != "static" and db.version() != _loaded["v"]:
        _loaded["v"] = db.version()
        reload_all()


# ----------------------------------------------------------------------
# Template helpers
# ----------------------------------------------------------------------
def fmt_bn(v, dec=1):
    return f"{v:,.{dec}f}"


def fmt_m(v):
    if v is None:
        return "n/a"
    if abs(v) >= 1000:
        return f"{v / 1000:,.1f} bn"
    return f"{v:,.0f} m"


def fmt_pct(v, dec=1, sign=False):
    if v is None:
        return "n/a"
    return f"{v * 100:+.{dec}f}%" if sign else f"{v * 100:.{dec}f}%"


def fmt_date(s, long=False):
    try:
        dt = datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except ValueError:
        return str(s)
    return dt.strftime("%d %B %Y" if long else "%d %b %Y").lstrip("0")


def money(v):
    return f"US${v:,.0f}"


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def is_admin():
    return bool(session.get("admin"))


app.jinja_env.globals.update(
    fmt_bn=fmt_bn, fmt_m=fmt_m, fmt_pct=fmt_pct, fmt_date=fmt_date, money=money,
    COUNTRY=d.COUNTRY, SUB=d.SUB, VERT=d.VERT, companies_all=d.STORE.companies, NEWS_TYPES=cfg.NEWS_TYPES,
    csrf_token=csrf_token, is_admin=is_admin, ysuf=timeline.year_suffix, CONF=dataio.LEVEL, CONF_LEVELS=dataio.LEVELS,
)


@app.context_processor
def inject():
    s = settings.load()
    return {"brand": s["brand"], "theme_v": settings.version(), "fonts_url": s["theme"]["google_fonts_url"],
            "nav_active": request.endpoint, "hidden": dataio.hidden_blocks(), "sample_notice": db.get_meta("sample_notice", "1") == "1", "copyright_year": date.today().year, "year_now": cfg.ESTIMATE_YEAR, "tl": timeline.describe(), "cagr_h": d.cagr_years()[0], "cagr_f": d.cagr_years()[1], "now_lbl": f"{cfg.ESTIMATE_YEAR}{timeline.year_suffix(cfg.ESTIMATE_YEAR)}", "CONF": dataio.LEVEL, "CONF_LEVELS": dataio.LEVELS}


app.jinja_env.filters["md"] = richtext.render


def get_filters(args=None):
    args = args or request.args
    f = {}
    for dim in ("country", "subsector", "vertical"):
        val = args.get(dim)
        if val and val in d.DIM_LOOKUP[dim]:
            f[dim] = val
    return f


def default_view(f):
    for dim in d.DIM_ORDER:
        if dim == "company" or dim not in f:
            return dim
    return "company"


def paginate(items, per):
    pages = max(1, -(-len(items) // per))
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    page = max(1, min(page, pages))
    return items[(page - 1) * per: page * per], page, pages


def per_page(key):
    return settings.load()["pagination"][key]


# ----------------------------------------------------------------------
# Theme and uploaded files
# ----------------------------------------------------------------------
@app.route("/theme.css")
def theme_css():
    css = render_template("theme.css", t=settings.theme_context())
    resp = Response(css, mimetype="text/css")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/favicon.svg")
def favicon_svg():
    t = settings.load()
    th, letter = t["theme"], (t["brand"]["name"] or "M")[:1].upper()
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="{th["primary"]}"/>'
           f'<text x="16" y="23" text-anchor="middle" font-family="Georgia,serif" font-size="21" font-weight="700" fill="{th["highlight"]}">{letter}</text></svg>')
    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/uploads/<path:filename>")
def uploads(filename):
    resp = send_from_directory(UPLOADS, filename, max_age=3600)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ----------------------------------------------------------------------
# Public pages
# ----------------------------------------------------------------------
@app.route("/")
def home():
    stats = d.platform_stats()
    top_countries, _ = d.breakdown("country", {})
    series = d.series_rows(d.market_series({}))
    return render_template("home.html", stats=stats, latest=d.NEWS[:4], series=series, top_countries=top_countries[:5],
                           papers=db.list_posts("paper")[:2], reports=db.list_posts("report")[:2])


@app.route("/dashboard")
def dashboard():
    f = get_filters()
    view = request.args.get("view")
    if view not in d.DIM_ORDER or (view != "company" and view in f):
        view = default_view(f)
    rows, total = d.breakdown(view, f)
    summ = d.summarize(total)
    news = d.news_for_slice(f, limit=8)
    heat = d.heatmap(f)

    crumbs, acc = [], {}
    for dim in ("country", "subsector", "vertical"):
        if dim in f:
            acc[dim] = f[dim]
            crumbs.append({"dim": dim, "id": f[dim], "name": d.DIM_LOOKUP[dim][f[dim]]["name"],
                           "url": url_for("dashboard", **acc),
                           "remove": url_for("dashboard", **{k: v for k, v in f.items() if k != dim})})

    for r in rows:
        if view == "company":
            r["url"] = url_for("company", slug=r["id"], **f)
        else:
            nf = {**f, view: r["id"]}
            r["url"] = url_for("dashboard", **nf, view=default_view(nf))
    for row in heat:
        for c in row["cells"]:
            nf = {**f, "subsector": c["sub"], "vertical": c["vert"]}
            c["url"] = url_for("dashboard", **nf, view="company")

    top = rows[:5]
    unit = "US$ bn" if view != "company" else "US$ m"
    chart_lines = [{"name": r["name"], "values": [round(v, 2) for v in r["series"]]} for r in top]
    chart_bars = [{"year": y, "value": round(v, 2), "status": d.year_status(y)} for y, v in zip(d.YEARS, total)]
    title = " · ".join(d.DIM_LOOKUP[k][v]["name"] for k, v in f.items()) if f else "Global market"

    blocks = [{"kind": dim, "name": d.DIM_LOOKUP[dim][f[dim]]["name"], **d.section_blocks(dim, f[dim])} for dim in ("country", "subsector", "vertical") if dim in f]
    blocks = [b for b in blocks if b["facts"] or b["top"] or b["bottom"]]
    summ["conf"] = d.market_confidence(f)
    return render_template("dashboard.html", f=f, view=view, rows=rows, summ=summ, news=news, heat=heat, blocks=blocks,
                           crumbs=crumbs, title=title, unit=unit, years=d.YEARS,
                           chart_lines=chart_lines, chart_bars=chart_bars,
                           n_companies=len(d.breakdown("company", f)[0]), news_params=dict(f),
                           tabs=[("country", "Country"), ("subsector", "Sub-sector"), ("vertical", "Vertical"),
                                 ("company", "Company")])


@app.route("/company/<slug>")
def company(slug):
    co = d.STORE.companies.get(slug)
    if not co:
        abort(404)
    f = get_filters()
    fin = d.STORE.fin.get(slug, [])
    latest, prev = d.last_fin(slug), d.prev_fin(slug)
    emp = next((r["employees"] for r in reversed(fin) if r["employees"] is not None), None)   # latest headcount reported
    slice_info = None
    if f:
        mkt = d.market_series(f)
        cs = d.company_series(slug, f)
        slice_info = {"revenue": cs[d.IDX2026], "market": mkt[d.IDX2026] * 1000,
                      "share": cs[d.IDX2026] / (mkt[d.IDX2026] * 1000) if mkt[d.IDX2026] else 0,
                      "cagr": d.hist_cagr(cs),
                      "label": " · ".join(d.DIM_LOOKUP[k][v]["name"] for k, v in f.items())}
    chart_rev = [{"year": r["year"], "value": round(r["revenue"], 1), "status": r["status"]} for r in fin]
    chart_margin = [{"year": r["year"], "value": round(r["ebitda_margin"] * 100, 2), "status": r["status"]} for r in fin
                    if r["ebitda_margin"] is not None]
    back = url_for("dashboard", **f, view="company") if f else url_for("dashboard", view="company")
    return render_template("company.html", co=co, fin=fin, latest=latest, prev=prev, emp=emp,
                           bd=d.company_breakdowns(slug), news=d.company_news(slug, 6), peers=d.peers(slug),
                           fin_q=d.STORE.fin_q.get(slug, []),
                           chart_revq=[{"year": r["short"], "value": round(r["revenue"], 1), "status": r["status"]} for r in d.STORE.fin_q.get(slug, [])[-12:]],
                           chart_rev=chart_rev, chart_margin=chart_margin, slice_info=slice_info, f=f, back=back,
                           blocks=d.section_blocks("company", slug))


# ---- News -------------------------------------------------------------
@app.route("/news")
def news_list():
    f = get_filters()
    company_slug = request.args.get("company") if request.args.get("company") in d.STORE.companies else None
    ntype = request.args.get("type") if request.args.get("type") in cfg.NEWS_TYPES else None
    q = (request.args.get("q") or "").strip() or None
    items = d.filter_news(f, company=company_slug, ntype=ntype, q=q)
    page_items, page, pages = paginate(items, per_page("news"))
    params = {**f, "company": company_slug, "type": ntype, "q": q}
    chips = []
    for key, label in [(k, d.DIM_LOOKUP[k][v]["name"]) for k, v in f.items()] + \
            ([("company", d.STORE.companies[company_slug]["name"])] if company_slug else []):
        chips.append({"name": label, "remove": url_for("news_list", **{k: v for k, v in params.items() if k != key})})
    return render_template("news_list.html", items=page_items, total=len(items), page=page, pages=pages, f=f,
                           company_slug=company_slug, ntype=ntype, q=q or "", params=params, chips=chips)


@app.route("/updates")
def updates_redirect():
    return redirect(url_for("news_list", **request.args), 301)


@app.route("/news/<slug>")
def news_article(slug):
    p = db.get_by_slug("news", slug, published_only=not is_admin())
    if not p:
        abort(404)
    n = post_to_news(p)
    related = [x for x in d.NEWS if x["slug"] != slug and
               ((n["company"] and x["company"] == n["company"]) or (n["country"] and x["country"] == n["country"]))][:4]
    return render_template("news_article.html", p=p, n=n, body=richtext.render(p["body"]), related=related)


# ---- White papers -----------------------------------------------------
@app.route("/white-papers")
def whitepapers():
    tag = request.args.get("tag")
    allp = db.list_posts("paper")
    tags = sorted({t for p in allp for t in p["tags"]})
    papers = [p for p in allp if not tag or tag in p["tags"]]
    page_items, page, pages = paginate(papers, per_page("papers"))
    return render_template("whitepapers.html", papers=page_items, tags=tags, tag=tag, page=page, pages=pages,
                           params={"tag": tag})


@app.route("/white-papers/<slug>")
def whitepaper(slug):
    p = db.get_by_slug("paper", slug, published_only=not is_admin())
    if not p:
        abort(404)
    more = [x for x in db.list_posts("paper") if x["slug"] != slug][:3]
    locked = not (is_admin() or g.user)
    return render_template("whitepaper_detail.html", p=p, body="" if locked else richtext.render(p["body"]), locked=locked,
                           read_min=richtext.read_minutes(p["body"]), more=more)


# ---- Reports ----------------------------------------------------------
@app.route("/reports")
def reports():
    cat = request.args.get("category")
    allr = db.list_posts("report")
    cats = sorted({r["meta"].get("category", "") for r in allr if r["meta"].get("category")})
    items = [r for r in allr if not cat or r["meta"].get("category") == cat]
    page_items, page, pages = paginate(items, per_page("reports"))
    return render_template("reports.html", reports=page_items, cats=cats, cat=cat, page=page, pages=pages,
                           params={"category": cat})


@app.route("/reports/<slug>", methods=["GET", "POST"])
def report(slug):
    r = db.get_by_slug("report", slug, published_only=not is_admin())
    if not r:
        abort(404)
    price = int(r["meta"].get("price") or 0)
    errors, form = {}, {}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in ("name", "email", "company", "licence")}
        if not form["name"]:
            errors["name"] = "Enter your full name."
        if "@" not in form["email"] or "." not in form["email"].split("@")[-1]:
            errors["email"] = "Enter a valid work email address."
        if not form["company"]:
            errors["company"] = "Enter your company name."
        lic = next((l for l in content.LICENCES if l["id"] == form["licence"]), None)
        if not lic:
            errors["licence"] = "Choose a licence type."
        if not errors:
            order = {"id": uuid.uuid4().hex[:10].upper(), "report": r["slug"], "title": r["title"],
                     "licence": lic["name"], "amount": round(price * lic["multiplier"]),
                     "name": form["name"], "email": form["email"], "company": form["company"],
                     "created": datetime.utcnow().isoformat(timespec="seconds") + "Z", "status": "pending-payment"}
            db.add_order(order)
            return redirect(url_for("order_confirmation", order_id=order["id"]))
    else:
        form = {"licence": "single"}
    related = [x for x in db.list_posts("report") if x["slug"] != slug][:3]
    return render_template("report_detail.html", r=r, price=price, body=richtext.render(r["body"]),
                           licences=content.LICENCES, errors=errors, form=form, related=related)


@app.route("/orders/<order_id>")
def order_confirmation(order_id):
    order = db.get_order(order_id)
    if not order:
        abort(404)
    return render_template("order_confirmation.html", o=order)


# ---- JSON API ---------------------------------------------------------
@app.route("/api/market")
def api_market():
    f = get_filters()
    view = request.args.get("view")
    if view not in d.DIM_ORDER:
        view = default_view(f)
    rows, total = d.breakdown(view, f)
    return jsonify({
        "filters": f, "view": view, "years": d.YEARS, "unit": "US$ bn (company view: US$ m)",
        "total": [round(v, 3) for v in total],
        "current_year": cfg.ESTIMATE_YEAR,
        "rows": [{"id": r["id"], "name": r["name"], "size_current_year": round(r["size"], 3), "share": round(r["share"], 4),
                  "cagr_history": r["cagr_hist"], "cagr_forecast": r["cagr_fc"]} for r in rows],
    })


@app.route("/api/news")
def api_news():
    items = d.filter_news(get_filters(), company=request.args.get("company"), ntype=request.args.get("type"),
                          q=request.args.get("q"))
    return jsonify({"count": len(items), "items": items[:50]})


@app.route("/api/company/<slug>")
def api_company(slug):
    if slug not in d.STORE.companies:
        abort(404)
    co = {k: v for k, v in d.STORE.companies[slug].items() if k not in ("alloc", "has_split")}
    return jsonify({"company": co, "financials": d.STORE.fin.get(slug, [])})


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


@app.errorhandler(400)
def bad_request(_):
    return render_template("404.html", bad=True), 400


# ======================================================================
# Admin
# ======================================================================
_failed = {}


def admin_password():
    return os.environ.get("ADMIN_PASSWORD") or "change-me"


def using_default_password():
    return not os.environ.get("ADMIN_PASSWORD")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        if not token or not hmac.compare_digest(token, session.get("_csrf", "")):
            abort(400)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    ip = request.remote_addr or "?"
    if request.method == "POST":
        recent = [t for t in _failed.get(ip, []) if time.time() - t < 300]
        if len(recent) >= 5:
            error = "Too many attempts. Wait a few minutes and try again."
        elif hmac.compare_digest(request.form.get("password", ""), admin_password()):
            session.clear()
            session["admin"] = True
            csrf_token()
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin_index"))
        else:
            recent.append(time.time())
            error = "That password is not right."
        _failed[ip] = recent
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin_index():
    counts = {s: len(db.list_posts(k, published_only=False)) for s, k in KIND_OF.items()}
    drafts = {s: len([p for p in db.list_posts(k, published_only=False) if p["status"] != "published"]) for s, k in KIND_OF.items()}
    users = db.list_users()
    stats = {"users": len(users), "subscribers": len([u for u in users if members.tier_of(u) == "subscriber"]),
             "mailing": len([u for u in users if u["mailing_opt_in"] and u["active"]]),
             "new_messages": len([m for m in db.list_messages() if m["status"] == "new"])}
    return render_template("admin/index.html", counts=counts, drafts=drafts, orders=len(db.list_orders()), stats=stats,
                           default_pw=using_default_password())


@app.route("/admin/<section>")
@admin_required
def admin_list(section):
    if section not in KIND_OF:
        abort(404)
    q = (request.args.get("q") or "").strip().lower()
    items = db.list_posts(KIND_OF[section], published_only=False)
    if q:
        items = [p for p in items if q in p["title"].lower()]
    page_items, page, pages = paginate(items, 20)
    return render_template("admin/list.html", section=section, label=SECTION_LABEL[section], singular=SECTION_SINGULAR[section],
                           items=page_items, total=len(items), page=page, pages=pages, q=q, params={"q": q or None})


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def parse_post_form(section, form, existing=None):
    kind = KIND_OF[section]
    errors = {}
    title = (form.get("title") or "").strip()
    summary = (form.get("summary") or "").strip()
    if not title:
        errors["title"] = "Enter a title."
    if not summary:
        errors["summary"] = "Enter a short summary. It appears on list pages."
    day = (form.get("date") or "").strip()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        errors["date"] = "Enter a date as YYYY-MM-DD."
    status = "published" if form.get("status") == "published" else "draft"
    cover = (form.get("cover") or "").strip()
    meta = dict((existing or {}).get("meta") or {})
    data = {"title": title, "summary": summary, "body": form.get("body") or "", "cover": cover, "date": day,
            "status": status, "slug": (form.get("slug") or "").strip(), "author": (form.get("author") or "").strip(),
            "tags": [], "meta": meta}
    if kind == "news":
        ntype = form.get("type") or "Market"
        if ntype not in cfg.NEWS_TYPES:
            errors["type"] = "Choose a news type."
        meta.update({"type": ntype, "source": (form.get("source") or "").strip(),
                     "impact": form.get("impact") if form.get("impact") in ("positive", "neutral", "negative") else "neutral"})
        for key, lookup in (("company", d.STORE.companies), ("country", d.COUNTRY), ("subsector", d.SUB), ("vertical", d.VERT)):
            val = (form.get(key) or "").strip()
            if val and val not in lookup:
                errors[key] = "Choose a value from the list."
                val = ""
            meta[key] = val
        data["tags"] = [ntype]
    elif kind == "paper":
        data["tags"] = [t.strip() for t in (form.get("tags") or "").split(",") if t.strip()]
        meta["takeaways"] = _lines(form.get("takeaways"))
    else:
        try:
            price = int(float((form.get("price") or "0").replace(",", "")))
            if price < 0:
                raise ValueError
        except ValueError:
            errors["price"] = "Enter a price as a whole number, for example 2450."
            price = 0
        try:
            pages = int(form.get("pages") or 0)
        except ValueError:
            pages = 0
        category = (form.get("category") or "General").strip() or "General"
        meta.update({"subtitle": (form.get("subtitle") or "").strip(), "price": price, "pages": pages,
                     "coverage": (form.get("coverage") or "").strip(), "category": category,
                     "highlights": _lines(form.get("highlights")), "toc": _lines(form.get("toc"))})
        data["tags"] = [category]
    return data, errors


def post_to_form(section, p):
    """Flatten a stored post to the values the editor shows."""
    m = p["meta"]
    f = {"title": p["title"], "summary": p["summary"], "body": p["body"], "cover": p["cover"], "date": p["date"],
         "status": p["status"], "slug": p["slug"], "author": p["author"]}
    if section == "news":
        f.update({k: m.get(k, "") for k in ("type", "source", "impact", "company", "country", "subsector", "vertical")})
    elif section == "papers":
        f["tags"] = ", ".join(p["tags"])
        f["takeaways"] = "\n".join(m.get("takeaways", []))
    else:
        f.update({k: m.get(k, "") for k in ("subtitle", "price", "pages", "coverage", "category")})
        f["highlights"] = "\n".join(m.get("highlights", []))
        f["toc"] = "\n".join(m.get("toc", []))
    return f


def _editor(section, post_id=None):
    existing = db.get(post_id) if post_id else None
    if post_id and (not existing or existing["kind"] != KIND_OF[section]):
        abort(404)
    errors = {}
    if request.method == "POST":
        data, errors = parse_post_form(section, request.form, existing)
        form = dict(request.form)
        form = {k: request.form.get(k, "") for k in request.form}
        if not errors:
            new_id = db.save(KIND_OF[section], data, post_id)
            if section == "news":
                refresh_news()
            flash("Published." if data["status"] == "published" else "Saved as draft.", "ok")
            return redirect(url_for("admin_edit", section=section, post_id=new_id))
        flash("Fix the highlighted fields and save again.", "error")
    elif existing:
        form = post_to_form(section, existing)
    else:
        form = {"date": date.today().isoformat(), "status": "published", "type": "Market", "impact": "neutral",
                "category": "General", "author": "Meridian Research" if section != "news" else ""}
    return render_template("admin/edit.html", section=section, label=SECTION_LABEL[section],
                           singular=SECTION_SINGULAR[section], form=form, errors=errors, post=existing,
                           snippets=richtext.CHART_SNIPPETS, countries=cfg.COUNTRIES, subsectors=cfg.SUBSECTORS,
                           verticals=cfg.VERTICALS)


@app.route("/admin/<section>/new", methods=["GET", "POST"])
@admin_required
def admin_new(section):
    if section not in KIND_OF:
        abort(404)
    return _editor(section)


@app.route("/admin/<section>/<int:post_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit(section, post_id):
    if section not in KIND_OF:
        abort(404)
    return _editor(section, post_id)


@app.route("/admin/<section>/<int:post_id>/delete", methods=["POST"])
@admin_required
def admin_delete(section, post_id):
    if section not in KIND_OF:
        abort(404)
    p = db.get(post_id)
    if p and p["kind"] == KIND_OF[section]:
        db.delete(post_id)
        if section == "news":
            refresh_news()
        flash(f"Deleted “{p['title']}”.", "ok")
    return redirect(url_for("admin_list", section=section))


@app.route("/admin/<section>/<int:post_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle(section, post_id):
    if section not in KIND_OF:
        abort(404)
    p = db.get(post_id)
    if p and p["kind"] == KIND_OF[section]:
        new = "draft" if p["status"] == "published" else "published"
        db.set_status(post_id, new)
        if section == "news":
            refresh_news()
        flash(("Published " if new == "published" else "Unpublished ") + f"“{p['title']}”.", "ok")
    return redirect(request.referrer or url_for("admin_list", section=section))


# ---- Uploads and preview ----------------------------------------------
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
BRAND_EXT = IMAGE_EXT | {"svg", "ico"}


def _sniff_ok(head, ext):
    if ext == "png":
        return head.startswith(b"\x89PNG")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8")
    if ext == "gif":
        return head.startswith(b"GIF8")
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == "ico":
        return head[:4] in (b"\x00\x00\x01\x00", b"\x89PNG")
    if ext == "svg":
        return b"<svg" in head.lower() or head.lstrip().startswith(b"<?xml")
    return False


def save_upload(file, allowed):
    """Validate and store an uploaded image. Returns (url, None) or (None, error)."""
    if not file or not file.filename:
        return None, "Choose an image file."
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        return None, "Use one of these file types: " + ", ".join(sorted(allowed)) + "."
    head = file.stream.read(512)
    file.stream.seek(0)
    if not _sniff_ok(head, ext):
        return None, "That file does not look like a valid ." + ext + " image."
    name = f"{uuid.uuid4().hex[:12]}.{ext}"
    file.save(os.path.join(UPLOADS, name))
    return url_for("uploads", filename=name), None


@app.route("/admin/upload", methods=["POST"])
@admin_required
def admin_upload():
    url, err = save_upload(request.files.get("file"), IMAGE_EXT)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"url": url})


@app.route("/admin/preview", methods=["POST"])
@admin_required
def admin_preview():
    return Response(richtext.render(request.form.get("body", "")), mimetype="text/html")


# ---- Settings ---------------------------------------------------------
@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    current = settings.load()
    if request.method == "POST":
        saved, problems = {}, []
        for key in ("logo", "logo_dark", "favicon"):
            f = request.files.get(key)
            if f and f.filename:
                url, err = save_upload(f, BRAND_EXT)
                if err:
                    problems.append(f"{key.replace('_', ' ').capitalize()}: {err}")
                else:
                    saved[key] = url
        new = settings.clean_settings(request.form, current, saved)
        settings.save(new)
        if problems:
            flash(" ".join(problems), "error")
        flash("Settings saved. The whole site now uses them.", "ok")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", s=current, presets=settings.PRESETS)


@app.route("/admin/orders")
@admin_required
def admin_orders():
    return render_template("admin/orders.html", orders=db.list_orders())


members.register(app, admin_required, paginate, is_admin)
datamgr.register(app, admin_required, paginate)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
