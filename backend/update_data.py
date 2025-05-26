import os
import requests

# URLs for authoritative data
OURAIRPORTS_URL = "https://ourairports.com/data/airports.csv"
SWISS_AIRSPACE_URL = "https://www.bazl.admin.ch/bazl/en/home/good-to-know/airspace/airspace-structure/_jcr_content/contentPar/tabs/items/dokumente/tabPar/downloadlist/downloadItems/123_1688727818837.download/airspaces_ch.geojson"
US_AIRSPACE_URL = "https://www.openaip.net/api/airspace-geojson?country=US"  # Replace with actual OpenAIP/FAA endpoint if needed

AIRPORTS_CSV = os.path.join(os.path.dirname(__file__), "airports.csv")
AIRSPACES_GEOJSON = os.path.join(os.path.dirname(__file__), "airspaces_ch.geojson")
US_AIRSPACES_GEOJSON = os.path.join(os.path.dirname(__file__), "airspaces_us.geojson")

OPENAIP_API_KEY = os.environ.get('OPENAIP_API_KEY', '')

def download_file(url, dest, headers=None):
    print(f"Downloading {url} ...")
    r = requests.get(url, timeout=60, headers=headers)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    print(f"Saved to {dest}")

def main():
    try:
        download_file(OURAIRPORTS_URL, AIRPORTS_CSV)
    except Exception as e:
        print(f"Failed to update airports.csv: {e}")
    try:
        download_file(SWISS_AIRSPACE_URL, AIRSPACES_GEOJSON)
    except Exception as e:
        print(f"Failed to update airspaces_ch.geojson: {e}")
    if not OPENAIP_API_KEY:
        print("OPENAIP_API_KEY not set in environment. Skipping US airspace download.")
    else:
        try:
            headers = {"Authorization": f"Bearer {OPENAIP_API_KEY}"}
            download_file(US_AIRSPACE_URL, US_AIRSPACES_GEOJSON, headers=headers)
        except Exception as e:
            print(f"Failed to update airspaces_us.geojson: {e}")

if __name__ == "__main__":
    main() 