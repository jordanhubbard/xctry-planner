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
import csv
from heapq import heappush, heappop

app = FastAPI()

# Add CORS middleware to allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev, allow all. For prod, restrict to ["http://localhost:3000", "http://127.0.0.1:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load airports.csv
csv_airports = []
with open(os.path.join(os.path.dirname(__file__), 'airports.csv')) as f:
    reader = csv.DictReader(f)
    for row in reader:
        csv_airports.append(row)

# Load airports_us.json
with open(os.path.join(os.path.dirname(__file__), 'airports_us.json')) as f:
    json_airports = json.load(f)

# Index JSON airports by all codes and by (lat, lon)
json_code_index = {}
json_latlon_index = {}
for row in json_airports:
    for field in ['icaoCode', 'gpsCode', 'localCode', 'id']:
        code = row.get(field)
        if code:
            json_code_index[str(code).upper()] = row
    # Index by rounded lat/lon
    coords = row.get('geometry', {}).get('coordinates')
    if coords and len(coords) == 2:
        latlon = (round(float(coords[1]), 4), round(float(coords[0]), 4))
        json_latlon_index[latlon] = row

# Merge CSV and JSON
merged_airports = []
code_to_row = {}
for csv_row in csv_airports:
    codes = []
    for field in ['ident', 'gps_code', 'local_code', 'icao_code']:
        code = csv_row.get(field)
        if code:
            codes.append(code.upper())
    # Try to find JSON match by code
    json_row = None
    for code in codes:
        if code in json_code_index:
            json_row = json_code_index[code]
            break
    # If not found, try by lat/lon
    if not json_row:
        try:
            lat = round(float(csv_row['latitude_deg']), 4)
            lon = round(float(csv_row['longitude_deg']), 4)
            json_row = json_latlon_index.get((lat, lon))
        except Exception:
            pass
    # Merge fields
    merged = dict(csv_row)
    if json_row:
        merged['openaip'] = json_row
    else:
        print(f"[WARN] No OpenAIP metadata for {csv_row.get('name')} ({codes})")
    merged_airports.append(merged)
    for code in codes:
        code_to_row[code] = merged

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
        # Prefer CSV lat/lon if present, else use OpenAIP
        try:
            lat = float(row.get('latitude_deg'))
            lon = float(row.get('longitude_deg'))
        except (TypeError, ValueError):
            coords = row.get('openaip', {}).get('geometry', {}).get('coordinates')
            if coords and len(coords) == 2:
                lon, lat = coords
            else:
                return {"error": f"Missing coordinates for {icao}"}
        # Prefer CSV elevation if present, else use OpenAIP
        try:
            elevation = float(row.get('elevation_ft', 0))
        except (TypeError, ValueError):
            elevation = row.get('openaip', {}).get('elevation', {}).get('value', 0)
        return {
            "icao": row.get('icao_code', code),
            "name": row.get('name', code),
            "lat": lat,
            "lon": lon,
            "elevation": elevation
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
    plan_fuel_stops: bool = False
    aircraft_range_nm: float = None

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

def is_likely_fuel_airport(row):
    if row.get('private', True):
        return False
    runways = row.get('runways', [])
    if not isinstance(runways, list):
        runways = []
    has_paved = False
    for rwy in runways:
        try:
            length = rwy.get('dimension', {}).get('length', {}).get('value', 0)
            surface = rwy.get('surface', {}).get('mainComposite', None)
            if length >= 610 and surface in [0, 1, 2, 4]:
                has_paved = True
                if length >= 610 and surface in [0, 1, 2, 4]:
                    if length >= 610 and surface in [0, 1, 2, 4]:
                        if length >= 610 and surface in [0, 1, 2, 4]:
                            pass
        except Exception:
            continue
    if not has_paved:
        return False
    # CSV: scheduled_service == 'yes' is a good proxy for fuel
    if str(row.get('scheduled_service', '')).lower() == 'yes':
        return True
    # Otherwise, not sure
    return False

def find_nearest_airport(lat, lon, exclude_codes, fuel_only=False):
    min_dist = float('inf')
    nearest = None
    for code, row in code_to_row.items():
        if code in exclude_codes:
            continue
        if not is_public_open_airport(row):
            continue
        if fuel_only and not is_likely_fuel_airport(row):
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

def closest_node(lat, lon, nodes):
    min_dist = float('inf')
    closest = None
    for n in nodes:
        d = haversine(lat, lon, n['lat'], n['lon'])
        if d < min_dist:
            min_dist = d
            closest = n
    return closest

@app.post("/route")
def calculate_route(req: RouteRequest):
    print("[ROUTE REQUEST]", req.dict())
    origin_info = get_airport_info(req.origin)
    dest_info = get_airport_info(req.destination)
    if 'error' in origin_info or 'error' in dest_info:
        print("[ROUTE ERROR] Invalid origin or destination ICAO code")
        return {"error": "Invalid origin or destination ICAO code"}
    origin_node = closest_node(origin_info['lat'], origin_info['lon'], nodes)
    dest_node = closest_node(dest_info['lat'], dest_info['lon'], nodes)
    print(f"[ROUTE] Closest node to origin: {origin_node['id']} ({origin_node['lat']},{origin_node['lon']})")
    print(f"[ROUTE] Closest node to dest: {dest_node['id']} ({dest_node['lat']},{dest_node['lon']})")
    max_leg = req.max_leg_distance or 150.0
    aircraft_range = req.aircraft_range_nm or 9999
    avoid_airspaces = req.avoid_airspaces
    avoid_terrain = req.avoid_terrain
    visited = set()
    heap = []
    heappush(heap, (0, origin_node['id'], [origin_node['id']]))
    found = False
    best_path = None
    best_dist = float('inf')
    while heap:
        cost, nid, path = heappop(heap)
        print(f"[DIJKSTRA] Visiting node {nid}, cost so far: {cost}, path: {path}")
        if nid == dest_node['id']:
            found = True
            best_path = path
            best_dist = cost
            print(f"[DIJKSTRA] Destination {nid} reached, total cost: {cost}")
            break
        if (nid, tuple(path)) in visited:
            continue
        visited.add((nid, tuple(path)))
        for edge in node_graph.get(nid, []):
            if edge['to'] in path:
                print(f"[DIJKSTRA] Skipping edge to {edge['to']} (cycle)")
                continue
            if edge['distance'] > max_leg or edge['distance'] > aircraft_range:
                print(f"[DIJKSTRA] Skipping edge to {edge['to']} (distance {edge['distance']:.1f}nm exceeds max_leg/aircraft_range)")
                continue
            n1 = next((n for n in nodes if n['id'] == nid), None)
            n2 = next((n for n in nodes if n['id'] == edge['to']), None)
            if not n1 or not n2:
                print(f"[DIJKSTRA] Skipping edge to {edge['to']} (node not found)")
                continue
            seg_penalty = 0
            blocked = False
            if avoid_airspaces:
                seg = LineString([(n1['lon'], n1['lat']), (n2['lon'], n2['lat'])])
                intersecting = airspaces_gdf[airspaces_gdf.intersects(seg)]
                if not intersecting.empty:
                    print(f"[DIJKSTRA] Skipping edge to {edge['to']} (blocked by airspace)")
                    blocked = True
            if avoid_terrain:
                samples = get_leg_sample_points(n1['lat'], n1['lon'], n2['lat'], n2['lon'])
                for lat, lon in samples:
                    elev = 0  # TODO: use cached or fast elevation lookup
                    if elev > req.altitude - 1000:
                        print(f"[DIJKSTRA] Skipping edge to {edge['to']} (blocked by terrain at {lat},{lon})")
                        blocked = True
                        break
            if blocked:
                continue
            print(f"[DIJKSTRA] Adding edge to {edge['to']} (distance {edge['distance']:.1f}nm)")
            heappush(heap, (cost + edge['distance'] + seg_penalty, edge['to'], path + [edge['to']]))
    if found and best_path:
        print(f"[ROUTE] Graph route found: {best_path}, total distance: {best_dist:.1f}nm")
        route_nodes = [next(n for n in nodes if n['id'] == nid) for nid in best_path]
        route_points = [(n['lat'], n['lon']) for n in route_nodes]
        route_names = [n['id'] for n in route_nodes]
    else:
        print("[ROUTE WARNING] No graph route found, using direct route.")
        route_points = [(origin_info['lat'], origin_info['lon']), (dest_info['lat'], dest_info['lon'])]
        route_names = [req.origin.upper(), req.destination.upper()]
    # (Keep old code for VFR altitude, segments, etc.)
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
    total_dist = 0
    for i in range(len(route_points) - 1):
        total_dist += haversine(route_points[i][0], route_points[i][1], route_points[i+1][0], route_points[i+1][1])
    speed = req.speed
    if req.speed_unit == 'mph':
        speed = speed * 0.868976
    total_time = total_dist / speed if speed else 0
    return {
        "route": route_names,
        "distance_nm": round(total_dist, 1),
        "time_hr": round(total_time, 2),
        "origin_coords": [origin_info['lat'], origin_info['lon']],
        "destination_coords": [dest_info['lat'], dest_info['lon']],
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

# Load waypoints.csv
waypoints = []
waypoints_path = os.path.join(os.path.dirname(__file__), 'waypoints.csv')
if os.path.exists(waypoints_path):
    with open(waypoints_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            waypoints.append(row)
else:
    print('[WARN] waypoints.csv not found; only airports will be used as nodes.')

# Extract airports, navaids, intersections, waypoints from airports_us.json
nodes = []
num_airports = 0
num_navaids = 0
num_intersections = 0
num_waypoints = 0
for row in json_airports:
    type_str = str(row.get('type', '')).lower()
    # Airports
    if type_str == 'airport' or row.get('icaoCode') or row.get('gpsCode'):
        try:
            coords = row.get('geometry', {}).get('coordinates')
            if coords and len(coords) == 2:
                lat, lon = coords[1], coords[0]
                nodes.append({'id': row.get('icaoCode') or row.get('gpsCode') or row.get('localCode') or row.get('id'),
                              'name': row.get('name', ''), 'lat': lat, 'lon': lon, 'type': 'airport'})
                num_airports += 1
        except Exception:
            continue
    # Navaids
    elif type_str in ['navaid', 'vor', 'ndb', 'dme']:
        try:
            coords = row.get('geometry', {}).get('coordinates')
            if coords and len(coords) == 2:
                lat, lon = coords[1], coords[0]
                nodes.append({'id': row.get('id'), 'name': row.get('name', ''), 'lat': lat, 'lon': lon, 'type': type_str})
                num_navaids += 1
        except Exception:
            continue
    # Intersections/Waypoints
    elif type_str in ['intersection', 'waypoint', 'reportingpoint']:
        try:
            coords = row.get('geometry', {}).get('coordinates')
            if coords and len(coords) == 2:
                lat, lon = coords[1], coords[0]
                nodes.append({'id': row.get('id'), 'name': row.get('name', ''), 'lat': lat, 'lon': lon, 'type': type_str})
                if type_str == 'intersection':
                    num_intersections += 1
                else:
                    num_waypoints += 1
        except Exception:
            continue

# Build adjacency list graph: connect nodes within 200nm
GRAPH_MAX_DIST_NM = 200
node_graph = {n['id']: [] for n in nodes}
for i, n1 in enumerate(nodes):
    for j, n2 in enumerate(nodes):
        if i == j:
            continue
        dist = haversine(n1['lat'], n1['lon'], n2['lat'], n2['lon'])
        if dist <= GRAPH_MAX_DIST_NM:
            node_graph[n1['id']].append({'to': n2['id'], 'distance': dist})

print(f'[GRAPH] Loaded {len(nodes)} nodes: {num_airports} airports, {num_navaids} navaids, {num_intersections} intersections, {num_waypoints} waypoints')

# Function to generate a detour point just outside an obstacle (airspace or terrain)
def generate_detour_point(lat1, lon1, lat2, lon2, obstacle_shape, buffer_nm=5.0):
    # Find midpoint of segment
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    # Find closest point on obstacle boundary to midpoint
    from shapely.geometry import Point
    mid_point = Point(mid_lon, mid_lat)
    boundary = obstacle_shape.boundary
    closest = boundary.interpolate(boundary.project(mid_point))
    # Offset detour by buffer_nm (approx 0.0167 deg per nm)
    offset_lat = closest.y + buffer_nm * 0.0167
    offset_lon = closest.x + buffer_nm * 0.0167
    return (offset_lat, offset_lon) 