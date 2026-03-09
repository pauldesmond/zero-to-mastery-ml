"""
Enrich pub_names.csv with FPI (Fucked Pub Index) scores from ismypubfucked.com.

The site uses Next.js with React Server Components (no clean JSON API).
This script scrapes the HTML search results and individual pub pages.

Falls back to reading a manual fpi_lookup.csv if the site is unreachable.

Output: Updates pub_names.csv with columns: fpi_score, fpi_category

Usage:
    python add_fpi_scores.py

    If the site is unreachable, create fpi_lookup.csv with columns:
        pub_name,fpi_score,fpi_category
    e.g.:
        Cat & Mutton,47,struggling
        Crown & Shuttle,77,fucked
"""

import csv
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PUB_NAMES_CSV = SCRIPT_DIR / "pub_names.csv"
FPI_LOOKUP_CSV = SCRIPT_DIR / "fpi_lookup.csv"

BASE_URL = "https://www.ismypubfucked.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_page(url):
    """Fetch a page and return its HTML content."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalise_name(name):
    """Normalise a pub name for fuzzy matching."""
    name = name.lower().strip()
    for prefix in ["the ", "ye olde ", "ye "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def search_pub(pub_name):
    """Search ismypubfucked.com and return list of (name, url, score, category)."""
    query = urllib.parse.quote_plus(pub_name)
    url = f"{BASE_URL}/search?q={query}"
    try:
        page_html = fetch_page(url)
    except Exception as e:
        return None, str(e)

    # Look for pub links with scores in the search results HTML.
    # The search results typically contain links to /pub/{id} with the pub name
    # and FPI score/category rendered nearby.
    results = []

    # Pattern 1: Look for links to /pub/ pages
    pub_links = re.findall(r'href="(/pub/\d+)"', page_html)

    # Pattern 2: Extract score and category from nearby text
    # The page renders scores like "47/100" and categories like "Struggling"
    score_pattern = re.compile(r'(\d{1,3})\s*/\s*100')
    category_pattern = re.compile(
        r'(somehow fine|feeling it|struggling|fucked|absolutely fucked)',
        re.IGNORECASE,
    )

    # If we found pub links, visit the first matching one for details
    if pub_links:
        # Return the first pub link for further scraping
        return pub_links, None

    # Try to extract scores directly from search results page
    scores = score_pattern.findall(page_html)
    categories = category_pattern.findall(page_html)

    if scores:
        return {"scores": scores, "categories": categories, "html": page_html}, None

    return {"html": page_html}, None


def scrape_pub_page(pub_path):
    """Scrape an individual pub page (/pub/{id}) for FPI data."""
    url = f"{BASE_URL}{pub_path}"
    try:
        page_html = fetch_page(url)
    except Exception as e:
        return None, str(e)

    # Extract pub name from the page
    name_match = re.search(r'<h[12][^>]*>([^<]+)</h[12]>', page_html)
    pub_name = html.unescape(name_match.group(1).strip()) if name_match else ""

    # Extract FPI score: look for pattern like "47/100" or score display
    score_match = re.search(r'(\d{1,3})\s*/\s*100', page_html)
    score = score_match.group(1) if score_match else ""

    # Extract category
    cat_match = re.search(
        r'(somehow fine|feeling it|struggling|fucked|absolutely fucked)',
        page_html,
        re.IGNORECASE,
    )
    category = cat_match.group(1).lower() if cat_match else ""

    # Extract address for matching
    addr_match = re.search(r'([A-Z][A-Z]?\d\d?\s*\d[A-Z]{2})', page_html)
    postcode = addr_match.group(1) if addr_match else ""

    if score:
        return {
            "pub_name": pub_name,
            "fpi_score": score,
            "fpi_category": category,
            "postcode": postcode,
        }, None

    return None, "Could not parse FPI data from page"


def search_and_match(pub_name, location=""):
    """Search for a pub and return its FPI data if found."""
    result, error = search_pub(pub_name)

    if error or result is None:
        return None

    # If we got pub links, scrape the first few to find a match
    if isinstance(result, list):
        target = normalise_name(pub_name)
        for pub_path in result[:5]:
            data, err = scrape_pub_page(pub_path)
            if data and normalise_name(data.get("pub_name", "")) == target:
                return data
            time.sleep(0.3)
        # If no exact match, return the first result (likely correct for specific names)
        if result:
            data, err = scrape_pub_page(result[0])
            if data:
                return data

    # If we got inline scores from the search page
    if isinstance(result, dict) and "scores" in result:
        scores = result["scores"]
        categories = result.get("categories", [])
        if scores:
            return {
                "fpi_score": scores[0],
                "fpi_category": categories[0].lower() if categories else "",
            }

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

    with open(PUB_NAMES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pubs = list(reader)

    if not pubs:
        print("No pubs found in CSV.")
        sys.exit(1)

    print(f"Loaded {len(pubs)} pubs from {PUB_NAMES_CSV}")

    # Test connectivity
    print("\nTesting ismypubfucked.com...")
    test_data = search_and_match(pubs[0]["pub_name"])
    site_reachable = test_data is not None

    if site_reachable:
        print(f"  Site reachable! Test result: {test_data}")
        print("  Fetching scores for all pubs...\n")
    else:
        print("  Site not reachable from this environment.")
        print(f"  Using manual lookup: {FPI_LOOKUP_CSV}\n")

    # Load manual lookup as fallback
    manual_lookup = load_manual_lookup()
    if manual_lookup:
        print(f"  Loaded {len(manual_lookup)} manual entries from {FPI_LOOKUP_CSV}")
    elif not site_reachable:
        print(f"  No {FPI_LOOKUP_CSV} found.")
        print(f"\n  Create {FPI_LOOKUP_CSV} with columns: pub_name,fpi_score,fpi_category")
        print(f"  Example:")
        print(f"    pub_name,fpi_score,fpi_category")
        print(f"    Cat & Mutton,47,struggling")
        print(f"    Crown & Shuttle,77,fucked\n")

    # Enrich each pub
    matched = 0
    for i, pub in enumerate(pubs):
        fpi = None

        if site_reachable:
            fpi_data = search_and_match(pub["pub_name"], pub.get("location", ""))
            if fpi_data:
                fpi = {
                    "fpi_score": fpi_data["fpi_score"],
                    "fpi_category": fpi_data["fpi_category"],
                }
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(pubs)}...")
            time.sleep(0.5)

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

    # Write updated CSV
    fieldnames = ["pub_name", "location", "postcode_area", "photo_url", "fpi_score", "fpi_category"]
    with open(PUB_NAMES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pubs)

    print(f"\nDone! Matched {matched}/{len(pubs)} pubs with FPI scores.")
    print(f"Updated {PUB_NAMES_CSV}")

    if matched > 0:
        print(f"\nPubs with FPI scores:")
        print(f"{'Pub Name':<40} {'Score':>5}  {'Category'}")
        print("-" * 65)
        for pub in pubs:
            if pub["fpi_score"]:
                print(f"{pub['pub_name']:<40} {pub['fpi_score']:>5}  {pub['fpi_category']}")


if __name__ == "__main__":
    main()
