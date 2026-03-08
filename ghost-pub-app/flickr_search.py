"""
Flickr API search script for finding abandoned/demolished pub photos.

Searches a specific Flickr user's photostream for pub-related images
that can be used in the Ghost Pub app.

Usage:
    1. Create a .env file in this directory with: FLICKR_API_KEY=your_key_here
    2. Run: python flickr_search.py
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Load API key from .env file
def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


load_env()

FLICKR_API_KEY = os.environ.get("FLICKR_API_KEY")
if not FLICKR_API_KEY:
    print("Error: FLICKR_API_KEY not found.")
    print("Create a .env file in this directory with: FLICKR_API_KEY=your_key_here")
    sys.exit(1)

FLICKR_API_URL = "https://api.flickr.com/services/rest/"

# The Flickr user with abandoned pub photos
TARGET_USER_ID = "55935853@N00"

# Search terms related to abandoned/demolished pubs
PUB_SEARCH_TERMS = [
    "abandoned pub",
    "demolished pub",
    "lost pub",
    "closed pub",
    "derelict pub",
    "former pub",
    "ghost pub",
    "disused pub",
]


def flickr_api_call(method, **kwargs):
    """Make a Flickr API call and return the JSON response."""
    params = {
        "method": method,
        "api_key": FLICKR_API_KEY,
        "format": "json",
        "nojsoncallback": 1,
        **kwargs,
    }
    url = FLICKR_API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def get_user_info(user_id):
    """Get information about the Flickr user."""
    data = flickr_api_call("flickr.people.getInfo", user_id=user_id)
    if data.get("stat") != "ok":
        print(f"Error fetching user info: {data}")
        return None
    person = data["person"]
    username = person.get("username", {}).get("_content", "Unknown")
    realname = person.get("realname", {}).get("_content", "")
    photo_count = person.get("photos", {}).get("count", {}).get("_content", "?")
    print(f"User: {username} ({realname})")
    print(f"Total photos: {photo_count}")
    print(f"Profile: https://www.flickr.com/photos/{user_id}/")
    print()
    return person


def search_user_photos(user_id, text, per_page=100, page=1):
    """Search a specific user's photos by text."""
    data = flickr_api_call(
        "flickr.photos.search",
        user_id=user_id,
        text=text,
        per_page=str(per_page),
        page=str(page),
        extras="description,date_taken,tags,geo,url_m,url_l,url_o,license",
    )
    if data.get("stat") != "ok":
        print(f"Error searching photos: {data}")
        return None
    return data["photos"]


def get_photo_url(photo, size="m"):
    """Build the photo URL from photo data."""
    # If URL was returned in extras, use it
    url_key = f"url_{size}"
    if url_key in photo:
        return photo[url_key]
    # Otherwise construct it
    farm = photo.get("farm")
    server = photo.get("server")
    photo_id = photo.get("id")
    secret = photo.get("secret")
    if all([farm, server, photo_id, secret]):
        size_suffix = f"_{size}" if size != "o" else ""
        return f"https://farm{farm}.staticflickr.com/{server}/{photo_id}_{secret}{size_suffix}.jpg"
    return None


def get_photo_page_url(photo, user_id):
    """Get the Flickr page URL for a photo."""
    return f"https://www.flickr.com/photos/{user_id}/{photo['id']}"


