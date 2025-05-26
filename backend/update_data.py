import os
import requests
import json

# OpenAIP endpoints (plural, with paging)
OPENAIP_AIRSPACE_URL = "https://api.core.openaip.net/api/airspaces"
OPENAIP_AIRPORT_URL = "https://api.core.openaip.net/api/airports"

AIRSPACES_US_JSON = os.path.join(os.path.dirname(__file__), "airspaces_us.json")
AIRPORTS_US_JSON = os.path.join(os.path.dirname(__file__), "airports_us.json")

OPENAIP_API_KEY = os.environ.get('OPENAIP_API_KEY', '')
PAGE_LIMIT = 1000

def download_paged(url, dest, headers=None):
    print(f"Downloading {url} with paging ...")
    all_items = []
    page = 1
    while True:
        params = {"page": page, "limit": PAGE_LIMIT}
        r = requests.get(url, timeout=120, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        # OpenAIP returns results in 'items' key
        items = data.get('items', [])
        if not items:
            break
        all_items.extend(items)
        print(f"Fetched page {page}, {len(items)} items.")
        if len(items) < PAGE_LIMIT:
            break
        page += 1
    with open(dest, "w") as f:
        json.dump(all_items, f)
    print(f"Saved {len(all_items)} items to {dest}")

def main():
    if not OPENAIP_API_KEY:
        print("OPENAIP_API_KEY not set in environment. Skipping OpenAIP downloads.")
    else:
        try:
            headers = {"x-openaip-api-key": OPENAIP_API_KEY}
            download_paged(OPENAIP_AIRSPACE_URL, AIRSPACES_US_JSON, headers=headers)
            print("Downloaded airspaces from OpenAIP.")
        except Exception as e:
            print(f"Failed to update airspaces_us.json: {e}")
        try:
            headers = {"x-openaip-api-key": OPENAIP_API_KEY}
            download_paged(OPENAIP_AIRPORT_URL, AIRPORTS_US_JSON, headers=headers)
            print("Downloaded airports from OpenAIP.")
        except Exception as e:
            print(f"Failed to update airports_us.json: {e}")

if __name__ == "__main__":
    main() 