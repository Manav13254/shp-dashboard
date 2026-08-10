"""Debug: test iXBRL regex against the actual tag snippet from BSE"""
import sys, re
sys.stdout.reconfigure(encoding="utf-8")

# Exact snippet from BSE's SBI filing (confirmed from probe)
sample = (
    "<ix:nonFraction name='in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares' "
    "contextRef='ShareholdingOfPromoterAndPromoterGroup_ContextI' decimals='INF' "
    "unitRef='pure' scale='-2'>55.47</ix:nonFraction>"
)

SHP_TAG = "ShareholdingAsAPercentageOfTotalNumberOfShares"
_Q    = r"""['"]"""
_ATTR = r"""(?:[^>]*?)"""

# Pattern: name first, then contextRef, scale optional anywhere after
PATTERN = re.compile(
    rf"""<ix:nonFraction"""
    rf"""{_ATTR}"""
    rf"""name={_Q}[^'"]*:{re.escape(SHP_TAG)}{_Q}"""
    rf"""{_ATTR}"""
    rf"""contextRef={_Q}([^'"]+){_Q}"""
    rf"""{_ATTR}"""
    rf"""(?:scale={_Q}([^'"]*){_Q})?"""
    rf"""{_ATTR}"""
    rf""">([^<]+)</ix:nonFraction>""",
    re.DOTALL | re.IGNORECASE,
)

m = PATTERN.search(sample)
if m:
    print(f"Match groups: ctx={m.group(1)!r}  scale={m.group(2)!r}  val={m.group(3)!r}")
else:
    print("NO MATCH")

# Try a simpler approach - just extract scale separately
print()
print("Simple scale extraction:")
scale_m = re.search(r"""scale=['"]([^'"]+)['"]""", sample)
ctx_m   = re.search(r"""contextRef=['"]([^'"]+)['"]""", sample)
val_m   = re.search(r""">([^<]+)</ix:nonFraction>""", sample)
print(f"  ctx={ctx_m.group(1) if ctx_m else None}")
print(f"  scale={scale_m.group(1) if scale_m else None}")
print(f"  val={val_m.group(1) if val_m else None}")
if scale_m and val_m:
    v = float(val_m.group(1)) * (10 ** int(scale_m.group(1)))
    print(f"  computed fraction={v}")
