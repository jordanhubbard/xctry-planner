import os
import requests

# URLs for authoritative data
OURAIRPORTS_URL = "https://ourairports.com/data/airports.csv"
SWISS_AIRSPACE_URL = "https://www.bazl.admin.ch/bazl/en/home/good-to-know/airspace/airspace-structure/_jcr_content/contentPar/tabs/items/dokumente/tabPar/downloadlist/downloadItems/123_1688727818837.download/airspaces_ch.geojson"

AIRPORTS_CSV = os.path.join(os.path.dirname(__file__), "airports.csv")
AIRSPACES_GEOJSON = os.path.join(os.path.dirname(__file__), "airspaces_ch.geojson")

def download_file(url, dest):
    print(f"Downloading {url} ...")
    r = requests.get(url, timeout=60)
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

if __name__ == "__main__":
    main() 