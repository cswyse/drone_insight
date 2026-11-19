"""Backups, and the guarded "start over" actions.

* Download backup: a zip with the database, the site settings and uploaded files.
* Reset / restore sample data is hidden away from the Dashboard data page. It only works when the server
  has ENABLE_DATA_RESET=1 set, and then also needs the admin password and a typed phrase. A backup is
  saved automatically first (the last 10 are kept in instance/backups).
"""
import hmac
import io
import os
import sqlite3
import time
import zipfile
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, send_file, url_for

import data as d
import dataio
import db
import settings

BACKUP_DIR = os.path.join(db.INSTANCE, "backups")
KEEP = 10
REMIND_DAYS = 30
PHRASES = {"clear": "DELETE ALL DATA", "sample": "REPLACE WITH SAMPLE"}
_tries = {}


def reset_enabled():
    return os.environ.get("ENABLE_DATA_RESET") == "1"


def _db_copy(dest):
    """A consistent copy of the live database (safe while the site is running)."""
    src = sqlite3.connect(db.DB_PATH)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


def make_zip(path_or_buf, uploads):
    private = os.path.join(db.INSTANCE, "private")
    tmp = os.path.join(db.INSTANCE, "_backup_tmp.db")
    _db_copy(tmp)
    try:
        with zipfile.ZipFile(path_or_buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "site.db")
            if os.path.exists(settings.SITE_FILE):
                z.write(settings.SITE_FILE, "site.json")
            if os.path.isdir(uploads):
                for f in sorted(os.listdir(uploads)):
                    p = os.path.join(uploads, f)
                    if os.path.isfile(p):
                        z.write(p, "uploads/" + f)
            if os.path.isdir(private):                       # report PDFs and data files
                for f in sorted(os.listdir(private)):
                    z.write(os.path.join(private, f), "private/" + f)
    finally:
        os.remove(tmp)


def auto_backup(uploads, why):
    """Save a backup in instance/backups before something destructive. Returns the file name."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"before-{why}-{datetime.now():%Y%m%d-%H%M%S}.zip"
    make_zip(os.path.join(BACKUP_DIR, name), uploads)
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip"))
    for old in files[:-KEEP]:
        os.remove(os.path.join(BACKUP_DIR, old))
    return name


def last_backup():
    v = db.get_meta("last_backup", "")
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None, None
    return t, (datetime.now() - t).days


def register(app, admin_required, uploads, check_password, failed):
    @app.route("/admin/backup")
    @admin_required
    def admin_backup():
        when, days = last_backup()
        return render_template("admin/backup.html", nav_active="admin_backup", when=when, days=days,
                               remind=(when is None or days >= REMIND_DAYS), remind_days=REMIND_DAYS)

    @app.route("/admin/backup/download", methods=["POST"])
    @admin_required
    def admin_backup_download():
        buf = io.BytesIO()
        make_zip(buf, uploads)
        buf.seek(0)
        db.set_meta("last_backup", datetime.now().isoformat(timespec="seconds"))
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"backup-{datetime.now():%Y-%m-%d-%H%M}.zip")

    # Deliberately not linked from the menu or the data pages
    @app.route("/admin/backup/danger", methods=["GET", "POST"])
    @admin_required
    def admin_danger():
        error = None
        if request.method == "POST":
            action = request.form.get("action")
            ip = request.remote_addr or "?"
            recent = [t for t in failed.get(ip, []) if time.time() - t < 300]
            if action not in PHRASES:
                abort(400)
            if not reset_enabled():
                error = "Switched off on the server. See the notes below."
            elif len(recent) >= 5:
                error = "Too many attempts. Wait a few minutes."
            elif not check_password(request.form.get("password", "")):
                failed[ip] = recent + [time.time()]
                error = "That password is not right."
            elif not hmac.compare_digest(request.form.get("phrase", "").strip(), PHRASES[action]):
                error = "The confirmation phrase does not match."
            if not error:
                name = auto_backup(uploads, action)
                if action == "clear":
                    dataio.clear_figures()
                    flash("Market sizes, companies and financials were cleared.", "ok")
                else:
                    dataio.seed_sample()
                    flash("The sample data was restored.", "ok")
                flash(f"A backup was saved first: instance/backups/{name}", "ok")
                return redirect(url_for("admin_backup"))
        return render_template("admin/danger.html", nav_active="admin_backup", error=error,
                               enabled=reset_enabled(), phrases=PHRASES)