def search_all_pub_photos(user_id):
    """Search for all pub-related photos from the user."""
    all_photos = {}

    for term in PUB_SEARCH_TERMS:
        print(f"Searching for: '{term}'...")
        result = search_user_photos(user_id, term)
        if not result:
            continue

        photos = result.get("photo", [])
        total = result.get("total", 0)
        print(f"  Found {total} results")

        for photo in photos:
            photo_id = photo["id"]
            if photo_id not in all_photos:
                all_photos[photo_id] = {
                    "id": photo_id,
                    "title": photo["title"],
                    "description": photo.get("description", {}).get("_content", ""),
                    "date_taken": photo.get("datetaken", ""),
                    "tags": photo.get("tags", ""),
                    "latitude": photo.get("latitude", ""),
                    "longitude": photo.get("longitude", ""),
                    "url_medium": get_photo_url(photo, "m"),
                    "url_large": get_photo_url(photo, "l"),
                    "url_original": get_photo_url(photo, "o"),
                    "flickr_page": get_photo_page_url(photo, user_id),
                    "matched_terms": [term],
                }
            else:
                all_photos[photo_id]["matched_terms"].append(term)

        # Be polite to the API
        time.sleep(0.5)

        # Fetch additional pages if there are more results
        total_pages = result.get("pages", 1)
        for page_num in range(2, min(total_pages + 1, 6)):  # Max 5 pages per term
            print(f"  Fetching page {page_num}/{total_pages}...")
            page_result = search_user_photos(user_id, term, page=page_num)
            if not page_result:
                break
            for photo in page_result.get("photo", []):
                photo_id = photo["id"]
                if photo_id not in all_photos:
                    all_photos[photo_id] = {
                        "id": photo_id,
                        "title": photo["title"],
                        "description": photo.get("description", {}).get("_content", ""),
                        "date_taken": photo.get("datetaken", ""),
                        "tags": photo.get("tags", ""),
                        "latitude": photo.get("latitude", ""),
                        "longitude": photo.get("longitude", ""),
                        "url_medium": get_photo_url(photo, "m"),
                        "url_large": get_photo_url(photo, "l"),
                        "url_original": get_photo_url(photo, "o"),
                        "flickr_page": get_photo_page_url(photo, user_id),
                        "matched_terms": [term],
                    }
                else:
                    all_photos[photo_id]["matched_terms"].append(term)
            time.sleep(0.5)

    return all_photos


def save_results(photos, output_path="pub_photos.json"):
    """Save results to a JSON file."""
    output_file = Path(__file__).parent / output_path
    photo_list = sorted(photos.values(), key=lambda p: p.get("title", ""))
    with open(output_file, "w") as f:
        json.dump(photo_list, f, indent=2)
    print(f"\nSaved {len(photo_list)} photos to {output_file}")
    return output_file


def print_summary(photos):
    """Print a summary of the found photos."""
    photo_list = sorted(photos.values(), key=lambda p: p.get("title", ""))
    print(f"\n{'='*70}")
    print(f"RESULTS: Found {len(photo_list)} unique pub photos")
    print(f"{'='*70}\n")

    geo_count = sum(1 for p in photo_list if p.get("latitude") and p["latitude"] != "0")
    print(f"Photos with geolocation data: {geo_count}/{len(photo_list)}")
    print()

    for i, photo in enumerate(photo_list[:20], 1):
        title = photo["title"] or "(untitled)"
        terms = ", ".join(photo["matched_terms"])
        has_geo = "GPS" if photo.get("latitude") and photo["latitude"] != "0" else "   "
        print(f"  {i:3d}. [{has_geo}] {title[:50]:<50} [{terms}]")
        print(f"       {photo['flickr_page']}")

    if len(photo_list) > 20:
        print(f"\n  ... and {len(photo_list) - 20} more (see pub_photos.json for full list)")


def main():
    print("Ghost Pub App - Flickr Photo Search")
    print(f"Searching user: {TARGET_USER_ID}")
    print(f"Profile: https://www.flickr.com/photos/{TARGET_USER_ID}/")
    print("=" * 70)
    print()

    # Get user info
    get_user_info(TARGET_USER_ID)

    # Search for pub photos
    photos = search_all_pub_photos(TARGET_USER_ID)

    if not photos:
        print("\nNo pub photos found. Try adjusting the search terms.")
        return

    # Print summary
    print_summary(photos)

    # Save to JSON
    save_results(photos)


if __name__ == "__main__":
    main()
