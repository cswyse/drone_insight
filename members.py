"""
Accounts, tiers, mailing list, legal pages, contact and pricing enquiries.

Tiers
    free        any signed-in account: full white papers
    subscriber  free + market dashboard, company profiles and every report's file
Admins (signed in at /admin) can see everything.
Subscriptions are managed by hand in Admin > Users: set the tier, and optionally an end date.
"""
import csv
import io
import os
import re
import time
import uuid
from datetime import date
from functools import wraps

from flask import (Response, abort, flash, g, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import mailer
import richtext
import settings

ROOT = os.path.dirname(os.path.abspath(__file__))
PRIVATE = os.path.join(ROOT, "instance", "private")
os.makedirs(PRIVATE, exist_ok=True)
EMAIL_RE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")
MIN_PW = 10
TOPICS = ["Subscription", "Buying a single report", "Request a demo", "Team or company licence", "Something else"]
_hits = {}                       # rate limiting: key -> [timestamps]
_DUMMY = generate_password_hash("not-a-real-password")


def _limited(key, limit, window):
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = recent
    return len(recent) >= limit


def _hit(key):
    _hits.setdefault(key, []).append(time.time())


def safe_next(nxt, default):
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else default


def tier_of(u):
    """'subscriber' or 'free' for an account, taking the optional end date into account."""
    if u and u["tier"] == "subscriber" and (not u["subscription_until"] or u["subscription_until"] >= date.today().isoformat()):
        return "subscriber"
    return "free"


def csv_cell(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def register(app, admin_required, paginate, is_admin):
    # ------------------------------------------------------------------
    # Who is signed in
    # ------------------------------------------------------------------
    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            u = db.get_user(uid)
            if u and u["active"]:
                g.user = u
            else:
                session.pop("uid", None)

    def level():
        if is_admin():
            return "admin"
        u = getattr(g, "user", None)
        return tier_of(u) if u else None

    def can(feature):
        lv = level()
        if feature == "member":
            return lv is not None
        return lv in ("admin", "subscriber")

    @app.context_processor
    def inject_user():
        lv = level()
        return {"user": getattr(g, "user", None), "level": lv, "is_member": lv is not None, "is_subscriber": lv in ("admin", "subscriber"),
                "contact_email": settings.load()["contact"]["email"], "legal": settings.load()["legal"]}

    def gate_response(need, api=False):
        if api:
            return jsonify({"error": "Sign in with a subscriber account to use this."}), (401 if not g.user else 403)
        return render_template("gate.html", need=need, next=request.full_path.rstrip("?")), (401 if not g.user else 403)

    def subscribers_only(fn, api=False):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not can("subscriber"):
                return gate_response("subscriber", api)
            return fn(*a, **kw)
        return wrapper

    for ep, api in (("dashboard", False), ("dashboard_export", False), ("company", False), ("api_market", True), ("api_company", True)):
        app.view_functions[ep] = subscribers_only(app.view_functions[ep], api)

    # ------------------------------------------------------------------
    # Sign up, sign in, sign out
    # ------------------------------------------------------------------
    def start_session(u):
        session.clear()
        session["uid"] = u["id"]
        session.permanent = False
        db.update_user(u["id"], last_login=db._now())

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        nxt = safe_next(request.values.get("next"), "")
        if g.user:
            return redirect(nxt or url_for("account"))
        errors, form = {}, {}
        if request.method == "POST":
            form = {k: (request.form.get(k) or "").strip() for k in ("name", "email", "company")}
            pw = request.form.get("password") or ""
            ip = request.remote_addr or "?"
            if request.form.get("website"):                    # honeypot: real people leave this empty
                return redirect(url_for("home"))
            if _limited("signup:" + ip, 8, 3600):
                errors["form"] = "Too many sign-ups from this connection. Try again later."
            if not form["name"]:
                errors["name"] = "Enter your full name."
            if not EMAIL_RE.match(form["email"]) or len(form["email"]) > 200:
                errors["email"] = "Enter a valid email address."
            elif db.get_user_by_email(form["email"]):
                errors["email"] = "An account with this email already exists. Sign in instead."
            if len(pw) < MIN_PW:
                errors["password"] = f"Use at least {MIN_PW} characters."
            elif len(pw) > 128:
                errors["password"] = "Use 128 characters or fewer."
            elif pw.lower() == form["email"].lower():
                errors["password"] = "Choose a password that is different from your email."
            if not request.form.get("terms"):
                errors["terms"] = "Agree to the Terms and Conditions and Privacy Policy to create an account."
            form["mailing"] = bool(request.form.get("mailing"))
            if not errors:
                _hit("signup:" + ip)
                uid = db.add_user(form["email"], form["name"][:120], form["company"][:120], generate_password_hash(pw),
                                  form["mailing"], settings.load()["legal"]["version"])
                start_session(db.get_user(uid))
                flash("Your account is ready.", "ok")
                return redirect(nxt or url_for("account"))
        return render_template("auth/signup.html", errors=errors, form=form, next=nxt)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        nxt = safe_next(request.values.get("next"), "")
        if g.user:
            return redirect(nxt or url_for("account"))
        error, email = None, ""
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            ip = request.remote_addr or "?"
            if _limited("login:" + ip, 20, 300) or _limited("login:" + email, 5, 300):
                error = "Too many attempts. Wait a few minutes and try again."
            else:
                u = db.get_user_by_email(email)
                ok = check_password_hash(u["pw_hash"] if u else _DUMMY, request.form.get("password") or "")
                if u and ok and not u["active"]:
                    error = "This account has been disabled. Contact us if you think that is a mistake."
                elif u and ok:
                    start_session(u)
                    if u["must_change_pw"]:
                        flash("Choose a new password to continue.", "ok")
                        return redirect(url_for("account_password"))
                    return redirect(nxt or url_for("account"))
                else:
                    _hit("login:" + ip)
                    _hit("login:" + email)
                    error = "That email and password do not match."
        return render_template("auth/login.html", error=error, email=email, next=nxt)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("home"))

    def member_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("login", next=request.path))
            return fn(*a, **kw)
        return wrapper

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    @app.route("/account", methods=["GET", "POST"])
    @member_required
    def account():
        errors = {}
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            if not name:
                errors["name"] = "Enter your full name."
            else:
                opt = bool(request.form.get("mailing"))
                fields = {"name": name[:120], "company": (request.form.get("company") or "").strip()[:120]}
                if opt != bool(g.user["mailing_opt_in"]):
                    fields.update(mailing_opt_in=int(opt), mailing_opt_in_at=db._now() if opt else "")
                db.update_user(g.user["id"], **fields)
                flash("Saved.", "ok")
                return redirect(url_for("account"))
        return render_template("auth/account.html", errors=errors, tier=tier_of(g.user), pw_changed=request.args.get("pw"))

    @app.route("/account/password", methods=["GET", "POST"])
    @member_required
    def account_password():
        error = None
        if request.method == "POST":
            new = request.form.get("new") or ""
            if _limited("pw:%s" % g.user["id"], 5, 300):
                error = "Too many attempts. Wait a few minutes and try again."
            elif not check_password_hash(g.user["pw_hash"], request.form.get("current") or ""):
                _hit("pw:%s" % g.user["id"])
                error = "Your current password is not right."
            elif len(new) < MIN_PW or len(new) > 128:
                error = f"Use between {MIN_PW} and 128 characters for the new password."
            else:
                db.update_user(g.user["id"], pw_hash=generate_password_hash(new), must_change_pw=0)
                flash("Password changed.", "ok")
                return redirect(url_for("account"))
        return render_template("auth/password.html", error=error, forced=bool(g.user["must_change_pw"]))

    @app.route("/account/delete", methods=["POST"])
    @member_required
    def account_delete():
        if not check_password_hash(g.user["pw_hash"], request.form.get("password") or ""):
            flash("Your password is not right, so the account was not deleted.", "error")
            return redirect(url_for("account"))
        db.delete_user(g.user["id"])
        session.clear()
        flash("Your account and personal details have been deleted.", "ok")
        return redirect(url_for("home"))

    # ------------------------------------------------------------------
    # Legal pages (edit the text in legal/*.md)
    # ------------------------------------------------------------------
    def legal_page(name, title):
        with open(os.path.join(ROOT, "legal", name + ".md"), encoding="utf-8") as fh:
            text = fh.read()
        s = settings.load()
        text = text.replace("{{site}}", s["brand"]["name"]).replace("{{email}}", s["contact"]["email"] or "the contact form on our website")
        return render_template("legal.html", title=title, body=richtext.render(text))

    @app.route("/terms")
    def terms():
        return legal_page("terms", "Terms and Conditions")

    @app.route("/privacy")
    def privacy():
        return legal_page("privacy", "Privacy Policy")

    # ------------------------------------------------------------------
    # Contact and pricing forms
    # ------------------------------------------------------------------
    def enquiry(kind, template):
        s = settings.load()
        errors, form = {}, {}
        if request.method == "POST":
            form = {k: (request.form.get(k) or "").strip() for k in ("name", "email", "company", "topic", "subject", "message")}
            ip = request.remote_addr or "?"
            if request.form.get("website"):                    # honeypot
                return redirect(url_for(kind))
            if _limited("msg:" + ip, 5, 3600):
                errors["form"] = "You have sent several messages recently. Please try again later."
            if not form["name"]:
                errors["name"] = "Enter your name."
            if not EMAIL_RE.match(form["email"]):
                errors["email"] = "Enter a valid email address so we can reply."
            if kind == "pricing" and form["topic"] not in TOPICS:
                errors["topic"] = "Choose what you are interested in."
            if kind == "contact" and not form["subject"]:
                errors["subject"] = "Enter a subject."
            if not form["message"] and kind == "contact":
                errors["message"] = "Write a message."
            if len(form["message"]) > 5000:
                errors["message"] = "Keep the message under 5,000 characters."
            if not errors:
                _hit("msg:" + ip)
                m = {"kind": kind, "name": form["name"][:120], "email": form["email"][:200], "company": form["company"][:120],
                     "topic": form["topic"], "subject": form["subject"][:200], "message": form["message"],
                     "user_id": g.user["id"] if g.user else None}
                mid = db.add_message(m)
                head = "Pricing enquiry: " + m["topic"] if kind == "pricing" else "Contact: " + m["subject"]
                body = (f"{head}\n\nFrom: {m['name']} <{m['email']}>\nCompany: {m['company'] or '-'}\n"
                        f"Account: {'yes, ' + tier_of(g.user) if g.user else 'no'}\n\n{m['message'] or '(no message)'}\n")
                mailer.notify(mid, s["contact"]["email"], f"[{s['brand']['name']}] {head}", body, m["email"])
                flash("Thanks. We have your message and will reply to " + m["email"] + ".", "ok")
                return redirect(url_for(kind) + "#sent")
        elif g.user:
            form = {"name": g.user["name"], "email": g.user["email"], "company": g.user["company"]}
        if request.method == "GET" and kind == "pricing" and request.args.get("topic") in TOPICS:
            form["topic"] = request.args["topic"]
        if request.method == "GET" and kind == "contact":
            form["subject"] = (request.args.get("subject") or "")[:200]
        return render_template(template, errors=errors, form=form, topics=TOPICS, pricing=s["pricing"])

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        return enquiry("contact", "contact.html")

    @app.route("/pricing", methods=["GET", "POST"])
    def pricing():
        return enquiry("pricing", "pricing.html")

    # ------------------------------------------------------------------
    # Report files (subscribers only; stored outside the public uploads folder)
    # ------------------------------------------------------------------
    DATA_EXT = {"csv", "xlsx", "xls"}

    def _data_ok(head, ext):
        if ext == "xlsx":
            return head.startswith(b"PK\x03\x04")
        if ext == "xls":
            return head.startswith(b"\xd0\xcf\x11\xe0")
        return b"\x00" not in head                       # csv: plain text

    @app.route("/reports/<slug>/download")
    @app.route("/reports/<slug>/download/<which>")
    def report_download(slug, which="pdf"):
        r = db.get_by_slug("report", slug, published_only=not is_admin())
        key = "data_file" if which == "data" else "file"
        if which not in ("pdf", "data") or not r or not r["meta"].get(key):
            abort(404)
        if not can("subscriber"):
            return gate_response("subscriber")
        name = os.path.basename(r["meta"][key])
        if which == "data":
            ext = name.rsplit(".", 1)[-1]
            return send_from_directory(PRIVATE, name, as_attachment=True, download_name=f"{r['slug']}-data.{ext}")
        return send_from_directory(PRIVATE, name, as_attachment=True, download_name=f"{r['slug']}.pdf", mimetype="application/pdf")

    @app.route("/admin/reports/<int:post_id>/file", methods=["POST"])
    @app.route("/admin/reports/<int:post_id>/file/<which>", methods=["POST"])
    @admin_required
    def admin_report_file(post_id, which="pdf"):
        """Attach, replace or remove a report's PDF (which=pdf) or data file (which=data: csv, xlsx or xls)."""
        p = db.get(post_id)
        if not p or p["kind"] != "report" or which not in ("pdf", "data"):
            abort(404)
        key, label = ("data_file", "Data file") if which == "data" else ("file", "PDF")
        back = redirect(url_for("admin_edit", section="reports", post_id=post_id))
        meta = dict(p["meta"])

        def drop():
            if meta.get(key):
                try:
                    os.remove(os.path.join(PRIVATE, os.path.basename(meta[key])))
                except OSError:
                    pass
                meta.pop(key, None)

        if request.form.get("remove"):
            drop()
            flash(f"{label} removed.", "ok")
        else:
            f = request.files.get("file")
            head = f.stream.read(8) if f and f.filename else b""
            if f:
                f.stream.seek(0)
            if which == "pdf":
                ext, good = "pdf", head.startswith(b"%PDF")
            else:
                ext = f.filename.rsplit(".", 1)[-1].lower() if f and "." in (f.filename or "") else ""
                good = ext in DATA_EXT and _data_ok(head, ext)
            if not good:
                flash("Choose a PDF file." if which == "pdf" else "Choose an Excel (.xlsx, .xls) or CSV file.", "error")
                return back
            drop()
            name = uuid.uuid4().hex + "." + ext
            f.save(os.path.join(PRIVATE, name))
            meta[key] = name
            flash(f"{label} uploaded. Subscribers can now download it.", "ok")
        p["meta"] = meta
        db.save("report", p, post_id)
        return back

    # ------------------------------------------------------------------
    # Admin: users, mailing list, messages
    # ------------------------------------------------------------------
    @app.route("/admin/users")
    @admin_required
    def admin_users():
        q = (request.args.get("q") or "").strip().lower()
        flt = request.args.get("show") or ""
        users = db.list_users()
        for u in users:
            u["eff"] = tier_of(u)
        if q:
            users = [u for u in users if q in u["email"].lower() or q in u["name"].lower() or q in u["company"].lower()]
        if flt == "subscribers":
            users = [u for u in users if u["eff"] == "subscriber"]
        elif flt == "free":
            users = [u for u in users if u["eff"] == "free"]
        elif flt == "mailing":
            users = [u for u in users if u["mailing_opt_in"]]
        items, page, pages = paginate(users, 25)
        return render_template("admin/users.html", users=items, total=len(users), page=page, pages=pages, q=q, show=flt,
                               params={"q": q or None, "show": flt or None})

    @app.route("/admin/users/<int:uid>", methods=["GET", "POST"])
    @admin_required
    def admin_user(uid):
        u = db.get_user(uid)
        if not u:
            abort(404)
        errors = {}
        if request.method == "POST":
            until = (request.form.get("subscription_until") or "").strip()
            if until:
                try:
                    date.fromisoformat(until)
                except ValueError:
                    errors["subscription_until"] = "Enter a date as YYYY-MM-DD, or leave it empty."
            tmp = request.form.get("temp_password") or ""
            if tmp and not MIN_PW <= len(tmp) <= 128:
                errors["temp_password"] = f"Use at least {MIN_PW} characters."
            if not errors:
                fields = {"name": (request.form.get("name") or u["name"]).strip()[:120],
                          "company": (request.form.get("company") or "").strip()[:120],
                          "tier": "subscriber" if request.form.get("tier") == "subscriber" else "free",
                          "subscription_until": until, "active": 1 if request.form.get("active") else 0,
                          "notes": (request.form.get("notes") or "").strip()[:2000]}
                if tmp:
                    fields.update(pw_hash=generate_password_hash(tmp), must_change_pw=1)
                db.update_user(uid, **fields)
                flash("User saved." + (" They must choose a new password at next sign-in." if tmp else ""), "ok")
                return redirect(url_for("admin_user", uid=uid))
            flash("Fix the highlighted fields.", "error")
        return render_template("admin/user.html", u=u, errors=errors, eff=tier_of(u),
                               msgs=[m for m in db.list_messages() if m["user_id"] == uid])

    @app.route("/admin/users/<int:uid>/delete", methods=["POST"])
    @admin_required
    def admin_user_delete(uid):
        db.delete_user(uid)
        flash("User deleted.", "ok")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users.csv")
    @admin_required
    def admin_users_csv():
        which = request.args.get("list", "mailing")
        rows = [u for u in db.list_users() if u["active"] and (which == "all" or u["mailing_opt_in"])]
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["email", "name", "company", "tier", "mailing_list", "opted_in_at", "terms_version", "terms_accepted_at", "joined"])
        for u in rows:
            w.writerow([csv_cell(x) for x in (u["email"], u["name"], u["company"], tier_of(u), "yes" if u["mailing_opt_in"] else "no",
                                              u["mailing_opt_in_at"], u["terms_version"], u["terms_accepted_at"], u["created"])])
        name = "mailing-list.csv" if which != "all" else "all-users.csv"
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})

    @app.route("/admin/messages")
    @admin_required
    def admin_messages():
        kind = request.args.get("kind") or ""
        msgs = [m for m in db.list_messages() if not kind or m["kind"] == kind]
        items, page, pages = paginate(msgs, 20)
        return render_template("admin/messages.html", msgs=items, page=page, pages=pages, kind=kind, params={"kind": kind or None},
                               smtp=mailer.configured(), to=settings.load()["contact"]["email"])

    @app.route("/admin/messages/<int:mid>/<action>", methods=["POST"])
    @admin_required
    def admin_message_action(mid, action):
        m = db.get_message(mid)
        if not m or action not in ("read", "unread", "delete"):
            abort(404)
        if action == "delete":
            db.delete_message(mid)
            flash("Message deleted.", "ok")
        else:
            db.update_message(mid, status="read" if action == "read" else "new")
        return redirect(request.referrer or url_for("admin_messages"))
