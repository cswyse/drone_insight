# Meridian Market Intelligence

An industry-agnostic market intelligence platform built with Flask. It ships with a fictional sample dataset so every page works out of the box; adapt it to a specific market later by editing one config file and swapping the data source.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Set `PORT` to change the port and `SECRET_KEY` for production.

## Pages

| Route | What it does |
|---|---|
| `/` | Homepage with the animated globe hero, feature overview and latest summaries |
| `/news`, `/news/<slug>` | News list (summaries, Previous / Next paging) and full article pages. `/updates` redirects here |
| `/dashboard` | Market intelligence dashboard (see below); news panels use the published articles |
| `/company/<slug>` | Company profile: financials, margins, revenue mix, news, peers |
| `/white-papers`, `/white-papers/<slug>` | Free long-form research |
| `/reports`, `/reports/<slug>` | Paid reports with licence tiers and a demo checkout |
| `/signup`, `/login`, `/account` | Accounts: sign up with terms and optional mailing list, sign in, manage details, change password, delete account |
| `/pricing`, `/contact` | Plan comparison and enquiry forms (emailed to you and saved in Admin > Messages) |
| `/terms`, `/privacy` | Legal pages, written in `legal/terms.md` and `legal/privacy.md` |
| `/admin` | Publishing, users, messages and site settings (password protected) |
| `/api/market`, `/api/news`, `/api/company/<slug>` | JSON endpoints |

## Dashboard data (Admin > Dashboard data)

The dashboard is driven by the database, not by code. The first run fills it with fictional sample data; you can edit it, or clear it and enter your own. Four steps:

1. **Countries, sub-sectors, verticals:** rename, reorder, add and delete the lists the market is split into. Countries have a region, city, exchange and a two-letter flag code (all flags are bundled in `static/flags`).
2. **Market sizing:** pick a country, then enter market size (US$ bn) for each sub-sector and vertical by year. You only need a few years: gaps are smoothed and later years grow at the rate you give or the one implied by your numbers. Or download the CSV, edit it in a spreadsheet and upload it (names or ids, all-or-nothing import).
3. **Companies:** profile, revenue split by country, sub-sector and vertical (percentages, scaled to 100), and financials by year (US$ m; only revenue is required). A company appears in dashboard tables once it has financials and a split. Years outside your data follow the growth of the markets the company sells into. Financials can also be bulk imported and exported as CSV.
4. **Page sections:** define your own sections for company, country, sub-sector and vertical pages (text, list, links or a short fact such as a website), choose where they go, reorder or hide them, and switch off built-in panels. Fill them in on each company (its edit page) or each country, sub-sector and vertical (the "Page content" link).

The **Break down by** table on the dashboard has a search box, sortable columns (click a header such as market size, YoY or CAGR; click again to reverse; blanks always sort last) and 25 rows per page. Search, sorting and paging run in the browser, which is comfortable for several hundred to a few thousand rows. Clicking a row, tab or heatmap cell updates the dashboard in place without jumping back to the top. Change the page size with `data-per` on the table in `templates/dashboard.html`.

### Confidence levels

Every figure can carry a confidence level, from reported data down to a low-confidence estimate: **Reported**, **High-confidence estimate**, **Medium-confidence estimate** and **Low-confidence estimate**. Set them in two places:

- **Market sizing:** a Confidence column on each sub-sector and vertical row (or a `confidence` column in the CSV). Rows left on Default count as medium.
- **Company financials:** a Confidence column on each year (or `confidence` in the financials CSV). Left on Default, years up to the last actual year count as reported and later years as high-confidence estimates.

The dashboard shows the level beside the market size, in a sortable Confidence column in the breakdown table, and on the company page. For a selection it averages the levels of the markets inside it, weighted by size. A company with no entry for the current year gets a low level, because that figure is extrapolated from its markets. To rename the levels or rewrite their descriptions, edit `CONFIDENCE` in `config.py` (keep the four ids).

"Start over" on the overview page clears all numbers or restores the sample data. Turn off the footer "sample data" notice there once you use real data. `config.py` still holds the first-run defaults and the timeline (years, last actual year, estimate year); `sample_data.py` generates the sample set.

## Featured images and flags

- Every news article, white paper and report has a **Featured image** field in Admin (upload or paste a path). It shows as a small thumbnail on the home page, News, White papers and Reports cards, and at the top of the item's own page.
- Country flags (SVG, from the MIT-licensed flag-icons set) appear next to country names on the dashboard, in news lines and on company pages. Flags for all countries are bundled; set the flag code per country in Dashboard data. A missing flag is simply hidden.

## Accounts and tiers

| | Signed out | Free account | Subscriber |
|---|---|---|---|
| News | yes | yes | yes |
| White papers | summary only | full | full |
| Dashboard, company profiles | no | no | yes |
| Reports | overview, can order | overview, can order | overview + PDF download |

