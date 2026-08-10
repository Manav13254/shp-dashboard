"""
Parses SEBI/BSE shareholding-pattern XBRL files and extracts the four numbers
our dashboard needs:

  - Promoter & Promoter Group %
  - Foreign Institutions (FII/FPI) %
  - Domestic Institutions (DII) %
  - Resident individuals holding <= Rs 2 lakh (our "Retail") %

SUPPORTED FORMATS
-----------------
1. Raw XML XBRL  (NSE filings):  standard <in-bse-shp:Tag contextRef="...">value</...>
   Uses ElementTree parsing. Values stored as plain fractions (0.5547 == 55.47%).

2. Inline iXBRL HTML (BSE filings, confirmed live):
   Uses <ix:nonFraction name='in-bse-shp:Tag' contextRef='...' scale='-2'>55.47</ix:nonFraction>
   Important: BSE iXBRL uses SINGLE-QUOTE attributes, not double quotes.
   scale='-2' means the stored value is already in % form (55.47 = 55.47%).
   We convert to fraction by dividing by 100.

All returned values are fractions (multiply by 100 at display time).
Missing categories return None.
"""

import re
from xml.etree import ElementTree as ET

# ── Tag name we're looking for in both formats ────────────────────────────────
SHP_TAG = "ShareholdingAsAPercentageOfTotalNumberOfShares"

# ── contextRef → our field name (same IDs used in both NSE XML and BSE iXBRL) ─
CONTEXT_TO_FIELD = {
    "ShareholdingOfPromoterAndPromoterGroup_ContextI": "promoter_pct",
    "InstitutionsForeign_ContextI":                    "fii_pct",
    "InstitutionsDomestic_ContextI":                   "dii_pct",
    "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh_ContextI": "retail_pct",
}

# ── iXBRL parsing helpers ────────────────────────────────────────────────────
#
# BSE iXBRL tags look like (with SINGLE-QUOTE attributes):
#   <ix:nonFraction name='in-bse-shp:ShareholdingAsAPercentage...'
#                   contextRef='ShareholdingOfPromoterAndPromoterGroup_ContextI'
#                   decimals='INF' unitRef='pure' scale='-2'>55.47</ix:nonFraction>
#
# Strategy: find all <ix:nonFraction ...> blocks that reference our tag,
# then extract contextRef / scale / value with 3 simple targeted regexes.
# A single complex regex with optional groups fails to capture scale reliably.

_Q = r"""['"]"""  # single or double quote

# Finds each <ix:nonFraction ...>VALUE</ix:nonFraction> block that contains our tag
_BLOCK_RE = re.compile(
    rf"""(<ix:nonFraction\b[^>]*?{re.escape(SHP_TAG)}[^>]*>)(.*?)</ix:nonFraction>""",
    re.DOTALL | re.IGNORECASE,
)

# Targeted sub-regexes applied inside each block
_CTX_RE   = re.compile(rf"""contextRef={_Q}([^'"]+){_Q}""",   re.IGNORECASE)
_SCALE_RE = re.compile(rf"""scale={_Q}([^'"]+){_Q}""",        re.IGNORECASE)


def _parse_ixbrl(text: str) -> dict:
    """Parse inline iXBRL (BSE HTML format) and return field dict."""
    result = {v: None for v in CONTEXT_TO_FIELD.values()}

    for m in _BLOCK_RE.finditer(text):
        open_tag = m.group(1)   # the <ix:nonFraction ...> opening tag
        raw_val  = m.group(2).strip()

        ctx_m   = _CTX_RE.search(open_tag)
        scale_m = _SCALE_RE.search(open_tag)
        if not ctx_m:
            continue

        field = CONTEXT_TO_FIELD.get(ctx_m.group(1))
        if field is None:
            continue

        val = _apply_scale(raw_val, scale_m.group(1) if scale_m else None)
        if val is not None:
            result[field] = val

    return result


