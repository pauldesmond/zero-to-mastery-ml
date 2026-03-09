"""
Enrich pub_names.csv with FPI scores and VOA rateable value data.

Two data sources:

1. fpi_lookup.csv — Manually verified FPI scores from ismypubfucked.com.
   Used as override when available.

2. /tmp/voa/pub-risk.json — VOA rating list data (from build_pub_risk.py).
   Matched by postcode area + fuzzy name + Flickr photo geotag proximity.
   Provides fpi_pct_change (raw rateable value % change) and voa_name.

When no manual lookup exists, FPI scores are computed from VOA percentage
change using the formula: score = clamp(round(pct_change * 0.6), 0, 100).
This replicates the ismypubfucked.com scoring methodology.

Output: Updates pub_names.csv with columns: fpi_score, fpi_category,
        fpi_pct_change, voa_name

Usage:
    python add_fpi_scores.py
"""

import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PUB_NAMES_CSV = SCRIPT_DIR / "pub_names.csv"
FPI_LOOKUP_CSV = SCRIPT_DIR / "fpi_lookup.csv"
VOA_JSON = Path("/tmp/voa/pub-risk.json")


def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in metres between two lat/lng points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Cache postcodes.io lookups to avoid repeat calls
_postcode_cache = {}


def geocode_postcode(postcode):
    """Geocode a full UK postcode via postcodes.io. Returns (lat, lng) or None."""
    postcode = postcode.strip().upper()
    if postcode in _postcode_cache:
        return _postcode_cache[postcode]
    try:
        encoded = urllib.parse.quote(postcode)
        url = f"https://api.postcodes.io/postcodes/{encoded}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") == 200:
            result = data["result"]
            coords = (result["latitude"], result["longitude"])
            _postcode_cache[postcode] = coords
            return coords
    except Exception:
        pass
    _postcode_cache[postcode] = None
    return None


MAX_GEO_DISTANCE_M = 200  # Max metres between photo and VOA postcode centroid


