"""SQLite storage for published content (news, white papers, reports) and report orders."""
import json
import os
import re
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.path.join(ROOT, "instance")
os.makedirs(INSTANCE, exist_ok=True)
DB_PATH = os.path.join(INSTANCE, "site.db")

KINDS = ("news", "paper", "report")

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    cover TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'published',
    meta TEXT NOT NULL DEFAULT '{}',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    UNIQUE(kind, slug)
);
CREATE INDEX IF NOT EXISTS idx_posts_kind_date ON posts(kind, status, date DESC, id DESC);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    report_slug TEXT, title TEXT, licence TEXT, amount INTEGER,
    name TEXT, email TEXT, company TEXT, created TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    pw_hash TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    subscription_until TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    mailing_opt_in INTEGER NOT NULL DEFAULT 0,
    mailing_opt_in_at TEXT NOT NULL DEFAULT '',
    terms_version TEXT NOT NULL DEFAULT '',
    terms_accepted_at TEXT NOT NULL DEFAULT '',
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    last_login TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', company TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '',
    user_id INTEGER, created TEXT NOT NULL,
    emailed INTEGER NOT NULL DEFAULT 0, email_error TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new'
);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def get_meta(key, default=""):
    with conn() as c:
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_meta(key, value):
    with conn() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def bump(c=None):
    """Mark published content or dashboard data as changed, so every running worker reloads its in-memory copy.
    Pass an open connection when called inside a transaction."""
    if c is None:
        with conn() as c2:
            return bump(c2)
    if True:
        c.execute("INSERT INTO meta (key, value) VALUES ('version','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")


def version():
    return get_meta("version", "0")


def slugify(s):
    out = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return out[:80].strip("-") or "untitled"


def _post(row):
    if row is None:
        return None
    p = dict(row)
    p["tags"] = json.loads(p["tags"] or "[]")
    p["meta"] = json.loads(p["meta"] or "{}")
    return p


def unique_slug(c, kind, base, exclude_id=None):
    base = slugify(base)
    slug, n = base, 2
    while True:
        row = c.execute("SELECT id FROM posts WHERE kind=? AND slug=?", (kind, slug)).fetchone()
        if not row or (exclude_id and row["id"] == exclude_id):
            return slug
        slug = f"{base}-{n}"
        n += 1


def count(kind=None):
    with conn() as c:
        if kind:
            return c.execute("SELECT COUNT(*) FROM posts WHERE kind=?", (kind,)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]


def list_posts(kind, published_only=True, with_body=False):
    cols = "*" if with_body else "id, kind, slug, title, summary, cover, date, author, tags, status, meta, created, updated"
    q = f"SELECT {cols} FROM posts WHERE kind=?"
    args = [kind]
    if published_only:
        q += " AND status='published'"
    q += " ORDER BY date DESC, id DESC"
    with conn() as c:
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        p = dict(r)
        p["tags"] = json.loads(p["tags"] or "[]")
        p["meta"] = json.loads(p["meta"] or "{}")
        out.append(p)
    return out


def get_by_slug(kind, slug, published_only=True):
    q = "SELECT * FROM posts WHERE kind=? AND slug=?"
    if published_only:
        q += " AND status='published'"
    with conn() as c:
        return _post(c.execute(q, (kind, slug)).fetchone())


def get(post_id):
    with conn() as c:
        return _post(c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())


def save(kind, data, post_id=None):
    """Insert or update. data: title, summary, body, cover, date, author, tags(list), status, meta(dict), slug(optional)."""
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with conn() as c:
        slug = unique_slug(c, kind, data.get("slug") or data["title"], exclude_id=post_id)
        vals = (slug, data["title"], data.get("summary", ""), data.get("body", ""), data.get("cover", ""),
                data["date"], data.get("author", ""), json.dumps(data.get("tags", [])),
                data.get("status", "published"), json.dumps(data.get("meta", {})))
        if post_id:
            c.execute("""UPDATE posts SET slug=?, title=?, summary=?, body=?, cover=?, date=?, author=?, tags=?,
                         status=?, meta=?, updated=? WHERE id=? AND kind=?""", vals + (now, post_id, kind))
            bump(c)
            return post_id
        cur = c.execute("""INSERT INTO posts (slug, title, summary, body, cover, date, author, tags, status, meta, kind, created, updated)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", vals + (kind, now, now))
        bump(c)
        return cur.lastrowid


def bulk_insert(kind, items):
    """Fast insert used by seeding; items as for save()."""
    for it in items:
        save(kind, it)


def delete(post_id):
    with conn() as c:
        c.execute("DELETE FROM posts WHERE id=?", (post_id,))
    bump()


def set_status(post_id, status):
    with conn() as c:
        c.execute("UPDATE posts SET status=?, updated=? WHERE id=?",
                  (status, datetime.utcnow().isoformat(timespec="seconds") + "Z", post_id))
    bump()


# ---- orders ----------------------------------------------------------
def add_order(o):
    with conn() as c:
        c.execute("INSERT INTO orders (id, report_slug, title, licence, amount, name, email, company, created, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (o["id"], o["report"], o["title"], o["licence"], o["amount"], o["name"], o["email"], o["company"],
                   o["created"], o["status"]))


def get_order(order_id):
    with conn() as c:
        r = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not r:
        return None
    o = dict(r)
    o["report"] = o.pop("report_slug")
    return o


def list_orders():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY created DESC").fetchall()]


# ---- users -----------------------------------------------------------
def _now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


USER_FIELDS = {"name", "company", "pw_hash", "tier", "subscription_until", "active", "mailing_opt_in",
               "mailing_opt_in_at", "terms_version", "terms_accepted_at", "must_change_pw", "notes", "last_login"}


def add_user(email, name, company, pw_hash, opt_in, terms_version):
    now = _now()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO users (email, name, company, pw_hash, mailing_opt_in, mailing_opt_in_at, terms_version, terms_accepted_at, created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (email.strip().lower(), name, company, pw_hash, 1 if opt_in else 0, now if opt_in else "", terms_version, now, now))
        return cur.lastrowid


def get_user(uid):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def get_user_by_email(email):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
    return dict(r) if r else None


def update_user(uid, **fields):
    fields = {k: v for k, v in fields.items() if k in USER_FIELDS}
    if not fields:
        return
    with conn() as c:
        c.execute(f"UPDATE users SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), uid))


def list_users():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY created DESC, id DESC").fetchall()]


def delete_user(uid):
    with conn() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("UPDATE messages SET user_id=NULL WHERE user_id=?", (uid,))


# ---- enquiries -------------------------------------------------------
def add_message(m):
    with conn() as c:
        cur = c.execute("INSERT INTO messages (kind, name, email, company, topic, subject, message, user_id, created) VALUES (?,?,?,?,?,?,?,?,?)",
                        (m["kind"], m["name"], m["email"], m.get("company", ""), m.get("topic", ""), m.get("subject", ""),
                         m["message"], m.get("user_id"), _now()))
        return cur.lastrowid


def get_message(mid):
    with conn() as c:
        r = c.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    return dict(r) if r else None


def list_messages():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM messages ORDER BY created DESC, id DESC").fetchall()]


def update_message(mid, **fields):
    fields = {k: v for k, v in fields.items() if k in ("emailed", "email_error", "status")}
    if fields:
        with conn() as c:
            c.execute(f"UPDATE messages SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), mid))


def delete_message(mid):
    with conn() as c:
        c.execute("DELETE FROM messages WHERE id=?", (mid,))
