"""
Quick smoke test for the new BSE direct-API client.
Run from the project root:
    python test_bse.py

Tests 3 scrip codes:
  500325 - Reliance Industries (large cap, lots of filings)
  500112 - State Bank of India
  540777 - HDFC Bank
"""

import sys
import os
import pprint
import requests

# Force UTF-8 on Windows so print() doesn't crash on non-ASCII
sys.stdout.reconfigure(encoding="utf-8")

from app.bse_client import make_bse_session, get_shareholding_filings, get_all_bse_equity_symbols

TEST_SCRIPS = [
    ("500325", "Reliance Industries"),
    ("500112", "SBI"),
    ("540777", "HDFC Bank"),
]


def test_filings():
    print("\n" + "="*60)
    print("TEST 1: Shareholding filings API")
    print("="*60)

    session = make_bse_session()
    all_ok = True

    try:
        for scrip_code, label in TEST_SCRIPS:
            print(f"\n--- {label} ({scrip_code}) ---")

            # Debug: show raw response first
            params = {"scripcode": scrip_code, "flag": "6", "indtype": "ALL"}
            url = "https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w"
            try:
                raw = session.get(url, params=params, timeout=20)
                print(f"  HTTP {raw.status_code}  ({len(raw.content)} bytes)")
                if raw.status_code != 200:
                    print(f"  [FAIL] Non-200: {raw.text[:300]}")
                    all_ok = False
                    continue
                data = raw.json()
                table = data.get("Table", [])
                print(f"  Table rows: {len(table)}")
                if table:
                    print(f"  First row keys: {list(table[0].keys())}")
                    print(f"  First row sample:")
                    pprint.pprint(table[0], indent=4)
            except Exception as e:
                print(f"  [ERROR] Raw request failed: {e}")
                all_ok = False
                continue

            filings = get_shareholding_filings(session, scrip_code)

            if not filings:
                print(f"  [FAIL] No filings returned after parsing!")
                all_ok = False
                continue

            for i, f in enumerate(filings):
                print(f"  Filing #{i+1}:")
                print(f"    submissionDate : {f['submissionDate']}")
                print(f"    endDate        : {f['endDate']}")
                print(f"    company_name   : {f['company_name']}")
                print(f"    xbrl (first 80): {f['xbrl'][:80]}...")
            print(f"  [PASS] {len(filings)} filing(s) received")
    finally:
        session.close()

    return all_ok


def test_equity_list():
    print("\n" + "="*60)
    print("TEST 2: BSE equity master list (first 5 scrips)")
    print("="*60)

    # First: print raw JSON to see actual field names
    import requests as _req
    _s = make_bse_session()
    _url = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
            "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
    try:
        _r = _s.get(_url, timeout=30)
        _data = _r.json()
        _rows = _data if isinstance(_data, list) else _data.get("Table", [])
        if _rows:
            print(f"Equity list raw first row keys: {list(_rows[0].keys())}")
            pprint.pprint(_rows[0])
    except Exception as e:
        print(f"  Raw equity probe failed: {e}")
    finally:
        _s.close()

    session = make_bse_session()
    try:
        symbols = get_all_bse_equity_symbols(session)
    finally:
        session.close()

    if not symbols:
        print("[FAIL] Empty list returned!")
        return False

    print(f"Total scrips returned: {len(symbols)}")
    print("\nFirst 5:")
    for s in symbols[:5]:
        print(f"  {s['scrip_code']:>7}  {s['symbol']:<20}  {s['name']}")
    print("[PASS] Master list looks good")
    return True


def test_xbrl_parse(filing):
    """Download and parse the XBRL from the first filing of the first test scrip."""
    print("\n" + "="*60)
    print("TEST 3: XBRL download + parse")
    print("="*60)

    from app.xbrl_parser import parse_xbrl

    session = make_bse_session()
    url = filing["xbrl"]
    print(f"Downloading: {url[:80]}...")
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        print(f"HTTP {resp.status_code}, {len(resp.content)} bytes")
        result = parse_xbrl(resp.content)
        print("Parsed result:")
        pprint.pprint(result)
        if any(v is not None for v in result.values()):
            print("[PASS] XBRL parsed - at least one field extracted")
            return True
        else:
            print("[WARN] XBRL parsed but ALL fields are None - check context IDs in xbrl_parser.py")
            # Print a snippet of the raw XML to help debug
            snippet = resp.text[:2000]
            print("\n--- First 2000 chars of XBRL ---")
            print(snippet)
            return False
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False
    finally:
        session.close()


if __name__ == "__main__":
    ok1 = test_filings()

    # Use the first filing from Reliance for the XBRL test
    ok3 = False
    if ok1:
        session = make_bse_session()
        try:
            sample_filings = get_shareholding_filings(session, "500325")
        finally:
            session.close()

        if sample_filings:
            ok3 = test_xbrl_parse(sample_filings[0])
        else:
            print("\n[SKIP] Skipping XBRL test (no filings for 500325)")

    ok2 = test_equity_list()

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"  Filings API  : {'PASS' if ok1 else 'FAIL'}")
    print(f"  XBRL parse   : {'PASS' if ok3 else 'FAIL'}")
    print(f"  Equity list  : {'PASS' if ok2 else 'FAIL'}")

    sys.exit(0 if (ok1 and ok2) else 1)
