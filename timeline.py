"""
The dashboard's timeline: which period it is "as of", how far reported data runs, and how far forecasts go.

    first_year / last_year   the years the dashboard covers (the last one is the forecast horizon)
    current_year / quarter   the period the dashboard is "as of"; the current year is the headline year
    last_actual_year         the latest year of annual (market) data that is fully reported
    last_actual_q            the latest quarter of company data that is reported, as [year, quarter]
    price_base               the year whose prices real (constant-price) market sizes are in; blank means the
                             latest reported year, which is the usual choice

Years up to last_actual_year are actual (A). Years after it, up to the current year, are estimates (E), so
the dashboard can be moved forward while the newest data is still to come. Later years are forecasts (F).
Quarters up to last_actual_q are actual; later quarters, up to the current one, are estimates.

The settings live in the database (meta key "timeline") and are applied to `config` and `data` on every
reload. `config.py` only supplies the defaults for a new install.
"""
import json

import config as cfg
import db

DEFAULTS = {
    "first_year": cfg.YEARS[0], "last_year": cfg.YEARS[-1],
    "current_year": cfg.ESTIMATE_YEAR, "current_quarter": 4,
    "last_actual_year": cfg.LAST_ACTUAL, "last_actual_q": [cfg.ESTIMATE_YEAR, 3],
}
HORIZON_GAP = DEFAULTS["last_year"] - DEFAULTS["current_year"]   # years of forecast kept when advancing

# Lists the rest of the code holds references to: updated in place by apply()
FIN_YEARS = []
CURRENT = {"q": DEFAULTS["current_quarter"], "last_actual_q": tuple(DEFAULTS["last_actual_q"]), "price_base": None}


def qkey(year, quarter):
    return year * 4 + quarter - 1


def qlabel(year, quarter, short=False):
    return f"Q{quarter} '{str(year)[2:]}" if short else f"Q{quarter} {year}"


def clean(raw):
    """Validate a settings dict. Returns (settings, errors)."""
    t, errors = {}, []
    base = {**DEFAULTS, **(raw or {})}
    try:
        for k in ("first_year", "last_year", "current_year", "current_quarter", "last_actual_year"):
            t[k] = int(base[k])
        la = base["last_actual_q"]
        t["last_actual_q"] = [int(la[0]), int(la[1])]
        pb = base.get("price_base")
        t["price_base"] = None if pb in (None, "") else int(pb)
    except (TypeError, ValueError, IndexError, KeyError):
        return dict(DEFAULTS), ["Some of the timeline values are not numbers."]
    if not 1 <= t["current_quarter"] <= 4 or not 1 <= t["last_actual_q"][1] <= 4:
        errors.append("Quarters are 1 to 4.")
    if not 1990 <= t["first_year"] <= t["current_year"] - 2:
        errors.append(f"The start year must be at least two years before the current year ({t['current_year']}).")
    if t["last_year"] < t["current_year"] + 2:
        errors.append(f"The forecast must run to at least {t['current_year'] + 2}.")
    if t["last_year"] - t["first_year"] > 40:
        errors.append("The timeline can cover at most 40 years.")
    if not t["first_year"] - 1 <= t["last_actual_year"] <= t["current_year"]:
        errors.append(f"The latest reported year must be between {t['first_year'] - 1} and the current year ({t['current_year']}).")
    if t["price_base"] is not None and not t["first_year"] <= t["price_base"] <= t["last_year"]:
        errors.append(f"The price year must be between {t['first_year']} and {t['last_year']}, or left on the latest reported year.")
    if not errors and qkey(*t["last_actual_q"]) > qkey(t["current_year"], t["current_quarter"]):
        errors.append("The latest reported quarter cannot be after the current quarter.")
    return (t if not errors else dict(DEFAULTS)), errors


def load():
    try:
        raw = json.loads(db.get_meta("timeline", "") or "{}")
    except ValueError:
        raw = {}
    t, errors = clean(raw)
    return t


def save(t):
    db.set_meta("timeline", json.dumps(t))
    db.bump()


def reset():
    db.set_meta("timeline", "")


def apply(t=None):
    """Push the settings into config and the shared lists. Returns the settings."""
    t = t or load()
    cfg.YEARS[:] = range(t["first_year"], t["last_year"] + 1)
    cfg.ESTIMATE_YEAR = t["current_year"]
    cfg.LAST_ACTUAL = t["last_actual_year"]
    cfg.FORECAST_FROM = t["current_year"] + 1
    CURRENT["q"] = t["current_quarter"]
    CURRENT["last_actual_q"] = tuple(t["last_actual_q"])
    CURRENT["price_base"] = t.get("price_base")
    FIN_YEARS[:] = [y for y in cfg.YEARS if y <= t["current_year"]]
    return t


def advance(t, quarters):
    """Move 'as of' forward by whole quarters. The forecast horizon moves with it; reported-data dates stay where
    they are until you move them, because newer data is often not out yet."""
    t = dict(t)
    n = t["current_year"] * 4 + (t["current_quarter"] - 1) + quarters
    new_year, t["current_quarter"] = n // 4, n % 4 + 1
    t["last_year"] += new_year - t["current_year"]
    t["current_year"] = new_year
    return t


def price_base():
    """The year real market sizes are priced in: set under Timeline, otherwise the latest reported year."""
    y = CURRENT["price_base"] or cfg.LAST_ACTUAL
    return y if cfg.YEARS[0] <= y <= cfg.YEARS[-1] else cfg.LAST_ACTUAL


def year_status(y):
    if y <= cfg.LAST_ACTUAL:
        return "A"
    if y <= cfg.ESTIMATE_YEAR:
        return "E"
    return "F"


def quarter_status(year, quarter):
    return "A" if qkey(year, quarter) <= qkey(*CURRENT["last_actual_q"]) else "E"


def quarter_slots(from_year):
    """(year, quarter) pairs from the first quarter of from_year to the current quarter."""
    out = []
    for y in range(max(from_year, cfg.YEARS[0]), cfg.ESTIMATE_YEAR + 1):
        for q in range(1, 5):
            if y == cfg.ESTIMATE_YEAR and q > CURRENT["q"]:
                break
            out.append((y, q))
    return out


def year_suffix(y):
    return {"A": "", "E": "E", "F": "F"}[year_status(y)]


def describe(t=None):
    """Plain-language summary for the pages."""
    t = t or {"first_year": cfg.YEARS[0], "last_year": cfg.YEARS[-1], "current_year": cfg.ESTIMATE_YEAR,
              "current_quarter": CURRENT["q"], "last_actual_year": cfg.LAST_ACTUAL, "last_actual_q": list(CURRENT["last_actual_q"])}
    la, cy, ly = t["last_actual_year"], t["current_year"], t["last_year"]
    est = f"{la + 1}" if cy == la + 1 else f"{la + 1} to {cy}"
    parts = [f"Actual to {la}"]
    if cy > la:
        parts.append(f"{est} estimated")
    parts.append(f"{cy + 1} to {ly} forecast" if ly > cy + 1 else f"{ly} forecast")
    return {
        "as_of": qlabel(cy, t["current_quarter"]), "first_year": t["first_year"], "current_year": cy, "last_actual_year": la, "last_year": ly,
        "last_actual_q": qlabel(*t["last_actual_q"]), "note": " · ".join(parts),
        "now_label": f"{cy}{year_suffix(cy)}",
    }


FIN_YEARS[:] = [y for y in cfg.YEARS if y <= cfg.ESTIMATE_YEAR]
