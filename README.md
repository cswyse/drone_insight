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

## Timeline: moving the dashboard through time (Admin > Dashboard data > Timeline)

The dashboard is not tied to a fixed year. The Timeline page holds:

- **As of:** a year and quarter. The current year is the headline year (the "2027E" in the figures and tables).
- **Reported to:** the latest year of annual data that is fully reported, and, separately, the latest quarter of company data. These do not have to move with "as of", so you can advance the dashboard while the newest figures are still to come. Years between "reported to" and the current year show as **estimates**, later years as **forecasts**, for example "Actual to 2025, 2026 to 2027 estimated, 2028 to 2031 forecast".
- **First year shown** and **forecast horizon.**

**Advance one quarter / one year** moves "as of" on. When the year rolls over the headline year changes and the forecast extends by a year. New years are filled in from the growth of your existing market sizes so the dashboard is never empty; enter real figures in Market sizing when you have them. **Mark a year (or quarter) as reported** changes it from estimate to actual when your data arrives, and financials you enter for it then default to "Reported". "Start over > restore sample data" also resets the timeline.

Market sizes are stored by year, so moving the timeline never loses data: years outside the view are kept, and databases from earlier versions are upgraded automatically.

### Quarterly company data

Market sizes stay annual. Companies can optionally report quarterly: open a company, then **Quarterly financials** (revenue, EBITDA, net income, capex and a confidence level per quarter, up to the current quarter). A year with quarterly figures takes its annual numbers from them. Quarters not reported yet are projected from the same quarter a year earlier (or from the average of the quarters you have if there is no earlier year), the year is labelled an estimate, and its confidence is capped by how many quarters were projected. The company page then shows an **Annual / Quarterly** switch and a quarterly revenue chart. The financials CSV has a `quarter` column (1 to 4, blank for a full year) for import and export.

### Confidence levels

Every figure can carry a confidence level, from reported data down to a low-confidence estimate: **Reported**, **High-confidence estimate**, **Medium-confidence estimate** and **Low-confidence estimate**. Set them in two places:

- **Market sizing:** a Confidence column on each sub-sector and vertical row (or a `confidence` column in the CSV). Rows left on Default count as medium.
- **Company financials:** a Confidence column on each year (or `confidence` in the financials CSV). Left on Default, years up to the last actual year count as reported and later years as high-confidence estimates.

The dashboard shows the level beside the market size, in a sortable Confidence column in the breakdown table, and on the company page. For a selection it averages the levels of the markets inside it, weighted by size. A company with no entry for the current year gets a low level, because that figure is extrapolated from its markets. To rename the levels or rewrite their descriptions, edit `CONFIDENCE` in `config.py` (keep the four ids).

"Start over" on the overview page clears all numbers or restores the sample data. Turn off the footer "sample data" notice there once you use real data. `config.py` still holds the first-run defaults and the timeline (years, last actual year, estimate year); `sample_data.py` generates the sample set.

## How the numbers are calculated

