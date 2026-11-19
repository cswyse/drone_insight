"""
Platform configuration and market taxonomy.

The platform is industry-agnostic. To adapt it to a specific market, edit this file:
rename the sub-sectors and verticals, adjust the countries, and change the brand.
Everything else (dashboard, updates feed, company pages) reads from here.
"""

# Timeline ---------------------------------------------------------------
YEARS = list(range(2021, 2032))   # 2021 to 2031: five years of forecast beyond the current year
LAST_ACTUAL = 2025        # fully reported
ESTIMATE_YEAR = 2026      # current year, estimate (today is Nov 2026)
FORECAST_FROM = 2027
TODAY = "2026-11-15"
SEED = 20261115

GLOBAL_BASE_2021 = 920.0  # US$ bn, total addressable market in the base year
BASE_GROWTH = 0.035

# Taxonomy ---------------------------------------------------------------
# weight = share of global market, growth = adjustment to base annual growth
COUNTRIES = [
    {"id": "us", "name": "United States", "region": "North America", "city": "New York", "lat": 40.7, "lon": -74.0, "weight": 0.26, "growth": 0.000, "exchange": "NYSE"},
    {"id": "cn", "name": "China", "region": "Asia-Pacific", "city": "Shanghai", "lat": 31.2, "lon": 121.5, "weight": 0.20, "growth": 0.015, "exchange": "SSE"},
    {"id": "de", "name": "Germany", "region": "Europe", "city": "Frankfurt", "lat": 50.1, "lon": 8.7, "weight": 0.08, "growth": -0.015, "exchange": "XETRA"},
    {"id": "jp", "name": "Japan", "region": "Asia-Pacific", "city": "Tokyo", "lat": 35.7, "lon": 139.7, "weight": 0.07, "growth": -0.020, "exchange": "TSE"},
    {"id": "uk", "name": "United Kingdom", "region": "Europe", "city": "London", "lat": 51.5, "lon": -0.1, "weight": 0.06, "growth": -0.005, "exchange": "LSE"},
    {"id": "in", "name": "India", "region": "Asia-Pacific", "city": "Mumbai", "lat": 19.1, "lon": 72.9, "weight": 0.06, "growth": 0.045, "exchange": "NSE"},
    {"id": "fr", "name": "France", "region": "Europe", "city": "Paris", "lat": 48.9, "lon": 2.4, "weight": 0.045, "growth": -0.010, "exchange": "EPA"},
    {"id": "br", "name": "Brazil", "region": "Latin America", "city": "São Paulo", "lat": -23.5, "lon": -46.6, "weight": 0.035, "growth": 0.010, "exchange": "B3"},
    {"id": "ca", "name": "Canada", "region": "North America", "city": "Toronto", "lat": 43.7, "lon": -79.4, "weight": 0.03, "growth": 0.000, "exchange": "TSX"},
    {"id": "nl", "name": "Netherlands", "region": "Europe", "city": "Amsterdam", "lat": 52.4, "lon": 4.9, "weight": 0.02, "growth": 0.005, "exchange": "AEX"},
    {"id": "sg", "name": "Singapore", "region": "Asia-Pacific", "city": "Singapore", "lat": 1.35, "lon": 103.8, "weight": 0.015, "growth": 0.020, "exchange": "SGX"},
    {"id": "ae", "name": "United Arab Emirates", "region": "Middle East", "city": "Dubai", "lat": 25.2, "lon": 55.3, "weight": 0.015, "growth": 0.030, "exchange": "ADX"},
]

SUBSECTORS = [
    {"id": "core-products", "name": "Core Products", "weight": 0.30, "growth": 0.000,
     "phrase": "core products and equipment"},
    {"id": "services-solutions", "name": "Services & Solutions", "weight": 0.26, "growth": 0.020,
     "phrase": "professional services and managed solutions"},
    {"id": "digital-platforms", "name": "Digital Platforms", "weight": 0.17, "growth": 0.070,
     "phrase": "software and digital platforms"},
    {"id": "infrastructure", "name": "Infrastructure & Assets", "weight": 0.15, "growth": 0.010,
     "phrase": "infrastructure and asset operations"},
    {"id": "components-inputs", "name": "Components & Inputs", "weight": 0.12, "growth": -0.005,
     "phrase": "components and specialised inputs"},
]

VERTICALS = [
    {"id": "financial-services", "name": "Financial Services", "weight": 0.20, "growth": 0.020},
    {"id": "healthcare", "name": "Healthcare & Life Sciences", "weight": 0.16, "growth": 0.030},
    {"id": "consumer", "name": "Consumer & Retail", "weight": 0.20, "growth": 0.000},
    {"id": "industrials", "name": "Industrials & Energy", "weight": 0.18, "growth": 0.010},
    {"id": "public-sector", "name": "Public Sector", "weight": 0.10, "growth": -0.005},
    {"id": "tmt", "name": "Technology, Media & Telecom", "weight": 0.16, "growth": 0.035},
]

NEWS_TYPES = ["Earnings", "M&A", "Partnership", "Product launch", "Expansion", "Leadership", "Investment", "Market"]


# Confidence levels for the figures on the dashboard, from most to least certain. You can rename the
# labels and rewrite the descriptions freely; keep the four ids (the code refers to them).
CONFIDENCE = [
    {"id": "reported", "name": "Reported", "short": "Reported",
     "desc": "Actual figures from filings, audited accounts or an official statistic."},
    {"id": "high", "name": "High-confidence estimate", "short": "High",
     "desc": "Estimate built on solid evidence, such as company guidance or several consistent sources."},
    {"id": "medium", "name": "Medium-confidence estimate", "short": "Medium",
     "desc": "Estimate based on partial data or reasonable assumptions."},
    {"id": "low", "name": "Low-confidence estimate", "short": "Low",
     "desc": "Rough estimate with limited evidence. Treat as indicative."},
]
CONFIDENCE_DEFAULT_MARKET = "medium"   # used for market sizes with no level set

CHART_YEARS_BACK, CHART_YEARS_AHEAD = 5, 5   # the top charts show this many years before and after the current year, however far the timeline moves
CAGR_YEARS = 5   # the growth columns: CAGR over the last 5 years up to the current year, and over the 5 years after it
