#!/usr/bin/env python3
"""
Look up FPI scores for pubs by searching VOA rateable values.

Searches the GOV.UK business rates service by postcode, matches pubs by
name, retrieves 2023 and 2026 rateable values, and computes FPI scores
using our formula: score = clamp(round(pct_change * 0.6), 0, 100).

Three modes:
  1. Automated: scrape GOV.UK for each pub's rateable value % change
  2. Interactive: manually enter RV values after looking them up in browser
  3. URLs: print GOV.UK links grouped by postcode for browser lookup

Usage:
    python lookup_fpi.py                 # Auto-search GOV.UK for all pubs
    python lookup_fpi.py --interactive   # Enter RV values manually per pub
    python lookup_fpi.py --urls          # Print GOV.UK lookup URLs
    python lookup_fpi.py --pub "Hydrant" # Search a single pub

Requirements (for auto mode):
    pip install requests beautifulsoup4
"""

import argparse
import csv
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FPI_LOOKUP_CSV = SCRIPT_DIR / "fpi_lookup.csv"

# GOV.UK business rates search
VOA_SEARCH_URL = "https://www.tax.service.gov.uk/business-rates-find"
VOA_POSTCODE_URL = f"{VOA_SEARCH_URL}/list-valuations-by-postcode"

# Pubs missing FPI scores — name | full postcode
MISSING_PUBS = [
    ("3 Locks Brewing", "NW1 8JY"),
    ("Albert Schloss", "W1D 7EU"),
    ("Beer Merchants Tap", "E9 5EN"),
    ("Cannick Taps", "EC4N 5AD"),
    ("Clapton Craft", "SW11 1TT"),
    ("Craft Beer Co", "EC3A 5BU"),
    ("Garlic & Shots", "W1D 4RD"),
    ("Holy Tavern", "EC1M 5UQ"),
    ("Howling Hops Tank Bar", "E9 5EN"),
    ("Hydrant Pub", "EC3R 8BG"),
    ("Longarm Brewery", "EC2A 2DX"),
    ("Magpie & Stump", "EC4M 7EP"),
    ("Project Orange", "SW11 1TT"),
    ("Radio City Social", "CM1 1TS"),  # Chelmsford, 35-36 Viaduct Road
    ("Satan's Whiskers", "E2 9RA"),
    ("Seething Lane Tap", "EC3N 4AX"),
    ("Strongroom Bar", "EC2A 3SQ"),
    ("Tap East", "E20 1EJ"),
    ("The Aldgate Tap", "EC3N 1AF"),
    ("The Ale House", "CM1 1TS"),  # Chelmsford, 24-26 Viaduct Road
    ("The Blue Lion", "CM2 7BT"),  # Great Baddow, Tabors Hill
    ("The Broadleaf", "EC2N 1HN"),
    ("The Clapham Tap", "SW4 6ED"),
    ("The Coach and Horses", "EC4Y 8BH"),
    ("The Craft Beer Co. (Spitalfields)", "E1 6NF"),
    ("The Ivory Peg", "CM2 0SW"),
    ("The Last Judgement", "WC2A 1DT"),
    ("The Light Bar", "E1 6PJ"),
    ("The Magpie and Stump", "EC4M 7EJ"),
    ("The Smithfield Tavern", "EC1M 6HR"),
    ("The St Bride's Tavern", "EC4Y 8EQ"),
    ("The White Horse", "CM2 7HH"),  # Great Baddow, 78 High Street
    ("Walrus & Carpenter", "EC3R 8BU"),
    ("Well & Bucket", "E2 7DG"),
    ("Wood Street", "EC2Y 5EJ"),  # 53 Fore Street, Barbican
]