Payments are manual. In **Admin > Users** open a user and set the tier to Subscriber, with an optional end date (they drop to Free automatically after it). You can also disable an account, set a temporary password (the user must change it at next sign-in, so this doubles as password reset), and keep private notes. Admins signed in at `/admin` can see everything.

- **Mailing list:** the signup form has an unticked "add me to the mailing list" box, separate from the required terms box. **Admin > Users > Download mailing list (CSV)** exports active users who opted in, with the date they opted in. Users can change this in their account.
- **Terms and privacy:** acceptance and the version are stored per user. The text in `legal/terms.md` and `legal/privacy.md` is a template with `[bracketed]` gaps: fill it in and have it checked by a lawyer. Bump `legal.version` in `site.json` when you change it.
- **Report PDFs:** open a report in Admin and upload the PDF at the bottom. It is stored in `instance/private`, not publicly, and only subscribers can download it.
- **Contact and pricing forms:** set the address in **Admin > Settings > Enquiries**. Every message is saved in **Admin > Messages**. To also get them by email, set `SMTP_HOST`, `SMTP_PORT` (587 default, 465 for SSL), `SMTP_USER`, `SMTP_PASSWORD` and optionally `SMTP_FROM` before starting the app. Messages show whether the email went out.
- **Security notes:** passwords are hashed, sign-in and forms are rate limited, forms have CSRF protection and a honeypot, and there is no email verification or self-service reset yet (no email system is assumed). Serve the site over HTTPS in production and set `SECRET_KEY`.

## Admin: publishing and settings

Open `/admin` and sign in. The password is the `ADMIN_PASSWORD` environment variable (default `change-me`, with a warning banner shown until you change it). Set `SECRET_KEY` too in production.

```bash
ADMIN_PASSWORD='something-long' python app.py
```

- **News, white papers, reports**: create, edit, preview, save as draft or publish. Write in Markdown. News can be tagged to a company, country, sub-sector or vertical so it appears in the matching dashboard panels.
- **Images**: use the upload button in the editor (png, jpg, gif, webp). It inserts `![Alt text](/uploads/file.png "Caption")`.
- **Charts**: use the chart buttons, or write a fenced block. The first data row names the series:

````
```chart
type: bar            (bar, hbar or line)
title: Market size by region
unit: US$ bn
source: Company estimates
Region, 2025, 2026
Americas, 410, 445
Europe, 280, 295
```
````

- **Settings**: site name, tagline, logo, favicon, colours, fonts, corner radius, page width, chart colours and page sizes, with presets and a live preview. Values are stored in `site.json`, which you can also edit by hand. Everything (CSS, charts, globe) reads from it through `/theme.css`.
- Authors are trusted: raw HTML in Markdown is allowed.

Content lives in `instance/site.db` and uploads in `instance/uploads`. The sample content in `content.py` and `seed.py` is written only on first run. To start over, delete `instance/site.db` and restart.

### Dashboard drill-down

State lives in the URL (`?country=us&subsector=digital-platforms&vertical=tmt&view=company`), so every view is shareable.

1. Start globally, or click a country.
2. Break down by **sub-sector** or **vertical** (tabs). Click a row to filter.
3. Switch to **Company** to see revenue, market share and margin within that slice.
4. Click a company to open its profile; the page shows its share of the slice you came from.

The sub-sector by vertical heatmap lets you jump straight to a combination. Filter chips in the header remove any filter. The news panel narrows with the selection and widens automatically (marked "Wider context") when a slice has few items.

## Adapting it to an industry

- **`site.json` / Admin Settings**: name, logo and theme.
- **`config.py`**: rename the sub-sectors and verticals, edit countries, timeline and base market size. Everything else reads from here.
- **`content.py`, `seed.py`**: first-run sample content only; after that use Admin.
- **`data.py`**: the sample data is generated deterministically in `build_store()`. To use real data, load your own into the same structures (documented at the top of the file) from a database, CSV or API. Dashboard and company pages need no changes.
- **Payments**: `/reports/<slug>` records orders to `instance/orders.json` with status `pending-payment`. Add a payment provider (e.g. Stripe Checkout) in the `report()` view.

## Structure

```
app.py          routes, template helpers, JSON API
dataio.py       dashboard data in SQLite, sample seeding
datamgr.py      admin screens for dashboard data
sample_data.py  sample dataset generator
members.py      accounts, tiers, forms, user admin
mailer.py       optional SMTP delivery of enquiries
legal/          terms and privacy text
config.py       timeline and market taxonomy
settings.py     site.json loader, theme and validation
site.json       name, logo, theme, pagination
db.py           SQLite content store
richtext.py     Markdown with chart blocks and figures
seed.py         first-run sample content
data.py         sample data generator and query layer
content.py      white papers, reports, licence tiers
templates/      Jinja pages
static/         css, charts.js (dependency-free SVG charts), hero3d.js (canvas globe), admin.js
```

All data is fictional. No external services or JavaScript libraries are required.
