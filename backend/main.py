from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import geopandas as gpd
import os
import requests
import math
import httpx
from shapely.geometry import LineString, Point
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Add CORS middleware to allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev, allow all. For prod, restrict to ["http://localhost:3000", "http://127.0.0.1:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load and cache the airports database
AIRPORTS_CSV = os.path.join(os.path.dirname(__file__), 'airports.csv')
airports_df = pd.read_csv(AIRPORTS_CSV, low_memory=False)
airports_df = airports_df.set_index('ident')

# Load and cache the Swiss airspace GeoJSON
AIRSPACES_GEOJSON = os.path.join(os.path.dirname(__file__), 'airspaces_ch.geojson')
airspaces_gdf = gpd.read_file(AIRSPACES_GEOJSON)

OPENWEATHERMAP_API_KEY = os.environ.get('OPENWEATHERMAP_API_KEY', '')

def get_airport_info(icao):
    try:
        row = airports_df.loc[icao.upper()]
        return {
            "icao": icao.upper(),
            "name": row['name'],
            "lat": row['latitude_deg'],
            "lon": row['longitude_deg'],
            "elevation": row['elevation_ft']
        }
    except Exception:
        return {"error": f"Airport {icao} not found"}

@app.get("/")
def read_root():
    return {"message": "Backend is running"}

@app.get("/airport/{icao}")
def airport_lookup(icao: str):
    return get_airport_info(icao)

class RouteRequest(BaseModel):
    origin: str
    destination: str
    speed: float
    speed_unit: str = 'knots'
    altitude: int
    avoid_airspaces: bool
    avoid_terrain: bool
    max_leg_distance: float = 150.0  # nm, default value

@app.post("/route")
def calculate_route(req: RouteRequest):
    origin_info = get_airport_info(req.origin)
    dest_info = get_airport_info(req.destination)
    if 'error' in origin_info or 'error' in dest_info:
        return {"error": "Invalid origin or destination ICAO code"}

    speed = req.speed
    if req.speed_unit == 'mph':
        speed = speed * 0.868976

    # Build initial direct route
    route_points = [
        (origin_info['lat'], origin_info['lon']),
        (dest_info['lat'], dest_info['lon'])
    ]
    route_names = [req.origin.upper(), req.destination.upper()]
    detour_added = False

    # Airspace avoidance (simple: if direct line intersects any airspace, add a midpoint detour)
    if req.avoid_airspaces:
        line = LineString([(p[1], p[0]) for p in route_points])  # (lon, lat)
        intersecting = airspaces_gdf[airspaces_gdf.intersects(line)]
        if not intersecting.empty:
            largest = intersecting.iloc[intersecting.area.argmax()]
            centroid = largest.geometry.centroid
            detour = (centroid.y + 0.2, centroid.x + 0.2)  # Offset by ~20nm for demo
            route_points.insert(1, detour)
            route_names.insert(1, "DETOUR")
            detour_added = True

    # Terrain avoidance (simple: if max terrain > cruise altitude, add midpoint detour)
    if req.avoid_terrain:
        mid_lat = (route_points[0][0] + route_points[-1][0]) / 2
        mid_lon = (route_points[0][1] + route_points[-1][1]) / 2
        try:
            import httpx
            import asyncio
            async def get_elev():
                async with httpx.AsyncClient() as client:
                    url = f"https://portal.opentopography.org/API/globaldem?demtype=SRTMGL1&south={mid_lat}&north={mid_lat}&west={mid_lon}&east={mid_lon}&outputFormat=JSON"
                    resp = await client.get(url, timeout=5)
                    if resp.status_code == 200:
                        j = resp.json()
                        return j['data'][0][2] if 'data' in j and j['data'] else 0
                    return 0
            elev = asyncio.run(get_elev())
        except Exception:
            elev = 0
        if elev and req.altitude and elev > req.altitude - 1000:
            detour = (mid_lat + 0.2, mid_lon)
            if not detour_added:
                route_points.insert(1, detour)
                route_names.insert(1, "DETOUR")

    # Diversion logic: break up long legs with overflown airports
    def find_nearest_airport(lat, lon, exclude_idents):
        # Find nearest public airport with valid ICAO code not in exclude_idents
        def is_valid_icao(ident):
            return (
                isinstance(ident, str)
                and len(ident) == 4
                and ident.isalnum()
                and not ident.startswith('US-')
                and not ident[0].isdigit()
            )
        dists = ((row['latitude_deg'], row['longitude_deg'], ident)
                 for ident, row in airports_df.iterrows()
                 if ident not in exclude_idents
                 and row.get('type', '').startswith(('large_airport', 'medium_airport', 'small_airport'))
                 and is_valid_icao(ident)
                 and row.get('scheduled_service', 'no') != 'closed')
        min_dist = float('inf')
        nearest = None
        for alat, alon, ident in dists:
            dist = haversine(lat, lon, alat, alon)
            if dist < min_dist:
                min_dist = dist
                nearest = (alat, alon, ident)
        return nearest

    max_leg = req.max_leg_distance
    i = 0
    overflown_airports = []
    overflown_coords = []
    overflown_names = []
    exclude_idents = set([req.origin.upper(), req.destination.upper()])
    while i < len(route_points) - 1:
        lat1, lon1 = route_points[i]
        lat2, lon2 = route_points[i+1]
        dist = haversine(lat1, lon1, lat2, lon2)
        if dist > max_leg:
            # Insert nearest airport to midpoint
            mid_lat = (lat1 + lat2) / 2
            mid_lon = (lon1 + lon2) / 2
            nearest = find_nearest_airport(mid_lat, mid_lon, exclude_idents)
            if nearest:
                alat, alon, ident = nearest
                route_points.insert(i+1, (alat, alon))
                route_names.insert(i+1, ident)
                overflown_airports.append(ident)
                overflown_coords.append([alat, alon])
                overflown_names.append(airports_df.loc[ident]['name'])
                exclude_idents.add(ident)
                # Do not increment i, check new leg
                continue
        i += 1

    # Build route segments with type
    segments = []
    for i in range(len(route_points) - 1):
        seg_type = 'cruise'
        if i == 0:
            seg_type = 'climb'
        elif i == len(route_points) - 2:
            seg_type = 'descent'
        if detour_added and i == 0:
            seg_type = 'airspace' if req.avoid_airspaces else 'terrain'
        segments.append({
            'start': route_points[i],
            'end': route_points[i+1],
            'type': seg_type
        })

    # Calculate total distance and time
    total_dist = 0
    for i in range(len(route_points) - 1):
        total_dist += haversine(route_points[i][0], route_points[i][1], route_points[i+1][0], route_points[i+1][1])
    total_time = total_dist / speed if speed else 0

    return {
        "route": route_names,
        "distance_nm": round(total_dist, 1),
        "time_hr": round(total_time, 2),
        "overflown_airports": overflown_airports,
        "origin_coords": [origin_info['lat'], origin_info['lon']],
        "destination_coords": [dest_info['lat'], dest_info['lon']],
        "overflown_coords": overflown_coords,
        "overflown_names": overflown_names,
        "segments": segments
    }

def haversine(lat1, lon1, lat2, lon2):
    R = 3440.065  # Radius of earth in nautical miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

@app.get("/weather")
def get_weather(origin: str, destination: str):
    origin_info = get_airport_info(origin)
    dest_info = get_airport_info(destination)
    if 'error' in origin_info or 'error' in dest_info:
        return {"error": "Invalid origin or destination ICAO code"}
    if not OPENWEATHERMAP_API_KEY:
        return {"error": "OpenWeatherMap API key not set"}
    def fetch_weather(lat, lon):
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHERMAP_API_KEY}&units=metric"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"Failed to fetch weather for {lat},{lon}"}
    origin_weather = fetch_weather(origin_info['lat'], origin_info['lon'])
    dest_weather = fetch_weather(dest_info['lat'], dest_info['lon'])

    # Wind barbs along route (every 20nm)
    lat1, lon1 = origin_info['lat'], origin_info['lon']
    lat2, lon2 = dest_info['lat'], dest_info['lon']
    total_dist = haversine(lat1, lon1, lat2, lon2)
    n_points = max(2, int(total_dist // 20) + 1)
    wind_points = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        lat = lat1 + frac * (lat2 - lat1)
        lon = lon1 + frac * (lon2 - lon1)
        wx = fetch_weather(lat, lon)
        wind = wx.get('wind', {})
        wind_points.append({
            'lat': lat,
            'lon': lon,
            'wind_speed': wind.get('speed'),
            'wind_deg': wind.get('deg')
        })

    return {
        "origin": origin,
        "destination": destination,
        "origin_weather": origin_weather,
        "destination_weather": dest_weather,
        "wind_points": wind_points
    }

@app.get("/airspaces")
def get_airspaces(
    min_lat: float = Query(...),
    min_lon: float = Query(...),
    max_lat: float = Query(...),
    max_lon: float = Query(...)
):
    bbox = (min_lon, min_lat, max_lon, max_lat)
    filtered = airspaces_gdf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
    return JSONResponse(content=filtered.to_json())

@app.post("/terrain-profile")
async def terrain_profile(request: Request):
    data = await request.json()
    points = data.get('points', [])  # list of [lat, lon]
    elevations = []
    async with httpx.AsyncClient() as client:
        for lat, lon in points:
            # OpenTopography SRTM API (public, no key needed for demo)
            url = f"https://portal.opentopography.org/API/globaldem?demtype=SRTMGL1&south={lat}&north={lat}&west={lon}&east={lon}&outputFormat=JSON"
            try:
                resp = await client.get(url, timeout=5)
                if resp.status_code == 200:
                    j = resp.json()
                    elev = j['data'][0][2] if 'data' in j and j['data'] else None
                else:
                    elev = None
            except Exception:
                elev = None
            elevations.append({'lat': lat, 'lon': lon, 'elevation': elev})
    return elevations 