def normalise_name(name):
    """Normalise a pub name for matching."""
    name = name.upper().strip()
    # Remove common prefixes
    for prefix in ["THE ", "YE OLDE ", "YE "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Normalise ampersands
    name = name.replace("&", "AND").replace("'", "").replace("\u2019", "")
    # Remove punctuation and extra spaces
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_pub_name_from_voa(voa_name):
    """Extract the pub name from a VOA address string.

    VOA names look like:
      "THE CAT AND MUTTON, 76, BROADWAY MARKET, LONDON"
      "PRINCE OF WALES, 48, CLEAVER SQUARE, LONDON"
    The pub name is typically the first comma-separated part.
    """
    parts = voa_name.split(",")
    return parts[0].strip()


def postcode_area(postcode):
    """Extract area from a full postcode: 'E8 4QJ' -> 'E8', 'EC1A 2BB' -> 'EC1'."""
    postcode = postcode.strip().upper()
    # Match the area part: letters followed by digits (e.g., E8, EC1, SW1, WC2)
    m = re.match(r"([A-Z]{1,2}\d{1,2})", postcode)
    return m.group(1) if m else postcode.split()[0] if postcode else ""


def compute_fpi_score(pct_change):
    """Compute FPI score (0-100) from rateable value percentage change.

    Formula reverse-engineered from ismypubfucked.com data points:
      -78.4% -> 0, +79.4% -> 48, +622% -> 100, +632% -> 100
    """
    return max(0, min(100, round(pct_change * 0.6)))


def fpi_category(score):
    """Return FPI category label for a given score."""
    if score == 0:
        return "somehow fine"
    if score < 30:
        return "feeling it"
    if score < 60:
        return "struggling"
    if score < 100:
        return "fucked"
    return "absolutely fucked"


def load_voa_data():
    """Load VOA pub-risk.json and index by postcode area."""
    print(f"Loading {VOA_JSON} ...")
    with open(VOA_JSON) as f:
        pubs = json.load(f)
    print(f"  Loaded {len(pubs)} pubs")

    # Index by postcode area for fast lookup
    by_area = {}
    for pub in pubs:
        area = postcode_area(pub["postcode"])
        if area:
            by_area.setdefault(area, []).append(pub)

    return pubs, by_area


def get_candidates(postcode_area_code, by_area):
    """Get VOA candidates for a postcode area, expanding short codes.

    If 'EC' has no direct matches, expand to EC1, EC2, EC3, EC4 etc.
    Similarly 'W' expands to W1, W2, ... W14, 'SW' to SW1..SW20.
    """
    candidates = by_area.get(postcode_area_code, [])
    if candidates:
        return candidates

    # Try expanding: 'EC' -> 'EC1', 'EC2', etc.
    all_candidates = []
    prefix = postcode_area_code.upper()
    for area_key in by_area:
        if area_key.startswith(prefix) and area_key != prefix:
            all_candidates.extend(by_area[area_key])
    return all_candidates


def extract_street(location):
    """Extract street name from location like 'Broadway Market, London'."""
    if not location:
        return ""
    # Take the part before the first comma (the street/area name)
    street = location.split(",")[0].strip()
    return street.upper()


def name_in_voa_address(target, voa_full_address):
    """Check if pub name appears anywhere in VOA address (not just first part).

    Handles cases like 'GRD FLR 7 CHAPEL PLACE 320, OLD STREET'
    where the pub name isn't the first comma-separated part.
    """
    norm_address = normalise_name(voa_full_address)
    return target in norm_address


def find_best_match(pub_name, postcode_area_code, by_area, location="",
                    photo_lat=None, photo_lng=None):
    """Find the best matching VOA pub by name within a postcode area.

    Uses name matching, street/location, and photo geotag proximity.

    When photo coordinates are available and multiple name matches exist,
    geocodes VOA postcodes and picks the nearest one within MAX_GEO_DISTANCE_M.
    """
    candidates = get_candidates(postcode_area_code, by_area)
    if not candidates:
        return None

    target = normalise_name(pub_name)
    street = extract_street(location)

    # Score all candidates by name + street
    scored = []
    for pub in candidates:
        score = 0
        voa_pub_name = extract_pub_name_from_voa(pub["name"])
        norm_voa = normalise_name(voa_pub_name)
        voa_full = pub["name"].upper()

        # Name matching
        if norm_voa == target:
            score += 3  # Perfect name match in first part
        elif target in norm_voa or norm_voa in target:
            score += 2  # Partial name match in first part
        elif name_in_voa_address(target, pub["name"]):
            score += 1  # Name found somewhere in full address

        if score == 0:
            continue

        # Street/location matching (bonus for disambiguation)
        if street and len(street) > 2:
            if street in voa_full:
                score += 2
            else:
                street_words = [w for w in street.split() if len(w) >= 4]
                matches = sum(1 for w in street_words if w in voa_full)
                if matches > 0:
                    score += 1

        scored.append((score, pub))

    if not scored:
        return None

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # If we have photo coordinates and multiple good candidates, use geo
    top_score = scored[0][0]
    top_candidates = [(s, p) for s, p in scored if s >= top_score - 1]

    if photo_lat is not None and photo_lng is not None and len(top_candidates) > 1:
        best_dist = float("inf")
        best_geo = None
        for _score, pub in top_candidates:
            coords = geocode_postcode(pub["postcode"])
            if coords:
                dist = haversine_m(photo_lat, photo_lng, coords[0], coords[1])
                if dist < best_dist:
                    best_dist = dist
                    best_geo = pub
            time.sleep(0.1)  # Rate limit postcodes.io

        if best_geo and best_dist <= MAX_GEO_DISTANCE_M:
            return best_geo

    # Fall back to highest-scored match
    return scored[0][1]


def load_manual_lookup():
    """Load manually-verified FPI scores from ismypubfucked.com."""
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
    geo_count = sum(1 for p in pubs if p.get("photo_lat"))
    if geo_count:
        print(f"  {geo_count}/{len(pubs)} have photo geotags for proximity matching")

    # Load manually-verified FPI scores (the only trusted source for scores)
    manual_lookup = load_manual_lookup()
    if manual_lookup:
        print(f"  Loaded {len(manual_lookup)} verified FPI scores from {FPI_LOOKUP_CSV}")

    # Try VOA data for % change and VOA name (but NOT for FPI scores)
    use_voa = VOA_JSON.exists()
    by_area = {}
    if use_voa:
        all_voa, by_area = load_voa_data()
    else:
        print(f"\n  {VOA_JSON} not found — skipping VOA matching.")
        print(f"  Run build_pub_risk.py first to enable VOA data.\n")

    # Enrich each pub
    matched_fpi = 0
    matched_voa = 0
    unmatched_fpi = []

    for pub in pubs:
        norm = normalise_name(pub["pub_name"])

        # VOA data: raw % change and VOA name
        pub["fpi_pct_change"] = ""
        pub["voa_name"] = ""
        if use_voa:
            area = pub.get("postcode_area", "")
            location = pub.get("location", "")
            plat = pub.get("photo_lat", "")
            plng = pub.get("photo_lng", "")
            photo_lat = float(plat) if plat else None
            photo_lng = float(plng) if plng else None
            match = find_best_match(pub["pub_name"], area, by_area, location,
                                    photo_lat=photo_lat, photo_lng=photo_lng)
            if match:
                pub["fpi_pct_change"] = str(match["fpi"])
                pub["voa_name"] = match["name"]
                matched_voa += 1

        # FPI score: prefer manual lookup, otherwise compute from VOA % change
        manual = manual_lookup.get(norm)
        if manual:
            pub["fpi_score"] = manual["fpi_score"]
            pub["fpi_category"] = manual["fpi_category"]
            matched_fpi += 1
        elif pub["fpi_pct_change"]:
            pct = float(pub["fpi_pct_change"])
            score = compute_fpi_score(pct)
            pub["fpi_score"] = str(score)
            pub["fpi_category"] = fpi_category(score)
            matched_fpi += 1
        else:
            pub["fpi_score"] = ""
            pub["fpi_category"] = ""
            unmatched_fpi.append(pub["pub_name"])

    # Write updated CSV — preserve photo_lat/photo_lng if present
    fieldnames = [
        "pub_name", "location", "postcode_area", "photo_url",
    ]
    if any(pub.get("photo_lat") for pub in pubs):
        fieldnames.extend(["photo_lat", "photo_lng"])
    fieldnames.extend(["fpi_score", "fpi_category", "fpi_pct_change", "voa_name"])
    with open(PUB_NAMES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pubs)

    print(f"\nDone!")
    print(f"  Verified FPI scores: {matched_fpi}/{len(pubs)}")
    if matched_voa:
        print(f"  VOA matches (% change): {matched_voa}/{len(pubs)}")
    if unmatched_fpi:
        print(f"  No verified FPI score: {len(unmatched_fpi)}")
        for name in unmatched_fpi[:20]:
            print(f"    - {name}")
        if len(unmatched_fpi) > 20:
            print(f"    ... and {len(unmatched_fpi) - 20} more")

    print(f"\nUpdated {PUB_NAMES_CSV}")

    # Print summary table
    scored_pubs = [p for p in pubs if p["fpi_score"] or p["voa_name"]]
    if scored_pubs:
        print(f"\n{'Pub Name':<35} {'FPI':>5}  {'Category':<17} {'% Change':>8}  VOA Name")
        print("-" * 120)
        for pub in scored_pubs:
            fpi = pub["fpi_score"] or "  -"
            cat = pub["fpi_category"] or "-"
            pct = pub["fpi_pct_change"] or "-"
            print(
                f"{pub['pub_name']:<35} {fpi:>5}  "
                f"{cat:<17} {pct:>8}  "
                f"{pub.get('voa_name', '')[:45]}"
            )


if __name__ == "__main__":
    main()