A short, client-facing answer to "where does this figure come from?". Everything on the dashboard is either **entered** by you (market sizes, company revenue and other financials, revenue splits, confidence levels) or **calculated** from what you entered by the rules below. There is no hidden modelling and no randomness: the same inputs always give the same outputs. (The sample data that ships with the project is generated with a random model purely to look realistic; it is fictional and is replaced by your own data.) Every calculated figure carries a [confidence level](#confidence-levels) so readers can see how much to trust it.

Years are labelled **A** (actual, up to the "reported to" year on the Timeline page), **E** (estimate, after that up to the current year) and **F** (forecast, after the current year). Money is US$ billions for markets and US$ millions for companies.

### 1. Market sizes

Market size is entered for each *country x sub-sector x vertical* row ("cell") and year. The totals you see for a country, sub-sector, vertical, selection or the whole market are **sums of the matching cells**, nothing more.

**Years you leave blank are filled in** (Market sizing grid, CSV import, and any year the timeline moves into):

| Situation | Rule | Example (entered: 2021 = 100, 2026 = 150) |
|---|---|---|
| Blank years **between** two numbers | Steady growth between them: `value = earlier x (later / earlier) ^ t`, where t is the fraction of the way along. (If either number is zero or negative, a straight line is used instead.) | 2022 108.4, 2023 117.6, 2024 127.5, 2025 138.3 |
| Years **after** your last number | Compound the last number by an annual growth rate. The rate is the one you typed in the row's "Growth % a year" box; if blank, it is the average annual growth between your first and last number, limited to -20% to +30%; with only one number (or a zero/negative one) it is 3.5%. | 2027 = 150 x 1.0845 = 162.7; with 5% typed in: 157.5 |
| Years **before** your first number | The same growth rate, run backwards: `value = next / (1 + rate)`. | with only 2023 = 80: 2022 77.3, 2021 74.7 |

Moving the timeline forward (see below) uses exactly the same rule to give new years a first estimate, so the dashboard is never empty. Those years are estimates until you enter real figures. Years are stored individually, so nothing you entered is ever overwritten by this.

### 2. Growth figures

- **YoY** = this year / last year - 1, for the current year against the year before.
- **CAGR** (compound annual growth rate) = `(end / start) ^ (1 / years) - 1`. It is blank ("-") when either end is zero or negative.
- **CAGR, historical column** = the last **5 years up to the current year** (for example 2022 to 2027 when the dashboard is as of 2027). **CAGR, forecast column** = the **5 years after** the current year (2027 to 2032). If the timeline does not have five years on that side, the window is shortened to what exists, and the column heading always states the exact years used. Change the window with `CAGR_YEARS` in `config.py`.
- **Share of selection** (country, sub-sector, vertical tables) = the row's current-year size / the total for the current selection.
- **Company market share** = the company's revenue within the selection (US$ m) / the market size of the selection (US$ bn x 1,000).

### 2a. Market size confidence for a selection

Each market row has its own confidence level (set by you; rows left on Default count as the level in `CONFIDENCE_DEFAULT_MARKET`, medium). For a selection (a country, a sub-sector, the whole market, and so on) the level shown is the **size-weighted average** of the levels of the rows inside it, using current-year size as the weight and the scores Reported = 4, High = 3, Medium = 2, Low = 1, rounded to the nearest level.

### 3. Company revenue by year

Revenue you enter (or that is added up from quarters, section 5) is used as given. Everything else is estimated:

- **Years between two reported years** are filled with steady growth between them, the same rule as in section 1.
- **Years after the last reported year** (up to the end of the timeline) and **before the first** follow the **market index** of the company: the growth of the markets it sells into. The index for a year is the sum, over the company's revenue-split cells, of `share of the company in that cell x market size of that cell`. In plain terms: if the markets the company sells into grow 6% in a year, the company's revenue is assumed to grow 6% too. This is an assumption of "holding market share steady", and is why such years are labelled estimates or forecasts with low confidence. (A company that reports quarterly is projected by its own quarterly trend, section 5, up to the end of the current year; years after that follow the market index.)
- **Company pages** show every year up to the current year. Where a company has no figures yet for a year, the page still shows it, marked **E** with low confidence: revenue from the market-index rule above, **EBITDA at the company's latest reported margin** (EBITDA = revenue x that margin), and every other line (gross margin, net income, capex, employees) left blank rather than guessed. The employee headline on the page keeps the latest headcount you reported.
- Other ratios are plain arithmetic: **growth** = revenue / previous year's revenue - 1 (shown only when the previous year is also on the page); **EBITDA margin** = EBITDA / revenue.

### 4. A company inside a selection (country, sub-sector, vertical)

Each company has a revenue split by country, by sub-sector and by vertical, in percent (each is scaled to add to 100). The dashboard needs revenue for combinations, which you do not enter, so it assumes the three splits are **independent**:

`share of a cell = % in that country x % in that sub-sector x % in that vertical`

A company with 60% of revenue in the US, 70% in software and 50% in healthcare is therefore treated as earning 0.6 x 0.7 x 0.5 = 21% of its revenue from US software for healthcare. **Revenue in a selection** is the company's revenue times the sum of the shares of the cells that match. This is the main simplification in the dashboard; if you have the true three-way split for a company, make it more accurate by entering a split that reflects it.

### 5. Quarterly company data

Market sizes are annual. A company can optionally report by quarter, and then:

- **A year's financials = the sum of its four quarters** (revenue, EBITDA, net income, capex). Gross margin and employees still come from the annual entry if you made one.
- **Quarters you have not entered are projected**, from the first quarter you entered to the end of the current year:
  1. Growth factor `g` = the latest four reported quarters / the same four quarters a year earlier (using the ones that have a year-earlier figure), limited to between 0.5x and 2x.
  2. Projected quarter = **the same quarter a year earlier x g** (the year-earlier figure may itself be a projection).
  3. If there is no year-earlier figure, or no comparison to take `g` from, the projected quarter simply **repeats the quarter before it**.
  4. EBITDA, net income and capex in a projected quarter = projected revenue x the share of revenue they had over the latest four reported quarters (left blank if any of those quarters lacks the figure).
  *Example: Q1 to Q3 2026 are 110 each against 100 each a year earlier, and Q4 2025 was 100. Then g = 330 / 300 = 1.1 and Q4 2026 = 100 x 1.1 = 110, so 2026 = 440.*
- The quarterly table on a company page shows reported quarters plus projected ones up to the current quarter (marked **E**). **YoY growth** compares with the same quarter a year earlier, **QoQ growth** with the quarter before.
- **Confidence of a year built from quarters** = the lowest level among its reported quarters, but no higher than **High** if one quarter was projected, **Medium** if two, **Low** if three or four.

### 6. Confidence levels you do not set

| Figure | Level when you have not set one |
|---|---|
| Market row | Medium (`CONFIDENCE_DEFAULT_MARKET`) |
| Company year, entered annually | Reported up to the "annual data reported to" year, otherwise High |
| Company quarter | Reported up to the "company quarters reported to" quarter, otherwise High |
| Year with no figures (extrapolated, section 3) | Low |
| Projected quarter | Low |
| Company revenue on the dashboard | The level of its current-year figures (Low if there are none) |

### 7. Timeline

"As of" (year and quarter) sets the **headline year**; "reported to" dates decide which periods are A or E (the Timeline section above); forecasts run to the "forecast to" year. Advancing only moves "as of" and the forecast end; it never changes a number you entered. New years appear through the rules in sections 1 and 3 until you enter data for them.

### 8. Small things that are also calculated

- **Heatmap shading** = the cell's current-year size / the largest cell on the grid.
- **Peer companies** on a company page: each other company scores 2 for every shared sub-sector, 1 for every shared vertical, and 2 more if their main sub-sector is the same; the five highest scores (ties by revenue) are shown.
- **Companies active** = the number of companies with revenue in the current selection.
- **News on a dashboard slice**: items for the exact selection first; if there are too few, it widens step by step (vertical, then sub-sector, then country).

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
timeline.py     as-of period, reported-to dates, forecast horizon
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
