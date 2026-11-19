"""Admin screens for the dashboard's own data: taxonomy, market sizes, companies, financials and page sections."""
import csv
import io
import json
import os
import re

from flask import Response, abort, flash, redirect, render_template, request, url_for

import config as cfg
import data as d
import backup
import dataio
import db
import timeline

from db import INSTANCE
UPLOADS = os.path.join(INSTANCE, "uploads")
YEARS = cfg.YEARS
FLAG_RE = re.compile(r"^[a-z]{2}(-[a-z0-9]{2,3})?$")
MAX_CSV = 2 * 1024 * 1024
FIN_FIELDS = ["revenue", "gross_margin", "ebitda", "net_income", "capex", "employees"]


def _num(text, label, errors, key, minimum=0.0):
    try:
        v = dataio.parse_num(text)
    except ValueError:
        errors[key] = f"{label}: enter a number."
        return None
    if v is not None and minimum is not None and v < minimum:
        errors[key] = f"{label}: cannot be negative."
        return None
    return v


def _csv_text(file):
    raw = file.read(MAX_CSV + 1)
    if len(raw) > MAX_CSV:
        raise ValueError("The file is larger than 2 MB.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def _lookup(kind, text):
    """Find a country/sub-sector/vertical by name or id (ignoring case)."""
    t = (text or "").strip().casefold()
    for r in d.DIM_LOOKUP[kind].values():
        if t in (r["id"].casefold(), r["name"].casefold()):
            return r["id"]
    return None


def register(app, admin_required, paginate):
    # ------------------------------------------------------------------
    # Hub
    # ------------------------------------------------------------------
    @app.route("/admin/data")
    @admin_required
    def admin_data():
        nc, ns, nv = len(d.COUNTRY), len(d.SUB), len(d.VERT)
        stats = {"countries": nc, "subsectors": ns, "verticals": nv, "cells": len(d.STORE.market), "cells_possible": nc * ns * nv,
                 "companies": len(d.STORE.companies), "no_split": len([c for c in d.STORE.companies.values() if not c["has_split"]]),
                 "no_fin": len([s for s in d.STORE.companies if not d.STORE.fin.get(s)]),
                 "sections": len(d.SECTIONS["defs"])}
        return render_template("admin/data_index.html", stats=stats, years=YEARS, section="data")

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------
    @app.route("/admin/data/taxonomy", methods=["GET", "POST"])
    @admin_required
    def admin_taxonomy():
        if request.method == "POST":
            f = request.form
            problems, saved = [], 0
            for kind in dataio.DIM_KINDS:
                existing = list(d.DIM_LOOKUP[kind].values())
                rows, taken = [], {r["id"] for r in existing}
                for r in existing:
                    p = f"{kind}__{r['id']}__"
                    name = (f.get(p + "name") or "").strip()
                    if not name:
                        problems.append(f"A {kind} name was empty, so it was left as {r['name']}.")
                        name = r["name"]
                    row = {k: v for k, v in r.items() if k not in ("id", "name", "sort")}
                    row.update(id=r["id"], name=name[:80])
                    try:
                        row["sort"] = int(f.get(p + "sort") or 0)
                    except ValueError:
                        row["sort"] = r.get("sort", 0)
                    if kind == "country":
                        for k in ("region", "city", "exchange"):
                            row[k] = (f.get(p + k) or "").strip()[:60]
                        fl = (f.get(p + "flag") or "").strip().lower()
                        row["flag"] = fl if FLAG_RE.match(fl) else ""
                        if fl and not FLAG_RE.match(fl):
                            problems.append(f"{name}: the flag code must be like gb or us.")
                    rows.append(row)
                for i in range(3):
                    name = (f.get(f"new_{kind}_{i}_name") or "").strip()
                    if not name:
                        continue
                    nid = dataio.unique_id(name, taken)
                    taken.add(nid)
                    row = {"id": nid, "name": name[:80], "sort": 1000 + i}
                    if kind == "country":
                        fl = (f.get(f"new_{kind}_{i}_flag") or "").strip().lower()
                        row.update(region=(f.get(f"new_{kind}_{i}_region") or "").strip()[:60], city="", exchange="",
                                   flag=fl if FLAG_RE.match(fl) else "")
                    rows.append(row)
                    saved += 1
                rows.sort(key=lambda r: (r.get("sort", 0), r["name"].lower()))
                for i, r in enumerate(rows):
                    r["sort"] = i
                dataio.save_dims(kind, rows)
            for p in problems[:5]:
                flash(p, "error")
            flash("Saved." + (f" Added {saved}." if saved else ""), "ok")
            return redirect(url_for("admin_taxonomy"))
        return render_template("admin/data_taxonomy.html", kinds=[("country", "Countries", d.COUNTRY), ("subsector", "Sub-sectors", d.SUB), ("vertical", "Verticals", d.VERT)],
                               section="data")

    @app.route("/admin/data/taxonomy/<kind>/<dim_id>/delete", methods=["POST"])
    @admin_required
    def admin_taxonomy_delete(kind, dim_id):
        if kind not in dataio.DIM_KINDS or dim_id not in d.DIM_LOOKUP[kind]:
            abort(404)
        name = d.DIM_LOOKUP[kind][dim_id]["name"]
        dataio.delete_dim(kind, dim_id)
        flash(f"Deleted {name} and its market data.", "ok")
        return redirect(url_for("admin_taxonomy"))

    # ------------------------------------------------------------------
    # Page content for a country / sub-sector / vertical
    # ------------------------------------------------------------------
    def _section_inputs(entity, ent_id):
        vals = d.SECTIONS["values"].get(ent_id, {})
        return [{**s, "value": vals.get(s["id"], "")} for s in d.SECTIONS["defs"] if s["entity"] == entity]

    def _read_section_values(entity):
        return {s["id"]: (request.form.get("sec_" + s["id"]) or "")[:20000] for s in d.SECTIONS["defs"] if s["entity"] == entity}

    @app.route("/admin/data/page/<kind>/<dim_id>", methods=["GET", "POST"])
    @admin_required
    def admin_dim_page(kind, dim_id):
        if kind not in dataio.DIM_KINDS or dim_id not in d.DIM_LOOKUP[kind]:
            abort(404)
        row = d.DIM_LOOKUP[kind][dim_id]
        if request.method == "POST":
            dataio.save_values(kind, dim_id, _read_section_values(kind))
            flash("Saved.", "ok")
            return redirect(url_for("admin_dim_page", kind=kind, dim_id=dim_id))
        return render_template("admin/data_dim.html", kind=kind, row=row, inputs=_section_inputs(kind, dim_id),
                               view_url=url_for("dashboard", **{kind: dim_id}), section="data")

    # ------------------------------------------------------------------
    # Market sizing
    # ------------------------------------------------------------------
    @app.route("/admin/data/market", methods=["GET", "POST"])
    @admin_required
    def admin_market():
        if not (d.COUNTRY and d.SUB and d.VERT):
            flash("Add at least one country, sub-sector and vertical first.", "error")
            return redirect(url_for("admin_taxonomy"))
        cid = request.values.get("country")
        if cid not in d.COUNTRY:
            cid = next(iter(d.COUNTRY))
        errors, form = {}, {}
        real = request.values.get("basis") == "real"
        if request.method == "POST" and request.form.get("action") == "fill_real":
            try:
                infl = dataio.parse_num(request.form.get("infl"))
            except ValueError:
                infl = None
            if infl is None or not -20 <= infl <= 100:
                flash("Enter a price growth percentage, for example 2.5.", "error")
                return redirect(url_for("admin_market", country=cid, basis="real"))
            base = timeline.price_base()
            fill = {}
            for (c0, s0, v0), vals in d.STORE.market.items():
                if c0 == cid and (c0, s0, v0) not in d.STORE.market_real:
                    fill[(c0, s0, v0)] = [x / (1 + infl / 100.0) ** (y - base) for x, y in zip(vals, YEARS)]
            dataio.save_market({}, None, fill)
            flash(f"Filled real sizes for {len(fill)} row{'' if len(fill) == 1 else 's'} of {d.COUNTRY[cid]['name']} at {infl:g}% price growth a year. Rows that already had real sizes were left alone.", "ok")
            return redirect(url_for("admin_market", country=cid, basis="real"))
        if request.method == "POST":
            form = request.form.to_dict()
            cells, confs, n_set, n_clear = {}, {}, 0, 0
            for s in d.SUB:
                for v in d.VERT:
                    raw, bad = [], False
                    for y in YEARS:
                        key = f"m|{s}|{v}|{y}"
                        try:
                            val = dataio.parse_num(form.get(key))
                        except ValueError:
                            errors[key] = "Enter a number."
                            bad = True
                            val = None
                        if val is not None and val < 0:
                            errors[key] = "No negatives."
                            bad = True
                        raw.append(val)
                    if bad:
                        continue
                    try:
                        g = dataio.parse_num(form.get(f"g|{s}|{v}"))
                    except ValueError:
                        errors[f"g|{s}|{v}"] = "Enter a percentage."
                        continue
                    series = dataio.fill_series(raw, None if g is None else g / 100.0, len(YEARS))
                    if real:
                        if series is not None and (cid, s, v) not in d.STORE.market:
                            errors[f"m|{s}|{v}|{YEARS[0]}"] = "Enter the nominal size for this row first."
                            continue
                        if series is None and (cid, s, v) in d.STORE.market_real:
                            n_clear += 1
                        cells[(cid, s, v)] = series
                        n_set += series is not None
                    elif series is None:
                        if (cid, s, v) in d.STORE.market:
                            n_clear += 1
                        cells[(cid, s, v)] = None
                    else:
                        cells[(cid, s, v)] = series
                        confs[(cid, s, v)] = form.get(f"c|{s}|{v}") if form.get(f"c|{s}|{v}") in dataio.LEVEL else None
                        n_set += 1
            if errors:
                flash("Some values are not numbers or are not allowed. They are marked below, and nothing was saved.", "error")
            else:
                if real:
                    dataio.save_market({}, None, cells)
                else:
                    dataio.save_market(cells, confs)
                flash(f"Saved {d.COUNTRY[cid]['name']}: {n_set} row{'' if n_set == 1 else 's'} with " + ("real sizes" if real else "data") + (f", {n_clear} cleared." if n_clear else "."), "ok")
                return redirect(url_for("admin_market", country=cid, basis="real" if real else None))
        grid = []
        for s in d.SUB.values():
            for v in d.VERT.values():
                key3 = (cid, s["id"], v["id"])
                vals = (d.STORE.market_real if real else d.STORE.market).get(key3)
                nom = d.STORE.market.get(key3)
                row = {"s": s, "v": v, "cells": [], "has_nominal": nom is not None}
                if real and vals is not None and nom is not None:        # price index now, with the base year = 100
                    b = YEARS.index(timeline.price_base()) if timeline.price_base() in YEARS else 0
                    row["index"] = (nom[d.IDX2026] / vals[d.IDX2026]) / (nom[b] / vals[b]) * 100 if vals[d.IDX2026] and vals[b] and nom[b] else None
                for i, y in enumerate(YEARS):
                    key = f"m|{s['id']}|{v['id']}|{y}"
                    row["cells"].append({"key": key, "value": form[key] if key in form else ("" if vals is None else f"{vals[i]:.4g}" if vals[i] < 1 else f"{vals[i]:.1f}"), "err": errors.get(key)})
                row["gkey"] = f"g|{s['id']}|{v['id']}"
                row["g"] = form.get(row["gkey"], "")
                row["ckey"] = f"c|{s['id']}|{v['id']}"
                row["conf"] = form.get(row["ckey"], d.STORE.market_conf.get((cid, s["id"], v["id"])) or "")
                grid.append(row)
        return render_template("admin/data_market.html", config_default=cfg.CONFIDENCE_DEFAULT_MARKET, cid=cid, grid=grid, years=YEARS, section="data", errors=errors,
                               real=real, price_base=timeline.price_base(), n_real=len(d.STORE.market_real))

    @app.route("/admin/data/market.csv")
    @admin_required
    def admin_market_csv():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["country", "sub-sector", "vertical", "basis", "confidence"] + YEARS)
        for c in d.COUNTRY.values():
            for s in d.SUB.values():
                for v in d.VERT.values():
                    vals = d.STORE.market.get((c["id"], s["id"], v["id"]))
                    lvl = d.STORE.market_conf.get((c["id"], s["id"], v["id"]))
                    names = [_safe(c["name"]), _safe(s["name"]), _safe(v["name"])]
                    w.writerow(names + ["nominal", dataio.LEVEL[lvl]["name"] if lvl else ""] + ([""] * len(YEARS) if vals is None else [round(x, 3) for x in vals]))
                    rv = d.STORE.market_real.get((c["id"], s["id"], v["id"]))
                    if rv is not None:
                        w.writerow(names + ["real", ""] + [round(x, 3) for x in rv])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=market-sizes.csv"})

    @app.route("/admin/data/market/import", methods=["POST"])
    @admin_required
    def admin_market_import():
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a CSV file first.", "error")
            return redirect(url_for("admin_market"))
        try:
            rows = list(csv.reader(io.StringIO(_csv_text(f))))
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("admin_market"))
        errors, cells, confs, real_cells = [], {}, {}, {}
        if not rows:
            errors.append("The file is empty.")
        else:
            head = [h.strip().lower().replace("-", "").replace(" ", "") for h in rows[0]]
            ci = si = vi = None
            ki = head.index("confidence") if "confidence" in head else None
            bi = head.index("basis") if "basis" in head else None
            yi = {}
            try:
                ci, si, vi = head.index("country"), head.index("subsector"), head.index("vertical")
                yi = {y: head.index(str(y)) for y in YEARS if str(y) in head}
            except ValueError:
                errors.append(f"The first row must have the columns: country, sub-sector, vertical, then years such as {YEARS[0]} to {YEARS[-1]}.")
            for n, r in enumerate(rows[1:] if not errors else [], start=2):
                if not any(x.strip() for x in r):
                    continue
                if len(errors) >= 10:
                    break
                try:
                    c, s, v = _lookup("country", r[ci]), _lookup("subsector", r[si]), _lookup("vertical", r[vi])
                except IndexError:
                    errors.append(f"Row {n} is too short.")
                    continue
                if not (c and s and v):
                    errors.append(f"Row {n}: unknown {'country' if not c else 'sub-sector' if not s else 'vertical'} “{r[ci] if not c else r[si] if not s else r[vi]}”. Add it under Countries, sub-sectors and verticals first.")
                    continue
                try:
                    raw = [dataio.parse_num(r[yi[y]]) if y in yi and yi[y] < len(r) else None for y in YEARS]
                except ValueError:
                    errors.append(f"Row {n}: a year value is not a number.")
                    continue
                if any(x is not None and x < 0 for x in raw):
                    errors.append(f"Row {n}: values cannot be negative.")
                    continue
                basis = (r[bi].strip().lower() if bi is not None and bi < len(r) else "") or "nominal"
                if basis not in ("nominal", "real"):
                    errors.append(f"Row {n}: basis must be nominal or real, not “{r[bi].strip()}”.")
                    continue
                if basis == "real":
                    real_cells[(c, s, v)] = dataio.fill_series(raw, None, len(YEARS))
                    continue
                cells[(c, s, v)] = dataio.fill_series(raw, None, len(YEARS))
                if ki is not None and ki < len(r) and r[ki].strip():
                    try:
                        confs[(c, s, v)] = dataio.parse_level(r[ki])
                    except ValueError:
                        errors.append(f"Row {n}: unknown confidence “{r[ki].strip()}”. Use one of: " + ", ".join(lv["name"] for lv in dataio.LEVELS) + ".")
        for key in real_cells:
            if key not in cells and key not in d.STORE.market and len(errors) < 10:
                errors.append("A real row has no nominal size for the same country, sub-sector and vertical. Add the nominal row too.")
                break
        if errors:
            flash("Nothing was imported. " + " ".join(errors[:10]), "error")
            return redirect(url_for("admin_market"))
        if request.form.get("mode") == "replace":
            backup.auto_backup(UPLOADS, "replace-import")
            for key in list(d.STORE.market):
                cells.setdefault(key, None)
        dataio.save_market(cells, confs, real_cells)
        n = len([1 for v in cells.values() if v is not None])
        flash(f"Imported {n} market rows.", "ok")
        return redirect(url_for("admin_market"))

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------
    @app.route("/admin/data/companies")
    @admin_required
    def admin_companies():
        q = (request.args.get("q") or "").strip().lower()
        show = request.args.get("show") or ""
        rows = []
        for slug, co in d.STORE.companies.items():
            fin = d.STORE.fin.get(slug, [])
            rows.append({**co, "n_fin": len(fin), "latest": fin[-1] if fin else None})
        if q:
            rows = [r for r in rows if q in r["name"].lower() or q in (r["ticker"] or "").lower()]
        if show == "incomplete":
            rows = [r for r in rows if not r["has_split"] or not r["n_fin"]]
        rows.sort(key=lambda r: r["name"].lower())
        items, page, pages = paginate(rows, 25)
        return render_template("admin/data_companies.html", rows=items, total=len(rows), page=page, pages=pages, q=q, show=show,
                               params={"q": q or None, "show": show or None}, section="data")

    def _company_form(co, fin, fin_q=()):
        """Flat dict of string values for the company form."""
        f = {"name": co.get("name", ""), "hq": co.get("hq", ""), "city": co.get("city", ""), "ownership": co.get("ownership", "Private"),
             "ticker": co.get("ticker") or "", "exchange": co.get("exchange") or "", "website": co.get("website") or "", "founded": co.get("founded") or "",
             "market_cap": co.get("market_cap") or "", "description": co.get("description", "")}
        for dim in dataio.DIM_KINDS:
            for k, v in (co.get("alloc", {}).get(dim, {}) or {}).items():
                f[f"alloc_{dim}_{k}"] = f"{v:g}"
        for r in fin:
            f[f"fin_{r['year']}_revenue"] = f"{r['revenue']:.1f}" if r["revenue"] is not None else ""
            f[f"fin_{r['year']}_gross_margin"] = f"{r['gross_margin'] * 100:.1f}" if r.get("gross_margin") is not None else ""
            for k in ("ebitda", "net_income", "capex"):
                f[f"fin_{r['year']}_{k}"] = f"{r[k]:.1f}" if r.get(k) is not None else ""
            f[f"fin_{r['year']}_employees"] = str(r["employees"]) if r.get("employees") is not None else ""
            f[f"fin_{r['year']}_conf"] = r.get("conf_raw") or ""
        for r in fin_q:
            p = f"fq_{r['year']}_{r['quarter']}_"
            for k in ("revenue", "ebitda", "net_income", "capex"):
                f[p + k] = f"{r[k]:.1f}" if r.get(k) is not None else ""
            f[p + "conf"] = r.get("conf_raw") or ""
        return f

    def _qraw(slug):
        """The quarters actually entered for a company (the stored figures, without projected quarters)."""
        return [r for r in d.STORE.fin_q.get(slug, []) if not r["projected"]]

    def _q_slots(slug):
        """The quarters the company form covers: from two years back (or the earliest quarter with data) to the current quarter."""
        first = min([cfg.ESTIMATE_YEAR - 2] + [r["year"] for r in _qraw(slug)]) if slug else cfg.ESTIMATE_YEAR - 2
        return timeline.quarter_slots(first)

    @app.route("/admin/data/companies/new", methods=["GET", "POST"])
    @app.route("/admin/data/companies/<slug>", methods=["GET", "POST"])
    @admin_required
    def admin_company(slug=None):
        existing = d.STORE.companies.get(slug) if slug else None
        if slug and not existing:
            abort(404)
        errors, form = {}, {}
        if request.method == "POST":
            form = request.form.to_dict()
            name = (form.get("name") or "").strip()
            if not name:
                errors["name"] = "Enter the company name."
            hq = form.get("hq") or ""
            if hq and hq not in d.COUNTRY:
                errors["hq"] = "Choose a country from the list."
            website = ""
            try:
                website = dataio.clean_website(form.get("website"))
            except ValueError:
                errors["website"] = "Enter a web address such as example.com or https://example.com."
            founded = None
            if (form.get("founded") or "").strip():
                try:
                    founded = int(form["founded"].strip())
                    if not 1000 <= founded <= 2100:
                        raise ValueError
                except ValueError:
                    errors["founded"] = "Enter a year such as 1998."
            mcap = _num(form.get("market_cap"), "Market capitalisation", errors, "market_cap")
            alloc = {}
            for dim in dataio.DIM_KINDS:
                alloc[dim] = {}
                for k in d.DIM_LOOKUP[dim]:
                    key = f"alloc_{dim}_{k}"
                    v = _num(form.get(key), "Share", errors, key)
                    if v:
                        alloc[dim][k] = v
                tot = sum(alloc[dim].values())
                if tot > 0:
                    alloc[dim] = {k: round(100 * v / tot, 2) for k, v in alloc[dim].items()}
            fin_rows = []
            for y in dataio.FIN_YEARS:
                vals, any_val = {}, False
                for k in FIN_FIELDS:
                    key = f"fin_{y}_{k}"
                    txt = (form.get(key) or "").strip()
                    if txt:
                        any_val = True
                    v = _num(txt, f"{y} {k.replace('_', ' ')}", errors, key, minimum=(None if k in ("ebitda", "net_income") else 0.0))
                    vals[k] = v
                if any_val:
                    if vals["revenue"] is None and f"fin_{y}_revenue" not in errors:
                        errors[f"fin_{y}_revenue"] = f"Enter revenue for {y}, or clear the row."
                    if vals["gross_margin"] is not None:
                        vals["gross_margin"] = vals["gross_margin"] / 100.0
                    if vals["employees"] is not None:
                        vals["employees"] = int(vals["employees"])
                    lvl = form.get(f"fin_{y}_conf")
                    fin_rows.append({"year": y, **vals, "conf": lvl if lvl in dataio.LEVEL else None})
            q_rows, q_slots = [], _q_slots(slug)
            for y, q in q_slots:
                vals, any_val, p = {}, False, f"fq_{y}_{q}_"
                for k in ("revenue", "ebitda", "net_income", "capex"):
                    txt = (form.get(p + k) or "").strip()
                    any_val = any_val or bool(txt)
                    vals[k] = _num(txt, f"{timeline.qlabel(y, q)} {k.replace('_', ' ')}", errors, p + k, minimum=(None if k in ("ebitda", "net_income") else 0.0))
                if any_val:
                    if vals["revenue"] is None and p + "revenue" not in errors:
                        errors[p + "revenue"] = f"Enter revenue for {timeline.qlabel(y, q)}, or clear the row."
                    lvl = form.get(p + "conf")
                    q_rows.append({"year": y, "quarter": q, **vals, "conf": lvl if lvl in dataio.LEVEL else None})
            prods, seen = [], set()
            try:
                n_prod = min(int(form.get("prod_n") or 0), 30)
            except ValueError:
                n_prod = 0
            for i in range(n_prod):
                pname = (form.get(f"prod_{i}_name") or "").strip()[:80]
                unit = (form.get(f"prod_{i}_unit") or "").strip()[:30]
                vols = {}
                for y in dataio.FIN_YEARS:
                    key = f"prod_{i}_{y}"
                    v = _num((form.get(key) or "").strip(), f"{pname or 'product'} volume {y}", errors, key, minimum=0.0)
                    if v is not None:
                        vols[y] = v
                if not (pname or unit or vols):
                    continue
                if not pname:
                    errors[f"prod_{i}_name"] = "Give the product a name, or clear the row."
                elif pname.lower() in seen:
                    errors[f"prod_{i}_name"] = f"“{pname}” is listed twice."
                seen.add(pname.lower())
                prods.append({"name": pname, "unit": unit, "vols": vols})
            own = (form.get("ownership") or "").strip()
            if own not in dataio.OWNERSHIP and own != (existing or {}).get("ownership"):
                own = dataio.OWNERSHIP[1]       # only the listed choices (or what the company already had) are accepted
            if not errors:
                is_new = existing is None
                taken = set(d.STORE.companies)
                slug = slug or dataio.unique_id(name, taken)
                data = {"hq": hq, "city": (form.get("city") or "").strip()[:80], "ownership": own,
                        "website": website, "ticker": (form.get("ticker") or "").strip()[:12], "exchange": (form.get("exchange") or "").strip()[:20],
                        "founded": founded, "market_cap": mcap, "description": (form.get("description") or "").strip()[:5000], "alloc": alloc}
                dataio.save_company(slug, name[:120], data)
                dataio.save_fin(slug, fin_rows, clear=dataio.FIN_YEARS)
                dataio.save_fin_q(slug, q_rows, clear=q_slots)
                dataio.save_products(slug, prods, window=set(dataio.FIN_YEARS))
                dataio.save_values("company", slug, _read_section_values("company"))
                flash(("Added " if is_new else "Saved ") + name + ".", "ok")
                return redirect(url_for("admin_company", slug=slug))
            flash("Some fields need attention. They are marked below, and nothing was saved.", "error")
        if not form:
            form = _company_form(existing or {}, d.STORE.fin_raw.get(slug, []) if existing else [], _qraw(slug) if existing else [])
            old = dataio.load_products().get(slug, []) if existing else []
            form["prod_n"] = str(len(old) + 1)
            for i, p in enumerate(old):
                form[f"prod_{i}_name"], form[f"prod_{i}_unit"] = p["name"], p["unit"]
                for y in dataio.FIN_YEARS:
                    if y in p["vols"]:
                        form[f"prod_{i}_{y}"] = f"{p['vols'][y]:g}"
        inputs = _section_inputs("company", slug) if slug else [{**s, "value": ""} for s in d.SECTIONS["defs"] if s["entity"] == "company"]
        if request.method == "POST":
            for i in inputs:
                i["value"] = form.get("sec_" + i["id"], "")
        sums = {dim: round(sum(float(form.get(f"alloc_{dim}_{k}") or 0) if re.match(r"^[0-9.]+$", form.get(f"alloc_{dim}_{k}") or "") else 0 for k in d.DIM_LOOKUP[dim]), 1) for dim in dataio.DIM_KINDS}
        return render_template("admin/data_company.html", co=existing, form=form, errors=errors, inputs=inputs, fin_years=dataio.FIN_YEARS,
                               ownership=dataio.OWNERSHIP, sums=sums, units=dataio.known_units(), prod_err=any(k.startswith("prod_") for k in errors),
                               n_prod=max(int(form.get("prod_n") or 1), 1) if str(form.get("prod_n") or "1").isdigit() else 1, last_actual=cfg.LAST_ACTUAL, section="data",
                               q_slots=[{"y": y, "q": q, "label": timeline.qlabel(y, q), "status": timeline.quarter_status(y, q)} for y, q in _q_slots(slug)],
                               q_years={r["year"] for r in _qraw(slug)} if existing else set(),
                               has_q=bool(existing and _qraw(slug)), q_has_err=any(k.startswith("fq_") for k in errors))

    @app.route("/admin/data/companies/<slug>/delete", methods=["POST"])
    @admin_required
    def admin_company_delete(slug):
        co = d.STORE.companies.get(slug)
        if not co:
            abort(404)
        dataio.delete_company(slug)
        flash(f"Deleted {co['name']}.", "ok")
        return redirect(url_for("admin_companies"))

    @app.route("/admin/data/volumes.csv")
    @admin_required
    def admin_volumes_csv():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["company", "product", "unit"] + list(dataio.FIN_YEARS))
        for slug, items in dataio.load_products().items():
            co = d.STORE.companies.get(slug)
            for p in items:
                if co:
                    w.writerow([_safe(co["name"]), _safe(p["name"]), _safe(p["unit"])] + [p["vols"].get(y, "") for y in dataio.FIN_YEARS])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=company-volumes.csv"})

    @app.route("/admin/data/volumes/import", methods=["POST"])
    @admin_required
    def admin_volumes_import():
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a CSV file first.", "error")
            return redirect(url_for("admin_companies"))
        try:
            rows = list(csv.reader(io.StringIO(_csv_text(f))))
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("admin_companies"))
        head = [h.strip().lower() for h in rows[0]] if rows else []
        errors, upd = [], {}
        if any(h not in head for h in ("company", "product", "unit")):
            errors.append("The first row must have the columns company, product and unit, then years such as " + f"{dataio.FIN_YEARS[0]} to {dataio.FIN_YEARS[-1]}.")
        else:
            col = {h: i for i, h in enumerate(head)}
            ycols = {y: col[str(y)] for y in dataio.FIN_YEARS if str(y) in col}
            by_name = {c["name"].casefold(): s for s, c in d.STORE.companies.items()}
            for n, r in enumerate(rows[1:], start=2):
                if not any(x.strip() for x in r) or len(errors) >= 10:
                    continue
                get = lambda k: r[col[k]].strip() if col[k] < len(r) else ""
                key = get("company").casefold()
                slug = key if key in d.STORE.companies else by_name.get(key)
                if not slug:
                    errors.append(f"Row {n}: company “{get('company')}” does not exist. Add it under Companies first.")
                    continue
                if not get("product"):
                    errors.append(f"Row {n}: the product name is empty.")
                    continue
                try:
                    vols = {y: dataio.parse_num(r[i]) for y, i in ycols.items() if i < len(r)}
                except ValueError:
                    errors.append(f"Row {n}: a volume is not a number.")
                    continue
                if any(v is not None and v < 0 for v in vols.values()):
                    errors.append(f"Row {n}: volumes cannot be negative.")
                    continue
                upd.setdefault(slug, []).append({"name": get("product")[:80], "unit": get("unit")[:30], "vols": {y: v for y, v in vols.items() if v is not None}})
        if errors:
            flash("Nothing was imported. " + " ".join(errors[:10]), "error")
            return redirect(url_for("admin_companies"))
        existing = dataio.load_products()
        n = 0
        for slug, items in upd.items():
            cur = {p["name"].lower(): p for p in existing.get(slug, [])}
            for it in items:
                p = cur.get(it["name"].lower())
                if p:
                    p["unit"] = it["unit"] or p["unit"]
                    p["vols"].update(it["vols"])
                else:
                    cur[it["name"].lower()] = {"name": it["name"], "unit": it["unit"], "vols": it["vols"]}
                n += 1
            dataio.save_products(slug, list(cur.values()))
        flash(f"Imported {n} product row{'' if n == 1 else 's'} for {len(upd)} compan{'y' if len(upd) == 1 else 'ies'}.", "ok")
        return redirect(url_for("admin_companies"))

    @app.route("/admin/data/financials.csv")
    @admin_required
    def admin_fin_csv():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["company", "year", "quarter", "revenue", "gross_margin_pct", "ebitda", "net_income", "capex", "employees", "confidence"])
        num = lambda v: "" if v is None else round(v, 1)
        for slug, co in sorted(d.STORE.companies.items(), key=lambda kv: kv[1]["name"].lower()):
            for r in d.STORE.fin_raw.get(slug, []):
                w.writerow([_safe(co["name"]), r["year"], "", num(r["revenue"]), "" if r["gross_margin"] is None else round(r["gross_margin"] * 100, 1),
                            num(r["ebitda"]), num(r["net_income"]), num(r["capex"]), "" if r["employees"] is None else r["employees"],
                            dataio.LEVEL[r["conf_raw"] or dataio.fin_default_conf(r["year"])]["name"]])
            for r in [x for x in d.STORE.fin_q.get(slug, []) if not x["projected"]]:
                w.writerow([_safe(co["name"]), r["year"], r["quarter"], num(r["revenue"]), "", num(r["ebitda"]), num(r["net_income"]), num(r["capex"]), "",
                            dataio.LEVEL[r["conf"]]["name"]])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=company-financials.csv"})

    @app.route("/admin/data/financials/import", methods=["POST"])
    @admin_required
    def admin_fin_import():
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a CSV file first.", "error")
            return redirect(url_for("admin_companies"))
        try:
            rows = list(csv.reader(io.StringIO(_csv_text(f))))
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("admin_companies"))
        errors, by_co, by_co_q = [], {}, {}
        head = [h.strip().lower() for h in rows[0]] if rows else []
        need = ["company", "year", "revenue"]
        if not rows or any(h not in head for h in need):
            errors.append("The first row must include the columns company, year and revenue. Optional: quarter (1 to 4, blank for a full year), gross_margin_pct, ebitda, net_income, capex, employees, confidence.")
        else:
            col = {h: head.index(h) for h in head}
            by_name, dupes = {}, set()
            for s_, c_ in d.STORE.companies.items():
                k_ = c_["name"].casefold()
                if k_ in by_name:
                    dupes.add(k_)
                by_name[k_] = s_
            for n, r in enumerate(rows[1:], start=2):
                if not any(x.strip() for x in r) or len(errors) >= 10:
                    continue
                get = lambda k: (r[col[k]] if k in col and col[k] < len(r) else "")
                key = get("company").strip().casefold()
                slug = key if key in d.STORE.companies else by_name.get(key)
                if slug != key and key in dupes:
                    errors.append(f"Row {n}: more than one company is called “{get('company').strip()}”. Use its id instead (see the web address of its edit page).")
                    continue
                if not slug:
                    errors.append(f"Row {n}: company “{get('company').strip()}” does not exist. Add it under Companies first.")
                    continue
                try:
                    year = int(float(get("year")))
                    vals = {"year": year, "revenue": dataio.parse_num(get("revenue")), "gross_margin": dataio.parse_num(get("gross_margin_pct")),
                            "ebitda": dataio.parse_num(get("ebitda")), "net_income": dataio.parse_num(get("net_income")),
                            "capex": dataio.parse_num(get("capex")), "employees": dataio.parse_num(get("employees"))}
                except ValueError:
                    errors.append(f"Row {n}: a value is not a number.")
                    continue
                if year not in dataio.FIN_YEARS:
                    errors.append(f"Row {n}: year must be between {dataio.FIN_YEARS[0]} and {dataio.FIN_YEARS[-1]}.")
                    continue
                quarter = None
                if get("quarter").strip():
                    try:
                        quarter = int(float(get("quarter")))
                        if not 1 <= quarter <= 4:
                            raise ValueError
                    except ValueError:
                        errors.append(f"Row {n}: quarter must be 1, 2, 3 or 4, or blank for a full year.")
                        continue
                    if timeline.qkey(year, quarter) > timeline.qkey(cfg.ESTIMATE_YEAR, timeline.CURRENT["q"]):
                        errors.append(f"Row {n}: {timeline.qlabel(year, quarter)} is after the current quarter ({timeline.qlabel(cfg.ESTIMATE_YEAR, timeline.CURRENT['q'])}).")
                        continue
                if vals["revenue"] is None or vals["revenue"] < 0:
                    errors.append(f"Row {n}: revenue is required and cannot be negative.")
                    continue
                if vals["gross_margin"] is not None:
                    vals["gross_margin"] /= 100.0
                if vals["employees"] is not None:
                    vals["employees"] = int(vals["employees"])
                if get("confidence").strip():
                    try:
                        vals["conf"] = dataio.parse_level(get("confidence"))
                    except ValueError:
                        errors.append(f"Row {n}: unknown confidence “{get('confidence').strip()}”. Use one of: " + ", ".join(lv["name"] for lv in dataio.LEVELS) + ".")
                        continue
                if quarter is not None:
                    qv = {k: vals[k] for k in ("year", "revenue", "ebitda", "net_income", "capex")}
                    qv["quarter"] = quarter
                    if "conf" in vals:
                        qv["conf"] = vals["conf"]
                    by_co_q.setdefault(slug, []).append(qv)
                else:
                    by_co.setdefault(slug, []).append(vals)
        if errors:
            flash("Nothing was imported. " + " ".join(errors), "error")
            return redirect(url_for("admin_companies"))
        for slug, rows_ in by_co.items():
            dataio.save_fin(slug, rows_, replace=False)
        for slug, rows_ in by_co_q.items():
            dataio.save_fin_q(slug, rows_, replace=False)
        n_rows = sum(len(v) for v in by_co.values()) + sum(len(v) for v in by_co_q.values())
        flash(f"Imported {n_rows} financial rows for {len(set(by_co) | set(by_co_q))} companies.", "ok")
        return redirect(url_for("admin_companies"))

    # ------------------------------------------------------------------
    # Page sections
    # ------------------------------------------------------------------
    @app.route("/admin/data/sections", methods=["GET", "POST"])
    @admin_required
    def admin_sections():
        if request.method == "POST":
            f = request.form
            kinds = {k for k, _, _ in dataio.KINDS}
            with db.conn() as c:
                taken = {r["id"] for r in c.execute("SELECT id FROM sections")}
                for s in d.SECTIONS["defs"]:
                    p = f"s_{s['id']}_"
                    if p + "title" not in f:
                        continue
                    title = (f.get(p + "title") or "").strip() or s["title"]
                    kind = f.get(p + "kind") if f.get(p + "kind") in kinds else s["kind"]
                    pos = "bottom" if f.get(p + "position") == "bottom" else "top"
                    try:
                        sort = int(f.get(p + "sort") or 0)
                    except ValueError:
                        sort = s["sort"]
                    c.execute("UPDATE sections SET title=?, kind=?, position=?, sort=?, visible=? WHERE id=?",
                              (title[:80], kind, pos, sort, 1 if f.get(p + "visible") else 0, s["id"]))
                added = 0
                for ent, _ in dataio.ENTITIES:
                    for i in range(2):
                        title = (f.get(f"new_{ent}_{i}_title") or "").strip()
                        if not title:
                            continue
                        kind = f.get(f"new_{ent}_{i}_kind") if f.get(f"new_{ent}_{i}_kind") in kinds else "text"
                        sid = dataio.unique_id(f"{ent}-{title}", taken)
                        taken.add(sid)
                        c.execute("INSERT INTO sections (id, entity, title, kind, position, sort, visible) VALUES (?,?,?,?,?,?,1)",
                                  (sid, ent, title[:80], kind, "top", 100 + i))
                        added += 1
                db.bump(c)
            hidden = [f"{page}.{bid}" for page, blocks in dataio.BLOCKS.items() for bid, _ in blocks if not f.get(f"show_{page}.{bid}")]
            db.set_meta("hidden_blocks", json.dumps(hidden))
            db.bump()
            flash("Saved." + (f" Added {added} section{'' if added == 1 else 's'}." if added else ""), "ok")
            return redirect(url_for("admin_sections"))
        groups = [(ent, label, [s for s in d.SECTIONS["defs"] if s["entity"] == ent]) for ent, label in dataio.ENTITIES]
        return render_template("admin/data_sections.html", groups=groups, kinds=dataio.KINDS, blocks=dataio.BLOCKS, hidden=dataio.hidden_blocks(),
                               section="data")

    @app.route("/admin/data/sections/<sid>/delete", methods=["POST"])
    @admin_required
    def admin_section_delete(sid):
        with db.conn() as c:
            c.execute("DELETE FROM sections WHERE id=?", (sid,))
            c.execute("DELETE FROM section_values WHERE section_id=?", (sid,))
            db.bump(c)
        flash("Section deleted, along with what was entered in it.", "ok")
        return redirect(url_for("admin_sections"))

    @app.route("/admin/data/notice", methods=["POST"])
    @admin_required
    def admin_data_notice():
        db.set_meta("sample_notice", "1" if request.form.get("show") else "0")
        flash("Saved.", "ok")
        return redirect(url_for("admin_data"))

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------
    @app.route("/admin/data/timeline", methods=["GET", "POST"])
    @admin_required
    def admin_timeline():
        t = timeline.load()
        if request.method == "POST":
            action = request.form.get("action")
            new = dict(t)
            if action in ("advance_q", "advance_y"):
                new = timeline.advance(t, 1 if action == "advance_q" else 4)
                done = f"The dashboard is now as of {timeline.describe(new)['as_of']}."
            elif action == "report_year":
                new["last_actual_year"] = min(t["last_actual_year"] + 1, t["current_year"])
                done = f"Annual data now counts as reported up to {new['last_actual_year']}."
            elif action == "report_quarter":
                y, q = t["last_actual_q"]
                y, q = (y + 1, 1) if q == 4 else (y, q + 1)
                new["last_actual_q"] = [y, q]
                done = f"Company quarters now count as reported up to {timeline.qlabel(y, q)}."
            elif action == "price_base":
                new["price_base"] = request.form.get("price_base") or None
                done = "Price year saved."
            elif action == "save":
                try:
                    new = {**t, **{k: int(request.form[k]) for k in ("first_year", "last_year", "current_year", "current_quarter", "last_actual_year")},
                           "last_actual_q": [int(request.form["laq_year"]), int(request.form["laq_quarter"])],
                           "price_base": request.form.get("price_base") or None}
                except (KeyError, ValueError):
                    flash("Enter whole numbers for the years and quarters.", "error")
                    return redirect(url_for("admin_timeline"))
                done = "Timeline saved."
            else:
                abort(400)
            clean, errors = timeline.clean(new)
            if errors:
                flash(" ".join(errors) + " Nothing was changed.", "error")
            elif new == t:
                flash("Nothing to change.", "ok")
            else:
                timeline.save(clean)
                flash(done, "ok")
            return redirect(url_for("admin_timeline"))
        cy = t["current_year"]
        missing = [c for s, c in d.STORE.companies.items() if c["has_split"] and not any(r["year"] == cy and not r.get("extrapolated") and r.get("q_reported") != 0 for r in d.STORE.fin.get(s, []))]
        return render_template("admin/data_timeline.html", t=t, info=timeline.describe(t), missing=len(missing), n_companies=len(d.STORE.companies),
                               nxt=timeline.describe(timeline.advance(t, 1)), nxt_y=timeline.describe(timeline.advance(t, 4)), section="data")
