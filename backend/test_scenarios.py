import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Example airports (update as needed for your data)
KPAO = "KPAO"  # Palo Alto
KSFO = "KSFO"  # San Francisco Intl
KOAK = "KOAK"  # Oakland
KLAX = "KLAX"  # Los Angeles Intl
KDEN = "KDEN"  # Denver Intl
KSLC = "KSLC"  # Salt Lake City Intl


def test_direct_route():
    req = {
        "origin": KPAO,
        "destination": KOAK,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": False,
        "avoid_terrain": False,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert j["route"][0] == KPAO
    assert j["route"][-1] == KOAK
    assert j["distance_nm"] > 0
    assert j["time_hr"] > 0
    assert len(j["overflown_airports"]) == 0
    assert all("vfr_altitude" in seg for seg in j["segments"])

def test_airspace_avoidance():
    req = {
        "origin": KPAO,
        "destination": KSFO,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": True,
        "avoid_terrain": False,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    # Should have at least one detour if airspace is present
    assert "DETOUR" in j["route"] or len(j["segments"]) > 1
    assert all("vfr_altitude" in seg for seg in j["segments"])

def test_diversion_airports():
    req = {
        "origin": KPAO,
        "destination": KLAX,
        "speed": 120,
        "altitude": 7500,
        "avoid_airspaces": False,
        "avoid_terrain": False,
        "max_leg_distance": 100  # Force diversions
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert len(j["overflown_airports"]) > 0
    assert len(j["overflown_coords"]) == len(j["overflown_airports"])
    assert len(j["overflown_names"]) == len(j["overflown_airports"])
    assert all("vfr_altitude" in seg for seg in j["segments"])

def test_terrain_aware_altitude():
    req = {
        "origin": KDEN,
        "destination": KSLC,
        "speed": 120,
        "altitude": 8500,
        "avoid_airspaces": False,
        "avoid_terrain": True,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    # VFR altitudes should be >= 3500 and reflect terrain
    assert all(seg["vfr_altitude"] >= 3500 for seg in j["segments"])

def test_invalid_airport():
    req = {
        "origin": "XXXX",
        "destination": KLAX,
        "speed": 120,
        "altitude": 5500,
        "avoid_airspaces": False,
        "avoid_terrain": False,
        "max_leg_distance": 500
    }
    r = client.post("/route", json=req)
    assert r.status_code == 200
    j = r.json()
    assert "error" in j 