from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import geopandas as gpd
import os
import requests
import math
import httpx
from shapely.geometry import LineString, Point, shape
from fastapi.middleware.cors import CORSMiddleware
import json
from typing import List, Tuple, Dict
import asyncio
from functools import lru_cache

app = FastAPI()

# Add CORS middleware to allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev, allow all. For prod, restrict to ["http://localhost:3000", "http://127.0.0.1:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load OpenAIP airports
AIRPORTS_JSON = os.path.join(os.path.dirname(__file__), 'airports_us.json')
with open(AIRPORTS_JSON, 'r') as f:
    airports_data = json.load(f)
# Build DataFrame for fast lookup
airports_df = pd.DataFrame(airports_data)
airports_df = airports_df.set_index('_id', drop=False)

# Build code lookup tables for ident, gps_code, local_code
code_to_row = {}
for _, row in airports_df.iterrows():
    codes = []
    for field in ['icaoCode', 'gpsCode', 'localCode', 'id']:
        code = row.get(field)
        if code is not None:
            code_str = str(code).upper()
            codes.append(code_str)
            code_to_row[code_str] = row
    if not codes:
        print(f"[WARN] Airport missing all codes: {row.get('name', 'UNKNOWN')}")

# Load OpenAIP airspaces
AIRSPACES_JSON = os.path.join(os.path.dirname(__file__), 'airspaces_us.json')
with open(AIRSPACES_JSON, 'r') as f:
    airspaces_data = json.load(f)
# Convert to GeoDataFrame
features = []
for asp in airspaces_data:
    if 'geometry' in asp and asp['geometry']:
        try:
            features.append({
                'geometry': shape(asp['geometry']),
                'name': asp.get('name'),
                'class': asp.get('category'),
                'type': asp.get('type'),
                'id': asp.get('id'),
            })
        except Exception:
            continue
if features:
    airspaces_gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
else:
    airspaces_gdf = gpd.GeoDataFrame([], crs="EPSG:4326")

OPENWEATHERMAP_API_KEY = os.environ.get('OPENWEATHERMAP_API_KEY', '')

def get_airport_info(icao):
    code = icao.upper()
    row = code_to_row.get(code)
    if row is not None:
        return {
            "icao": row.get('icaoCode', code),
            "name": row.get('name', code),
            "lat": row['geometry']['coordinates'][1],
            "lon": row['geometry']['coordinates'][0],
            "elevation": row.get('elevation', 0)
        }
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

def is_public_open_airport(row):
    # OpenAIP: 'private' == False for public-use
    if row.get('private', True):
        print(f"Skipping {row.get('name')} ({row.get('icaoCode')}) - private")
        return False
    # Ignore 'status' check (not present in OpenAIP)
    runways = row.get('runways', [])
    # Fix: handle NaN or non-list runways
    if not isinstance(runways, list):
        runways = []
    for rwy in runways:
        try:
            length = rwy.get('dimension', {}).get('length', {}).get('value', 0)
            surface = rwy.get('surface', {}).get('mainComposite', None)
            # OpenAIP: 0=asphalt, 1=concrete, 2=paved, 4=bitumen
            if length >= 610 and surface in [0, 1, 2, 4]:
                return True
        except Exception as e:
            print(f"Error checking runway: {e}")
            continue
    print(f"Skipping {row.get('name')} ({row.get('icaoCode')}) - no suitable runway")
    return False

def find_nearest_airport(lat, lon, exclude_codes):
    min_dist = float('inf')
    nearest = None
    for code, row in code_to_row.items():
        if code in exclude_codes:
            continue
        if not is_public_open_airport(row):
            continue
        coords = row['geometry']['coordinates']
        alat, alon = coords[1], coords[0]
        dist = haversine(lat, lon, alat, alon)
        if dist < min_dist:
            min_dist = dist
            nearest = (alat, alon, code, row.get('name', code))
    return nearest

def avoid_airspaces(route_points: List[Tuple[float, float]], buffer_nm=5.0) -> List[Tuple[float, float]]:
    # Iteratively add detours until no segment intersects any airspace
    changed = True
    max_iter = 10
    iter_count = 0
    while changed and iter_count < max_iter:
        changed = False
        new_points = [route_points[0]]
        for i in range(len(route_points) - 1):
            seg = LineString([(route_points[i][1], route_points[i][0]), (route_points[i+1][1], route_points[i+1][0])])
            intersecting = airspaces_gdf[airspaces_gdf.intersects(seg)]
            if not intersecting.empty:
                # Find the first airspace, add a detour just outside its boundary
                asp = intersecting.iloc[0]
                boundary = asp.geometry.boundary
                # Find closest point on boundary to segment midpoint
                mid = seg.interpolate(0.5, normalized=True)
                closest = boundary.interpolate(boundary.project(mid))
                # Offset detour by buffer_nm (approx 0.0167 deg per nm)
                offset_lat = closest.y + buffer_nm * 0.0167
                offset_lon = closest.x + buffer_nm * 0.0167
                new_points.append((offset_lat, offset_lon))
                new_points.append(route_points[i+1])
                changed = True
                break
            else:
                new_points.append(route_points[i+1])
        if changed:
            route_points = new_points
        iter_count += 1
    return route_points

