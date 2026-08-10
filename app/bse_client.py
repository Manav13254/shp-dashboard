"""
BSE shareholding-pattern client using BSE's confirmed internal REST API.

Confirmed endpoint (found via DevTools on Sharehold_Search.aspx):
  GET https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w
  Params:
    scripcode  - BSE scrip code, e.g. "500325" for Reliance
    flag       - time range: 1=latest, 2=3m, 3=6m, 4=9m, 5=1y, 6=1y, 7=custom
                 Use flag=6 to get last 1 year (the widest standard window)
    indtype    - "ALL" always

Response JSON has a key "Table" containing a list of filing dicts. Each dict:
  {
    "SCRIP_CD":      500325,
    "SCRIP_NAME":    "RELIANCE INDUSTRIES LTD.",
    "EndDate":       "30/06/2026",     # quarter-end date
    "broadcastTime": "01/08/2026 11:30:05",
    "XBRLAttachment": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/xxx.xml"
  }

BSE's API requires browser-like headers (Referer, Origin, User-Agent) or it
returns 403. This module uses a plain `requests.Session` pre-loaded with those
headers. No external `bse` library needed for this API.
"""

import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# ── confirmed endpoint ──────────────────────────────────────────────────────
BSE_SHP_API   = "https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w"
BSE_BASE_URL  = "https://www.bseindia.com"
BSE_REFERER   = "https://www.bseindia.com/corporates/Sharehold_Search.aspx"

# flag values for the `flag` query param
FLAG_LAST_1Y = "6"   # "Last 1 year" dropdown option - widest standard window

# ── headers BSE requires ────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": BSE_REFERER,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}


def make_bse_session() -> requests.Session:
    """
    Return a requests.Session pre-loaded with the headers BSE's API needs.
    Reuse this session across all calls to benefit from connection pooling
    and any cookies BSE's server sets.
    """
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def _parse_bse_date(date_str: str | None) -> str | None:
    """
    Convert BSE's DD/MM/YYYY or DD/MM/YYYY HH:MM:SS date strings to
    ISO-8601 (YYYY-MM-DD) for consistent storage/comparison.
    Returns the original string unchanged if it can't be parsed.
    """
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # fallback: return as-is


def get_shareholding_filings(
    session: requests.Session,
    scrip_code: str,
    flag: str = FLAG_LAST_1Y,
    max_filings: int = 2,
) -> list[dict]:
    """
    Fetch the latest shareholding-pattern filings for a BSE scrip code.

    Returns a list of dicts (latest-first, up to `max_filings`):
      [
        {
          "submissionDate": "2026-08-01",    # ISO date
          "endDate":        "2026-06-30",    # quarter-end ISO date
          "xbrl":           "https://www.bseindia.com/xml-data/corpfiling/AttachLive/xxx.xml",
          "company_name":   "RELIANCE INDUSTRIES LTD.",
        },
        ...
      ]

    Returns an empty list if the API call fails or returns no data.
    BSE's `Table` list is already newest-first.
    """
    params = {
        "scripcode": str(scrip_code),
        "flag": flag,
        "indtype": "ALL",
    }

    try:
        resp = session.get(BSE_SHP_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        logger.warning("BSE API HTTP error for scrip %s: %s", scrip_code, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("BSE API request failed for scrip %s: %s", scrip_code, e)
        return []
    except ValueError as e:
        logger.warning("BSE API non-JSON response for scrip %s: %s", scrip_code, e)
        return []

    rows = data.get("Table", [])
    if not rows:
        logger.debug("BSE API returned empty Table for scrip %s", scrip_code)
        return []

    filings = []
    for row in rows[:max_filings]:
        xbrl_url = (row.get("XBRLAttachment") or "").strip()
        if not xbrl_url:
            # Some filings have no attachment (e.g. older ones without XBRL).
            # Skip them; we need the XBRL to extract percentages.
            continue

        # XBRLAttachment is a relative path like /XBRLFILES/...
        # Prepend the base URL when there's no scheme.
        if xbrl_url.startswith("/"):
            xbrl_url = BSE_BASE_URL + xbrl_url

        # Confirmed live field name is "Company_NAme" (note capital N)
        company = (
            row.get("Company_NAme") or row.get("SCRIP_NAME") or row.get("company_name") or ""
        ).strip()

        filings.append({
            "submissionDate": row.get("broadcastTime"),   # keep raw string; scraper stores as-is
            "endDate":        _parse_bse_date(row.get("EndDate")),
            "xbrl":           xbrl_url,
            "company_name":   company,
        })

    return filings


# ── BSE equity master list ──────────────────────────────────────────────────

BSE_EQUITY_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)


def get_all_bse_equity_symbols(session: requests.Session | None = None) -> list[dict]:
    """
    Fetch BSE's full active-equity scrip master list.

    Returns [{
        "scrip_code": "500325",
        "symbol":     "RELIANCE",
        "name":       "Reliance Industries Ltd",
        "isin":       "INE002A01018",
    }, ...].

    Uses `session` if provided; otherwise creates a temporary one.
    """
    own_session = session is None
    if own_session:
        session = make_bse_session()

    try:
        resp = session.get(BSE_EQUITY_LIST_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Failed to fetch BSE equity master list: %s", e)
        return []
    finally:
        if own_session:
            session.close()

    # BSE returns {"Table": [...]} or the list directly depending on version
    rows = data if isinstance(data, list) else data.get("Table", [])

    # Debug: print first row keys so we can verify field names in production
    if rows:
        logger.debug("BSE equity list first row keys: %s", list(rows[0].keys()))

    results = []
    for row in rows:
        # Live-confirmed field names from BSE equity list API:
        # SCRIP_CD, scrip_id (ticker symbol), Scrip_Name (full name), ISIN_NUMBER
        scrip_code = str(
            row.get("SCRIP_CD") or row.get("Scrip_Code") or row.get("scripcode") or ""
        ).strip()
        symbol = (
            row.get("scrip_id") or row.get("SCRIP_ID") or
            row.get("SC_NAME") or ""
        ).strip()
        name = (
            row.get("Scrip_Name") or row.get("SCRIP_NAME") or
            row.get("Comp_Name") or row.get("Company_NAme") or
            row.get("Issuer_Name") or symbol
        ).strip()
        isin = (
            row.get("ISIN_NUMBER") or row.get("Isin_Number") or row.get("isin") or ""
        ).strip()
        if scrip_code:
            results.append({
                "scrip_code": scrip_code,
                "symbol":     symbol or scrip_code,
                "name":       name,
                "isin":       isin,
            })

    logger.info("BSE equity master: %d scrips loaded", len(results))
    return results
