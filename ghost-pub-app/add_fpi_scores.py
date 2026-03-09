"""
Enrich pub_names.csv with FPI (Fucked Pub Index) scores from ismypubfucked.com.

Tries to auto-fetch FPI scores via the site's API. If that fails, falls back
to reading a manually-created fpi_lookup.csv file.

Output: Updates pub_names.csv with two new columns: fpi_score, fpi_category

Usage:
    python add_fpi_scores.py

    If auto-fetch fails, create fpi_lookup.csv with columns:
        pub_name,fpi_score,fpi_category
    e.g.:
        Cat & Mutton,47,struggling
        Crown & Shuttle,77,fucked

    To find the API endpoint yourself:
    1. Open ismypubfucked.com in Chrome
    2. Open DevTools (F12) > Network tab
    3. Search for a pub name
    4. Look at the XHR/Fetch requests to find the search endpoint
    5. Update API_SEARCH_URL below with the endpoint you find
"""

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PUB_NAMES_CSV = SCRIPT_DIR / "pub_names.csv"
FPI_LOOKUP_CSV = SCRIPT_DIR / "fpi_lookup.csv"

# Update this if you discover the actual API endpoint via browser DevTools.
# Common patterns for Next.js / Vercel apps:
API_SEARCH_URLS = [
    "https://www.ismypubfucked.com/api/search?q={query}",
    "https://www.ismypubfucked.com/api/pubs?search={query}",
    "https://www.ismypubfucked.com/api/pubs/search?q={query}",
]


def normalise_name(name):
    """Normalise a pub name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common prefixes
    for prefix in ["the ", "ye olde ", "ye "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Remove punctuation and extra spaces
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def try_api_fetch(pub_name):
    """Try to fetch FPI data from ismypubfucked.com API."""
    query = urllib.parse.quote(pub_name)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    for url_template in API_SEARCH_URLS:
        url = url_template.format(query=query)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return parse_api_response(data, pub_name)
        except Exception:
            continue
    return None


def parse_api_response(data, pub_name):
    """Try to extract FPI score from API response. Handles common shapes."""
    target = normalise_name(pub_name)

    # data could be a list of results or {"results": [...]} or {"pubs": [...]}
    results = data
    if isinstance(data, dict):
        for key in ("results", "pubs", "data", "items"):
            if key in data:
                results = data[key]
                break

    if not isinstance(results, list):
        return None

    for item in results:
        if not isinstance(item, dict):
            continue
        # Try to match by name
        item_name = item.get("name", item.get("pub_name", item.get("title", "")))
        if normalise_name(item_name) == target or target in normalise_name(item_name):
            score = item.get("fpi_score", item.get("score", item.get("fpi", None)))
            category = item.get("fpi_category", item.get("category", item.get("status", "")))
            if score is not None:
                return {"fpi_score": str(score), "fpi_category": category}
    return None


def load_manual_lookup():
    """Load manually-created FPI lookup CSV."""
    lookup = {}
    if not FPI_LOOKUP_CSV.exists():
        return lookup
    with open(FPI_LOOKUP_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = normalise_name(row.get("pub_name", ""))
            if name:
                lookup[name] = {
                    "fpi_score": row.get("fpi_score", ""),
                    "fpi_category": row.get("fpi_category", ""),
                }
    return lookup


def main():
    if not PUB_NAMES_CSV.exists():
        print(f"Error: {PUB_NAMES_CSV} not found. Run extract_pub_names.py first.")
        sys.exit(1)

    # Read existing pub data
    with open(PUB_NAMES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pubs = list(reader)

    if not pubs:
        print("No pubs found in CSV.")
        sys.exit(1)

    print(f"Loaded {len(pubs)} pubs from {PUB_NAMES_CSV}")

    # Step 1: Try API auto-fetch for the first pub to test connectivity
    print("\nTesting ismypubfucked.com API...")
    test_result = try_api_fetch(pubs[0]["pub_name"])
    api_works = test_result is not None

    if api_works:
        print("  API is reachable! Fetching scores for all pubs...\n")
    else:
        print("  API not reachable (expected if running remotely).")
        print(f"  Falling back to manual lookup: {FPI_LOOKUP_CSV}\n")

    # Step 2: Load manual lookup as fallback
    manual_lookup = load_manual_lookup()
    if manual_lookup:
        print(f"  Loaded {len(manual_lookup)} entries from {FPI_LOOKUP_CSV}")
    elif not api_works:
        print(f"  No {FPI_LOOKUP_CSV} found.")
        print(f"\n  To add FPI scores manually, create {FPI_LOOKUP_CSV} with format:")
        print(f"    pub_name,fpi_score,fpi_category")
        print(f"    Cat & Mutton,47,struggling")
        print(f"    Crown & Shuttle,77,fucked")
        print(f"\n  Or discover the API endpoint using browser DevTools (see script header).")

    # Step 3: Enrich each pub
    matched = 0
    for i, pub in enumerate(pubs):
        fpi = None

        # Try API first
        if api_works:
            fpi = try_api_fetch(pub["pub_name"])
            if (i + 1) % 20 == 0:
                print(f"  Processed {i + 1}/{len(pubs)}...")
            time.sleep(0.3)

        # Fall back to manual lookup
        if fpi is None:
            norm = normalise_name(pub["pub_name"])
            fpi = manual_lookup.get(norm)

        if fpi:
            pub["fpi_score"] = fpi["fpi_score"]
            pub["fpi_category"] = fpi["fpi_category"]
            matched += 1
        else:
            pub["fpi_score"] = ""
            pub["fpi_category"] = ""

    # Step 4: Write updated CSV
    fieldnames = ["pub_name", "location", "postcode_area", "photo_url", "fpi_score", "fpi_category"]
    with open(PUB_NAMES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pubs)

    print(f"\nDone! Matched {matched}/{len(pubs)} pubs with FPI scores.")
    print(f"Updated {PUB_NAMES_CSV}")

    # Print matched pubs
    if matched > 0:
        print(f"\nPubs with FPI scores:")
        print(f"{'Pub Name':<40} {'Score':>5}  {'Category'}")
        print("-" * 65)
        for pub in pubs:
            if pub["fpi_score"]:
                print(f"{pub['pub_name']:<40} {pub['fpi_score']:>5}  {pub['fpi_category']}")


if __name__ == "__main__":
    main()