async def fetch_elevation_batch(points: List[Tuple[float, float]], client, cache: Dict) -> Dict[Tuple[float, float], float]:
    # Fetch elevations for all points, using cache where possible
    results = {}
    tasks = []
    for lat, lon in points:
        key = (round(lat, 5), round(lon, 5))
        if key in cache:
            results[key] = cache[key]
        else:
            url = f"https://portal.opentopography.org/API/globaldem?demtype=SRTMGL1&south={lat}&north={lat}&west={lon}&east={lon}&outputFormat=JSON"
            tasks.append((key, client.get(url, timeout=5)))
    if tasks:
        responses = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (key, _), resp in zip(tasks, responses):
            elev = 0
            try:
                if isinstance(resp, Exception):
                    elev = 0
                elif resp.status_code == 200:
                    j = resp.json()
                    elev = j['data'][0][2] if 'data' in j and j['data'] else 0
            except Exception:
                elev = 0
            results[key] = elev
            cache[key] = elev
    return results

def get_leg_sample_points(lat1, lon1, lat2, lon2, interval_nm=10) -> List[Tuple[float, float]]:
    n_samples = max(2, int(haversine(lat1, lon1, lat2, lon2) // interval_nm) + 1)
    return [(
        lat1 + (i / (n_samples - 1)) * (lat2 - lat1),
        lon1 + (i / (n_samples - 1)) * (lon2 - lon1)
    ) for i in range(n_samples)]

async def get_all_leg_vfr_altitudes(legs: List[Tuple[Tuple[float, float], Tuple[float, float]]], min_vfr_alt=3500, step=1000) -> List[int]:
    # Collect all sample points
    all_points = []
    for (lat1, lon1), (lat2, lon2) in legs:
        all_points.extend(get_leg_sample_points(lat1, lon1, lat2, lon2))
    # Remove duplicates
    all_points = list({(round(lat, 5), round(lon, 5)) for lat, lon in all_points})
    cache = {}
    async with httpx.AsyncClient() as client:
        elevations = await fetch_elevation_batch(all_points, client, cache)
    # Now calculate per-leg VFR altitudes
    vfr_alts = []
    for (lat1, lon1), (lat2, lon2) in legs:
        samples = get_leg_sample_points(lat1, lon1, lat2, lon2)
        max_terrain = 0
        max_airspace_floor = 0
        for lat, lon in samples:
            key = (round(lat, 5), round(lon, 5))
            elev = elevations.get(key, 0)
            if elev > max_terrain:
                max_terrain = elev
            pt = Point(lon, lat)
            intersecting = airspaces_gdf[airspaces_gdf.contains(pt)]
            for _, asp in intersecting.iterrows():
                floor = asp.get('lowerLimit', 0)
                if isinstance(floor, str):
                    try:
                        floor = int(floor.replace('ft', '').replace(' ', ''))
                    except Exception:
                        floor = 0
                if floor > max_airspace_floor:
                    max_airspace_floor = floor
        needed = max(max_terrain + 1000, max_airspace_floor + 500)
        vfr = max(min_vfr_alt, int((needed + step - 1) // step * step))
        vfr_alts.append(vfr)
    return vfr_alts

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

    # Airspace avoidance (iterative)
    if req.avoid_airspaces:
        route_points = avoid_airspaces(route_points)
        # Insert detour names for each detour
        route_names = [req.origin.upper()] + ["DETOUR"] * (len(route_points) - 2) + [req.destination.upper()]

    # Diversion logic: break up long legs with overflown airports
    max_leg = req.max_leg_distance
    i = 0
    overflown_airports = []
    overflown_coords = []
    overflown_names = []
    exclude_codes = set([req.origin.upper(), req.destination.upper()])
    while i < len(route_points) - 1:
        lat1, lon1 = route_points[i]
        lat2, lon2 = route_points[i+1]
        dist = haversine(lat1, lon1, lat2, lon2)
        if dist > max_leg:
            # Insert nearest airport to midpoint
            mid_lat = (lat1 + lat2) / 2
            mid_lon = (lon1 + lon2) / 2
            nearest = find_nearest_airport(mid_lat, mid_lon, exclude_codes)
            if nearest:
                alat, alon, code, name = nearest
                route_points.insert(i+1, (alat, alon))
                route_names.insert(i+1, code)
                overflown_airports.append(code)
                overflown_coords.append([alat, alon])
                overflown_names.append(name)
                exclude_codes.add(code)
                continue
        i += 1

    # Build route segments with type and per-leg VFR altitude (async)
    legs = [(route_points[i], route_points[i+1]) for i in range(len(route_points) - 1)]
    vfr_alts = asyncio.run(get_all_leg_vfr_altitudes(legs))
    segments = []
    for i, ((start, end), vfr_alt) in enumerate(zip(legs, vfr_alts)):
        seg_type = 'cruise'
        if i == 0:
            seg_type = 'climb'
        elif i == len(legs) - 1:
            seg_type = 'descent'
        segments.append({
            'start': start,
            'end': end,
            'type': seg_type,
            'vfr_altitude': vfr_alt
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