import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Use two known airports from the OurAirports dataset (e.g., KJFK, KBOS)
ORIGIN = "KJFK"
DEST = "KBOS"


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "Backend is running" in r.json().get("message", "")

def test_airport_lookup():
    r = client.get(f"/airport/{ORIGIN}")
    assert r.status_code == 200
    j = r.json()
    assert j["icao"] == ORIGIN
    assert "lat" in j and "lon" in j

def test_route_direct():
    req = {
        "origin": ORIGIN,
        "destination": DEST,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": False,
        "avoid_terrain": False,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert j["route"][0] == ORIGIN
    assert j["route"][-1] == DEST
    assert j["distance_nm"] > 0
    assert j["time_hr"] > 0
    assert len(j["overflown_airports"]) == 0

def test_route_with_diversion():
    req = {
        "origin": ORIGIN,
        "destination": DEST,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": False,
        "avoid_terrain": False,
        "max_leg_distance": 30  # Force diversion
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert len(j["overflown_airports"]) > 0
    assert len(j["overflown_coords"]) == len(j["overflown_airports"])
    assert len(j["overflown_names"]) == len(j["overflown_airports"])

def test_route_with_airspace_avoidance():
    req = {
        "origin": ORIGIN,
        "destination": DEST,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": True,
        "avoid_terrain": False,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert "segments" in j
    # If airspace avoidance triggers, route will have a 'DETOUR' in names
    # (not guaranteed for all pairs, so just check segments exist)
    assert len(j["segments"]) >= 1

def test_weather():
    r = client.get(f"/weather?origin={ORIGIN}&destination={DEST}")
    assert r.status_code == 200
    j = r.json()
    assert j["origin"] == ORIGIN
    assert j["destination"] == DEST
    assert "wind_points" in j

def test_terrain_profile():
    points = [[40.6413, -73.7781], [42.3656, -71.0096]]  # KJFK to KBOS
    r = client.post("/terrain-profile", json={"points": points})
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, list)
    assert len(j) == 2
    assert "elevation" in j[0] 