def normalise(name):
    """Normalise a pub name for fuzzy matching."""
    name = name.upper().strip()
    for prefix in ("THE ", "YE OLDE ", "YE "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = name.replace("&", "AND").replace("'", "").replace("\u2019", "")
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def compute_fpi_score(pct_change):
    """Compute FPI score (0-100) from rateable value percentage change.

    Piecewise linear formula:
      <= 0%:   score = 0
      0-100%:  score = round(pct * 0.6)
      > 100%:  score = min(100, 60 + round((pct - 100) * 0.3))
    """
    if pct_change <= 0:
        return 0
    if pct_change <= 100:
        return int(pct_change * 0.6 + 0.5)
    return min(100, 60 + int((pct_change - 100) * 0.3 + 0.5))


def fpi_category(pct_change):
    """Return FPI category label based on raw percentage change."""
    if pct_change <= 0:
        return "somehow fine"
    if pct_change < 50:
        return "feeling it"
    if pct_change < 100:
        return "struggling"
    score = compute_fpi_score(pct_change)
    if score < 100:
        return "fucked"
    return "absolutely fucked"


# ---------------------------------------------------------------------------
# Automated VOA lookup (requires requests + beautifulsoup4)
# ---------------------------------------------------------------------------

def _get_session():
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session


def search_voa_by_postcode(session, postcode):
    """Search GOV.UK business rates by postcode. Returns list of {text, link}."""
    import requests as req
    from bs4 import BeautifulSoup

    try:
        resp = session.get(
            VOA_POSTCODE_URL,
            params={"postcode": postcode, "startPage": "1"},
            timeout=15,
        )
        resp.raise_for_status()
    except req.RequestException as e:
        print(f"    Error searching {postcode}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # GOV.UK lists properties in table rows or summary lists
    for row in soup.select("tr, .govuk-summary-list__row, li.search-result"):
        text = row.get_text(" ", strip=True)
        link_el = row.select_one("a[href]")
        link = link_el["href"] if link_el else ""
        if link and not link.startswith("http"):
            link = f"https://www.tax.service.gov.uk{link}"
        results.append({"text": text, "link": link})

    for link_el in soup.select("a.govuk-link"):
        href = link_el.get("href", "")
        text = link_el.get_text(strip=True)
        if "valuation" in href.lower() or "property" in href.lower():
            if href and not href.startswith("http"):
                href = f"https://www.tax.service.gov.uk{href}"
            results.append({"text": text, "link": href})

    return results


def get_property_values(session, url):
    """Fetch a property page and extract 2023/2026 rateable values."""
    import requests as req
    from bs4 import BeautifulSoup

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except req.RequestException as e:
        print(f"    Error fetching {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    values = {}
    rv_patterns = [
        (r"(?:2023|current)\s+(?:list\s+)?(?:rateable\s+value|RV)\s*[:\s]*£([\d,]+)", "rv_2023"),
        (r"(?:2026|draft)\s+(?:list\s+)?(?:rateable\s+value|RV)\s*[:\s]*£([\d,]+)", "rv_2026"),
        (r"Rateable\s+value\s*£([\d,]+)", "rv_2023"),
    ]
    for pattern, key in rv_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            values.setdefault(key, int(m.replace(",", "")))

    return values if values else None


def find_pub_in_results(pub_name, results):
    """Find a pub name match in search results."""
    target = normalise(pub_name)
    for result in results:
        text_norm = normalise(result["text"])
        if target in text_norm or any(
            word in text_norm for word in target.split() if len(word) >= 4
        ):
            return result
    return None


def auto_lookup(pub_name, postcode, session):
    """Auto-look up a pub via GOV.UK. Returns {fpi_score, fpi_category, pct_change} or None."""
    print(f"  Searching: {pub_name} ({postcode})")

    results = search_voa_by_postcode(session, postcode)
    if not results:
        print(f"    No VOA results for {postcode}")
        return None

    match = find_pub_in_results(pub_name, results)
    if not match:
        print(f"    No name match in {len(results)} results")
        for r in results[:5]:
            print(f"      - {r['text'][:80]}")
        return None

    print(f"    Matched: {match['text'][:80]}")

    if match.get("link"):
        values = get_property_values(session, match["link"])
        if values and "rv_2023" in values and "rv_2026" in values:
            pct = ((values["rv_2026"] - values["rv_2023"]) / values["rv_2023"]) * 100
            score = compute_fpi_score(pct)
            cat = fpi_category(pct)
            print(f"    RV 2023=£{values['rv_2023']:,} → 2026=£{values['rv_2026']:,}"
                  f" ({pct:+.1f}%) → FPI={score} ({cat})")
            return {"fpi_score": score, "fpi_category": cat, "pct_change": pct}

    print(f"    Could not extract rateable values")
    return None


# ---------------------------------------------------------------------------
# Interactive mode — user enters RV values from browser
# ---------------------------------------------------------------------------

def interactive_entry(pubs_to_search, existing):
    """Prompt user to enter 2023 and 2026 rateable values for each pub.

    Computes FPI from the % change. User looks up values on GOV.UK.
    """
    print("Interactive mode: enter rateable values from GOV.UK")
    print("Look up each pub at:")
    print("  https://www.tax.service.gov.uk/business-rates-find/search\n")
    print("For each pub, enter the 2023 and 2026 rateable values.")
    print("Press Enter to skip, or 'q' to quit.\n")

    added = 0
    for name, postcode in pubs_to_search:
        print(f"  {name} ({postcode})")
        try:
            rv23_str = input("    2023 RV (£): ").strip().replace(",", "").replace("£", "")
        except (EOFError, KeyboardInterrupt):
            print("\n\nStopped.")
            break

        if rv23_str.lower() == "q":
            break
        if not rv23_str:
            print("    Skipped\n")
            continue

        try:
            rv23 = int(rv23_str)
        except ValueError:
            print("    Invalid number, skipping\n")
            continue

        try:
            rv26_str = input("    2026 RV (£): ").strip().replace(",", "").replace("£", "")
        except (EOFError, KeyboardInterrupt):
            print("\n\nStopped.")
            break

        if not rv26_str:
            print("    Skipped\n")
            continue

        try:
            rv26 = int(rv26_str)
        except ValueError:
            print("    Invalid number, skipping\n")
            continue

        if rv23 == 0:
            print("    2023 RV is 0, can't compute % change\n")
            continue

        pct = ((rv26 - rv23) / rv23) * 100
        score = compute_fpi_score(pct)
        cat = fpi_category(pct)

        existing[name] = {
            "pub_name": name,
            "fpi_score": str(score),
            "fpi_category": cat,
        }
        added += 1
        print(f"    → {pct:+.1f}% change → FPI {score} ({cat})\n")

    return added


# ---------------------------------------------------------------------------
# URL generator for manual browser lookup
# ---------------------------------------------------------------------------

def generate_urls(pubs_to_search):
    """Print GOV.UK search URLs grouped by postcode."""
    print("VOA lookup URLs — search each postcode on GOV.UK:\n")

    by_postcode = {}
    for name, postcode in pubs_to_search:
        by_postcode.setdefault(postcode, []).append(name)

    for postcode in sorted(by_postcode):
        names = by_postcode[postcode]
        encoded = postcode.replace(" ", "+")
        url = (f"https://www.tax.service.gov.uk/business-rates-find/"
               f"list-valuations-by-postcode?postcode={encoded}&startPage=1")
        print(f"  {postcode}:")
        for n in names:
            print(f"    - {n}")
        print(f"    {url}\n")

    print(f"Find the pub, note the 2023 and 2026 rateable values,")
    print(f"then run: python lookup_fpi.py --interactive")


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_existing_lookup():
    lookup = {}
    if FPI_LOOKUP_CSV.exists():
        with open(FPI_LOOKUP_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lookup[row["pub_name"]] = row
    return lookup


def save_lookup(lookup):
    with open(FPI_LOOKUP_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pub_name", "fpi_score", "fpi_category"])
        writer.writeheader()
        for name in sorted(lookup.keys()):
            writer.writerow(lookup[name])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Look up FPI scores for pubs via VOA rateable values"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show results without writing to CSV")
    parser.add_argument("--pub", type=str,
                        help="Look up a single pub by name")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between requests (default: 1.0)")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Enter rateable values manually per pub")
    parser.add_argument("--urls", action="store_true",
                        help="Print GOV.UK lookup URLs for each postcode")
    args = parser.parse_args()

    existing = load_existing_lookup()

    # Determine which pubs still need lookup
    if args.pub:
        pubs_to_search = [(n, p) for n, p in MISSING_PUBS if args.pub.lower() in n.lower()]
        if not pubs_to_search:
            print(f"Pub '{args.pub}' not found in MISSING_PUBS list")
            sys.exit(1)
    else:
        pubs_to_search = [(n, p) for n, p in MISSING_PUBS if n not in existing]

    if not pubs_to_search and not args.urls:
        print(f"All {len(MISSING_PUBS)} pubs already have FPI scores!")
        return

    # URL mode: just print links
    if args.urls:
        generate_urls(pubs_to_search if pubs_to_search else MISSING_PUBS)
        return

    print(f"Existing FPI lookup: {len(existing)} pubs")
    print(f"Pubs to look up: {len(pubs_to_search)}\n")

    # Interactive mode: user enters RV values
    if args.interactive:
        added = interactive_entry(pubs_to_search, existing)
        if added > 0:
            save_lookup(existing)
            print(f"Added {added} pubs. Updated {FPI_LOOKUP_CSV} ({len(existing)} total)")
        else:
            print("No scores added.")
        return

    # Auto mode: scrape GOV.UK
    try:
        import requests  # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        print("Auto mode requires: pip install requests beautifulsoup4")
        print("Or use --interactive to enter values manually,")
        print("or --urls to get browser links.")
        sys.exit(1)

    session = _get_session()
    found = 0
    not_found = []

    for i, (name, postcode) in enumerate(pubs_to_search):
        if i > 0:
            time.sleep(args.delay)

        result = auto_lookup(name, postcode, session)
        if result:
            found += 1
            if not args.dry_run:
                existing[name] = {
                    "pub_name": name,
                    "fpi_score": str(result["fpi_score"]),
                    "fpi_category": result["fpi_category"],
                }
        else:
            not_found.append((name, postcode))
        print()

    print(f"Results: {found} found, {len(not_found)} not found")

    if not_found:
        print(f"\nNot found ({len(not_found)}):")
        for name, postcode in not_found:
            print(f"  - {name} ({postcode})")
        print(f"\nFor unfound pubs, try:")
        print(f"  python lookup_fpi.py --urls        # get browser links")
        print(f"  python lookup_fpi.py --interactive  # enter RV values manually")

    if not args.dry_run and found > 0:
        save_lookup(existing)
        print(f"\nUpdated {FPI_LOOKUP_CSV} ({len(existing)} total pubs)")
    elif args.dry_run and found > 0:
        print(f"\nDry run — no changes written")


if __name__ == "__main__":
    main()
