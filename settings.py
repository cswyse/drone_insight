"""
Site settings: brand and theme in ONE place (site.json).

Edit site.json by hand, or use Admin > Settings. Changes apply to every page, chart and the hero globe,
because the whole site reads its colours and fonts from the generated /theme.css.
"""
import copy
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE_FILE = os.path.join(ROOT, "site.json")

DEFAULTS = {
    "brand": {
        "name": "Meridian", "product": "Market Intelligence",
        "tagline": "See the whole market. Decide with confidence.",
        "lead": "Market size, company moves and independent research in one place.",
        "logo": "", "logo_dark": "", "favicon": "", "logo_height": 30,
    },
    "theme": {
        "primary": "#051C2C", "accent": "#2251FF", "highlight": "#00A9F4", "ink": "#1B2733", "muted": "#566677",
        "line": "#D8DEE5", "soft": "#F3F5F8", "background": "#FFFFFF", "positive": "#0B7A4B", "negative": "#B3261E",
        "heading_font": "Georgia, 'Times New Roman', Times, serif",
        "body_font": "'Helvetica Neue', Helvetica, Arial, 'Segoe UI', sans-serif",
        "google_fonts_url": "", "heading_weight": "400", "radius": "0px", "max_width": "1200px",
    },
    "charts": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]},
    "pagination": {"news": 10, "papers": 6, "reports": 6},
    "contact": {"email": ""},
    "pricing": {"subscriber_price": "Contact us for pricing", "subscriber_note": "Invoiced by arrangement. Access is switched on by our team."},
    "legal": {"version": "1.0", "updated": "2026-11-16"},
}

COLOR_KEYS = ["primary", "accent", "highlight", "ink", "muted", "line", "soft", "background", "positive", "negative"]

# One-click starting points in Admin > Settings
PRESETS = {
    "Navy and blue": {"primary": "#051C2C", "accent": "#2251FF", "highlight": "#00A9F4", "ink": "#1B2733", "muted": "#566677", "line": "#D8DEE5", "soft": "#F3F5F8", "background": "#FFFFFF"},
    "Forest": {"primary": "#0F2E24", "accent": "#0F7B5F", "highlight": "#5CC9A7", "ink": "#1A2A24", "muted": "#586A62", "line": "#D9E2DD", "soft": "#F2F6F4", "background": "#FFFFFF"},
    "Charcoal and amber": {"primary": "#1C1F26", "accent": "#D9730D", "highlight": "#F2A541", "ink": "#22252B", "muted": "#5E636D", "line": "#DEDFE3", "soft": "#F5F5F6", "background": "#FFFFFF"},
    "Burgundy": {"primary": "#2B0F1B", "accent": "#A31D4B", "highlight": "#E5708F", "ink": "#2A1A21", "muted": "#6A5560", "line": "#E6DCE0", "soft": "#F8F4F6", "background": "#FFFFFF"},
    "Light and clean": {"primary": "#E9EEF5", "accent": "#1F5FD6", "highlight": "#2AA3D9", "ink": "#16202B", "muted": "#566677", "line": "#D8DEE5", "soft": "#F5F7FA", "background": "#FFFFFF"},
}

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_cache = {"mtime": None, "data": None}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    """Return merged settings, re-reading site.json when it changes."""
    try:
        mtime = os.path.getmtime(SITE_FILE)
    except OSError:
        mtime = None
    if _cache["data"] is None or _cache["mtime"] != mtime:
        try:
            with open(SITE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = {}
        _cache["data"] = _merge(DEFAULTS, data)
        _cache["mtime"] = mtime
    return _cache["data"]


def version():
    load()
    return int(_cache["mtime"] or 0)


def save(data):
    with open(SITE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    _cache["data"] = None


# ----- colour helpers -------------------------------------------------
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(c):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(x))) for x in c)


def mix(a, b, pct):
    """pct% of colour a mixed with the rest of b."""
    ra, rb = rgb(a), rgb(b)
    return to_hex([ra[i] * pct / 100 + rb[i] * (100 - pct) / 100 for i in range(3)])


def luminance(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def on_color(h):
    """Readable text colour (white or near-black) for a given background."""
    return "#FFFFFF" if luminance(h) < 0.35 else "#0B1620"


def theme_context():
    t = load()["theme"]
    c = load()["charts"]
    primary, accent, bg = t["primary"], t["accent"], t["background"]
    on_primary = on_color(primary)
    ctx = dict(t)
    ctx.update({
        "primary_rgb": ",".join(map(str, rgb(primary))),
        "accent_rgb": ",".join(map(str, rgb(accent))),
        "highlight_rgb": ",".join(map(str, rgb(t["highlight"]))),
        "on_primary": on_primary,
        "on_primary_rgb": ",".join(map(str, rgb(on_primary))),
        "on_accent": on_color(accent),
        "chart_actual": primary if luminance(primary) < 0.6 else t["ink"],
        "chart_estimate": accent,
        "chart_forecast": mix(accent, bg, 42),
        "series": (c.get("series") or DEFAULTS["charts"]["series"])[:5],
    })
    return ctx


def clean_hex(v, fallback):
    v = (v or "").strip()
    if re.match(r"^#[0-9a-fA-F]{3}$", v):
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v.upper() if HEX_RE.match(v) else fallback


_SAFE_CSS = re.compile(r"^[A-Za-z0-9 ,'\"\-_.()]+$")


def clean_css_value(v, fallback):
    v = (v or "").strip()
    return v if v and _SAFE_CSS.match(v) else fallback


def clean_settings(form, current, files_saved):
    """Validate the admin settings form into a new settings dict."""
    s = copy.deepcopy(current)
    b, t = s["brand"], s["theme"]
    for k in ("name", "product", "tagline", "lead"):
        val = (form.get(k) or "").strip()
        if val:
            b[k] = val[:300]
    try:
        b["logo_height"] = max(16, min(80, int(form.get("logo_height") or b["logo_height"])))
    except ValueError:
        pass
    for k in ("logo", "logo_dark", "favicon"):
        if form.get("remove_" + k):
            b[k] = ""
        if k in files_saved:
            b[k] = files_saved[k]
    for k in COLOR_KEYS:
        t[k] = clean_hex(form.get("color_" + k), t[k])
    t["heading_font"] = clean_css_value(form.get("heading_font"), t["heading_font"])
    t["body_font"] = clean_css_value(form.get("body_font"), t["body_font"])
    url = (form.get("google_fonts_url") or "").strip()
    t["google_fonts_url"] = url if (url == "" or url.startswith("https://fonts.googleapis.com/")) else t["google_fonts_url"]
    if form.get("heading_weight") in ("300", "400", "500", "600", "700"):
        t["heading_weight"] = form["heading_weight"]
    if form.get("radius") in ("0px", "2px", "4px", "8px", "12px"):
        t["radius"] = form["radius"]
    series = [clean_hex(form.get("series_%d" % i), s["charts"]["series"][i]) for i in range(5)]
    s["charts"]["series"] = series
    for key in ("news", "papers", "reports"):
        try:
            s["pagination"][key] = max(3, min(50, int(form.get("per_" + key) or s["pagination"][key])))
        except ValueError:
            pass
    em = (form.get("contact_email") or "").strip()
    if em == "" or re.match(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$", em):
        s["contact"]["email"] = em
    for k in ("subscriber_price", "subscriber_note"):
        s["pricing"][k] = (form.get("pricing_" + k) or "").strip()[:200]
    return s