def _apply_scale(value_str: str, scale_str: str | None) -> float | None:
    """
    Apply the iXBRL `scale` exponent to get the actual numeric value,
    then convert to a 0–1 fraction for consistent storage.

    scale='-2' means the raw value (e.g. 55.47) is already in percentage form
    (i.e. multiply by 10^-2 to get the real number 0.5547).  We want fractions,
    so: fraction = raw_value * 10^scale.

    If scale is missing/zero, assume the value is already a fraction (NSE style).
    """
    try:
        v = float(value_str.strip())
    except (ValueError, AttributeError):
        return None

    if scale_str:
        try:
            exponent = int(scale_str.strip())
            v = v * (10 ** exponent)
        except ValueError:
            pass

    # Normalize to fraction: shareholding percentage for a category is always <= 1.0.
    # If the XML reported a raw percentage (e.g. 23.28 instead of 0.2328), convert it to a fraction.
    if v > 1.0:
        v = v / 100.0

    return v


def _parse_ixbrl(text: str) -> dict:
    """Parse inline iXBRL (BSE HTML format) and return field dict."""
    result = {v: None for v in CONTEXT_TO_FIELD.values()}

    for m in _BLOCK_RE.finditer(text):
        open_tag = m.group(1)   # the <ix:nonFraction ...> opening tag
        raw_val  = m.group(2).strip()

        ctx_m   = _CTX_RE.search(open_tag)
        scale_m = _SCALE_RE.search(open_tag)
        if not ctx_m:
            continue

        field = CONTEXT_TO_FIELD.get(ctx_m.group(1))
        if field is None:
            continue

        val = _apply_scale(raw_val, scale_m.group(1) if scale_m else None)
        if val is not None:
            result[field] = val

    return result



def _parse_raw_xml(text: str) -> dict:
    """Parse raw XML XBRL (NSE format) using ElementTree."""
    result = {v: None for v in CONTEXT_TO_FIELD.values()}

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return result

    for el in root.iter():
        localname = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if localname != SHP_TAG:
            continue

        ctx = el.attrib.get("contextRef")
        field = CONTEXT_TO_FIELD.get(ctx)
        if field is None:
            continue

        raw = (el.text or "").strip()
        if not raw:
            continue

        # NSE raw XML: values are already fractions (0.5547 == 55.47%)
        # scale attribute rarely present in NSE files, but handle it anyway
        scale = el.attrib.get("scale")
        val = _apply_scale(raw, scale)
        if val is not None:
            result[field] = val

    return result


def parse_xbrl(xml_bytes_or_str) -> dict:
    """
    Parse XBRL content (bytes or str) and return a dict:
      {"promoter_pct": 0.5547, "fii_pct": 0.12, "dii_pct": 0.18,
       "retail_pct": 0.07, "submission_date": None}

    Automatically detects iXBRL (BSE HTML) vs raw XML (NSE) by looking
    for the <ix:nonFraction signature in the content.

    Missing fields are returned as None.
    """
    if isinstance(xml_bytes_or_str, bytes):
        xml_bytes_or_str = xml_bytes_or_str.decode("utf-8", errors="replace")

    text = xml_bytes_or_str

    # Detect format: iXBRL has the ix: namespace signature
    if "ix:nonFraction" in text or "ix:nonNumeric" in text:
        result = _parse_ixbrl(text)
    else:
        result = _parse_raw_xml(text)

    # Add submission_date placeholder (filled in by caller)
    result.setdefault("submission_date", None)
    return result


def extract_symbol_and_date(xml_bytes_or_str) -> dict:
    """Best-effort extraction of Symbol + DateOfReport, useful for sanity checks."""
    if isinstance(xml_bytes_or_str, bytes):
        xml_bytes_or_str = xml_bytes_or_str.decode("utf-8", errors="replace")

    symbol_match = re.search(r"<[^:<>]+:Symbol[^>]*>([^<]+)<", xml_bytes_or_str)
    date_match   = re.search(r"<[^:<>]+:DateOfReport[^>]*>([^<]+)<", xml_bytes_or_str)

    # iXBRL variant (name= attribute style)
    if not symbol_match:
        symbol_match = re.search(r"""name=['"][^'"]*:Symbol['"][^>]*>([^<]+)<""", xml_bytes_or_str)
    if not date_match:
        date_match = re.search(r"""name=['"][^'"]*:DateOfReport['"][^>]*>([^<]+)<""", xml_bytes_or_str)

    return {
        "symbol":        symbol_match.group(1).strip() if symbol_match else None,
        "date_of_report": date_match.group(1).strip() if date_match else None,
    }
