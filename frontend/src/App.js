import React, { useEffect, useState } from 'react';
import './App.css';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Polygon, useMapEvent } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

function WindBarbMarker({ lat, lon, wind_deg, wind_speed }) {
  const icon = L.divIcon({
    className: '',
    html: `<svg width="32" height="32" style="transform: rotate(${wind_deg || 0}deg);">
      <g>
        <line x1="16" y1="28" x2="16" y2="4" stroke="blue" stroke-width="3" />
        <polygon points="12,8 16,0 20,8" fill="blue" />
      </g>
      <text x="16" y="30" text-anchor="middle" font-size="10" fill="black">${wind_speed ? wind_speed.toFixed(0) : ''}</text>
    </svg>`
  });
  return <Marker position={[lat, lon]} icon={icon} />;
}

function AirspaceOverlay({ setAirspaces }) {
  useMapEvent('moveend', (e) => {
    const map = e.target;
    const bounds = map.getBounds();
    const min_lat = bounds.getSouth();
    const min_lon = bounds.getWest();
    const max_lat = bounds.getNorth();
    const max_lon = bounds.getEast();
    fetch(`http://localhost:8000/airspaces?min_lat=${min_lat}&min_lon=${min_lon}&max_lat=${max_lat}&max_lon=${max_lon}`)
      .then((res) => res.json())
      .then((geojson) => setAirspaces(geojson))
      .catch(() => setAirspaces(null));
  });
  return null;
}

function calculateCourse(lat1, lon1, lat2, lon2) {
  // Returns course in degrees from north
  const toRad = (deg) => deg * Math.PI / 180;
  const toDeg = (rad) => rad * 180 / Math.PI;
  const dLon = toRad(lon2 - lon1);
  const y = Math.sin(dLon) * Math.cos(toRad(lat2));
  const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) - Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLon);
  let brng = Math.atan2(y, x);
  brng = toDeg(brng);
  return (brng + 360) % 360;
}

function suggestVFRAltitudes(course) {
  // Odd thousands + 500 for 0-179 (east), even + 500 for 180-359 (west)
  const east = [3500, 5500, 7500, 9500, 11500];
  const west = [4500, 6500, 8500, 10500, 12500];
  if (course >= 0 && course < 180) return east;
  return west;
}

function haversine(lat1, lon1, lat2, lon2) {
  const R = 3440.065; // nm
  const toRad = (deg) => deg * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2)**2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

function ElevationChart({ profile, loading, error }) {
  if (loading) return <div style={{ color: 'white', margin: '1em' }}>Loading terrain profile...</div>;
  if (error) return <div style={{ color: 'red', margin: '1em' }}>Could not fetch terrain profile.</div>;
  if (!profile || profile.length === 0) return null;
  const width = 600;
  const height = 120;
  const minElev = Math.min(...profile.map(p => p.elevation ?? 0));
  const maxElev = Math.max(...profile.map(p => p.elevation ?? 0));
  const elevRange = maxElev - minElev || 1;
  const points = profile.map((p, i) => [
    (i / (profile.length - 1)) * width,
    height - ((p.elevation - minElev) / elevRange) * (height - 20) - 10
  ]);
  const polyline = points.map(([x, y]) => `${x},${y}`).join(' ');
  return (
    <svg width={width} height={height} style={{ background: '#222', borderRadius: 8, margin: '1em auto', display: 'block' }}>
      <polyline points={polyline} fill="none" stroke="lime" strokeWidth="2" />
      <text x="5" y="15" fill="white" fontSize="12">Elevation (ft)</text>
      <text x="5" y={height - 5} fill="white" fontSize="10">{minElev.toFixed(0)}</text>
      <text x={width - 40} y={height - 5} fill="white" fontSize="10">{maxElev.toFixed(0)}</text>
    </svg>
  );
}

const SEGMENT_COLORS = {
  cruise: 'lime',
  climb: 'orange',
  descent: 'blue',
  airspace: 'red',
  terrain: 'brown',
};

function App() {
  const [backendMsg, setBackendMsg] = useState('');
  const [form, setForm] = useState({
    origin: '',
    destination: '',
    speed: '',
    altitude: '',
    avoid_airspaces: false,
    avoid_terrain: false,
    max_leg_distance: 150,
  });
  const [routeResult, setRouteResult] = useState(null);
  const [weather, setWeather] = useState(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [airspaces, setAirspaces] = useState(null);
  const [airspacesLoading, setAirspacesLoading] = useState(false);
  const [airspacesError, setAirspacesError] = useState(null);
  const [vfrAltitudes, setVfrAltitudes] = useState([]);
  const [terrainProfile, setTerrainProfile] = useState([]);
  const [terrainLoading, setTerrainLoading] = useState(false);
  const [terrainError, setTerrainError] = useState(null);

  useEffect(() => {
    fetch('http://localhost:8000/')
      .then((res) => res.json())
      .then((data) => setBackendMsg(data.message))
      .catch(() => setBackendMsg('Could not reach backend'));
  }, []);

  useEffect(() => {
    // Suggest VFR altitudes when route changes
    if (routeResult && routeResult.origin_coords && routeResult.destination_coords) {
      const [lat1, lon1] = routeResult.origin_coords;
      const [lat2, lon2] = routeResult.destination_coords;
      const course = calculateCourse(lat1, lon1, lat2, lon2);
      setVfrAltitudes(suggestVFRAltitudes(course));
    } else {
      setVfrAltitudes([]);
    }
  }, [routeResult]);

  useEffect(() => {
    // Fetch terrain profile when route changes
    if (routeResult && routeResult.origin_coords && routeResult.destination_coords) {
      setTerrainLoading(true);
      setTerrainError(null);
      const points = [routeResult.origin_coords, ...(routeResult.overflown_coords || []), routeResult.destination_coords];
      fetch('http://localhost:8000/terrain-profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ points }),
      })
        .then((res) => res.json())
        .then((data) => {
          setTerrainProfile(data);
          setTerrainLoading(false);
        })
        .catch(() => {
          setTerrainProfile([]);
          setTerrainError('Could not fetch terrain profile');
          setTerrainLoading(false);
        });
    } else {
      setTerrainProfile([]);
      setTerrainError(null);
    }
  }, [routeResult]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
  };

  const handleVFRAltitudeChange = (e) => {
    setForm((prev) => ({ ...prev, altitude: e.target.value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    fetch('http://localhost:8000/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...form,
        speed: parseFloat(form.speed),
        altitude: parseInt(form.altitude, 10),
        max_leg_distance: parseFloat(form.max_leg_distance),
      }),
    })
      .then((res) => res.json())
      .then(setRouteResult)
      .catch(() => setRouteResult({ error: 'Could not calculate route' }));
  };

  const fetchWeather = () => {
    if (!form.origin || !form.destination) return;
    setWeatherLoading(true);
    fetch(`http://localhost:8000/weather?origin=${form.origin}&destination=${form.destination}`)
      .then((res) => res.json())
      .then((data) => {
        setWeather(data);
        setWeatherLoading(false);
      })
      .catch(() => {
        setWeather({ error: 'Could not fetch weather' });
        setWeatherLoading(false);
      });
  };

  // Use real coordinates from backend if available
  let polylinePositions = null;
  let originMarker = null;
  let destMarker = null;
  let overflownMarkers = [];
  if (routeResult && routeResult.origin_coords && routeResult.destination_coords) {
    polylinePositions = [
      routeResult.origin_coords,
      ...(routeResult.overflown_coords || []),
      routeResult.destination_coords
    ];
    originMarker = (
      <Marker position={routeResult.origin_coords}>
        <Popup>
          {routeResult.route && routeResult.route[0]}<br />
          Origin Airport
        </Popup>
      </Marker>
    );
    destMarker = (
      <Marker position={routeResult.destination_coords}>
        <Popup>
          {routeResult.route && routeResult.route[routeResult.route.length - 1]}<br />
          Destination Airport
        </Popup>
      </Marker>
    );
    if (routeResult.overflown_coords && routeResult.overflown_names) {
      overflownMarkers = routeResult.overflown_coords.map((coords, i) => (
        <Marker position={coords} key={i}>
          <Popup>
            {routeResult.overflown_names[i]}<br />
            Overflown Airport
          </Popup>
        </Marker>
      ));
    }
  }

  let windBarbMarkers = [];
  if (weather && weather.wind_points && Array.isArray(weather.wind_points)) {
    windBarbMarkers = weather.wind_points.map((wp, i) => (
      <WindBarbMarker key={i} lat={wp.lat} lon={wp.lon} wind_deg={wp.wind_deg} wind_speed={wp.wind_speed} />
    ));
  }

  let airspacePolygons = [];
  if (airspaces && airspaces.features) {
    airspacePolygons = airspaces.features.map((feature, i) => (
      <Polygon
        key={i}
        positions={feature.geometry.coordinates[0].map(([lon, lat]) => [lat, lon])}
        pathOptions={{ color: 'red', fillOpacity: 0.2 }}
      >
        <Popup>
          {feature.properties.Name || feature.properties.name}<br />
          Class: {feature.properties.ASClass || feature.properties.class}<br />
          Type: {feature.properties.ASType || feature.properties.type}
        </Popup>
      </Polygon>
    ));
  }

  // Table view of flight legs
  let legsTable = null;
  if (routeResult && routeResult.route && routeResult.route.length >= 2 && routeResult.origin_coords && routeResult.destination_coords) {
    const points = [routeResult.origin_coords, ...(routeResult.overflown_coords || []), routeResult.destination_coords];
    const legs = [];
    for (let i = 0; i < points.length - 1; i++) {
      const from = points[i];
      const to = points[i + 1];
      const dist = haversine(from[0], from[1], to[0], to[1]);
      const time = form.speed ? dist / parseFloat(form.speed) : 0;
      const diversion = (routeResult.overflown_coords && routeResult.overflown_coords.length > 0 && i < routeResult.overflown_coords.length) ? routeResult.overflown_names[i] : '';
      legs.push({
        from: routeResult.route[i],
        to: routeResult.route[i + 1],
        dist: dist.toFixed(1),
        time: time > 0 ? time.toFixed(2) : '-',
        altitude: form.altitude,
        diversion,
      });
    }
    legsTable = (
      <table style={{ margin: '1em auto', background: '#222', color: 'white', borderRadius: 8 }}>
        <thead>
          <tr>
            <th>From</th>
            <th>To</th>
            <th>Distance (nm)</th>
            <th>Time (hr)</th>
            <th>Altitude (ft)</th>
            <th>Diversion Airport</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, i) => (
            <tr key={i} style={leg.diversion ? { background: '#333', color: 'yellow' } : {}}>
              <td>{leg.from}</td>
              <td>{leg.to}</td>
              <td>{leg.dist}</td>
              <td>{leg.time}</td>
              <td>{leg.altitude}</td>
              <td>{leg.diversion}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  // Color-coded route segments
  let segmentPolylines = [];
  if (routeResult && routeResult.segments) {
    segmentPolylines = routeResult.segments.map((seg, i) => (
      <Polyline
        key={i}
        positions={[
          [seg.start[0], seg.start[1]],
          [seg.end[0], seg.end[1]]
        ]}
        color={SEGMENT_COLORS[seg.type] || 'lime'}
        weight={5}
      />
    ));
  }

  // Overflown airport markers (diversion airports)
  let diversionMarkers = [];
  if (routeResult && routeResult.overflown_coords && routeResult.overflown_names) {
    diversionMarkers = routeResult.overflown_coords.map((coords, i) => (
      <Marker position={coords} key={i} icon={L.divIcon({ className: '', html: `<svg width='28' height='28'><circle cx='14' cy='14' r='10' fill='yellow' stroke='black' stroke-width='2'/><text x='14' y='19' text-anchor='middle' font-size='10' fill='black'>D</text></svg>` })}>
        <Popup>
          Diversion Airport<br />
          {routeResult.overflown_names[i]}
        </Popup>
      </Marker>
    ));
  }

  return (
    <div className="App">
      <header className="App-header">
        <h1>Cross Country Flight Planner</h1>
        <p>Backend says: {backendMsg}</p>
        <form onSubmit={handleSubmit} style={{ margin: '2em 0' }}>
          <input
            name="origin"
            placeholder="Origin ICAO"
            value={form.origin}
            onChange={handleChange}
            required
            style={{ marginRight: 8 }}
          />
          <input
            name="destination"
            placeholder="Destination ICAO"
            value={form.destination}
            onChange={handleChange}
            required
            style={{ marginRight: 8 }}
          />
          <input
            name="speed"
            placeholder="Speed (knots or mph)"
            value={form.speed}
            onChange={handleChange}
            type="number"
            required
            style={{ marginRight: 8, width: 120 }}
          />
          <select name="altitude" value={form.altitude} onChange={handleVFRAltitudeChange} required style={{ marginRight: 8, width: 160 }}>
            <option value="">Select VFR Altitude</option>
            {vfrAltitudes.map((alt, i) => (
              <option key={i} value={alt}>{alt} ft</option>
            ))}
          </select>
          <input
            name="max_leg_distance"
            placeholder="Max leg distance (nm)"
            value={form.max_leg_distance}
            onChange={handleChange}
            type="number"
            min={50}
            max={500}
            step={10}
            required
            style={{ marginRight: 8, width: 180 }}
            title="Maximum distance between diversion airports (nm)"
          />
          <label style={{ marginRight: 8 }}>
            <input
              name="avoid_airspaces"
              type="checkbox"
              checked={form.avoid_airspaces}
              onChange={handleChange}
            />{' '}
            Avoid airspaces
          </label>
          <label style={{ marginRight: 8 }}>
            <input
              name="avoid_terrain"
              type="checkbox"
              checked={form.avoid_terrain}
              onChange={handleChange}
            />{' '}
            Avoid high terrain
          </label>
          <button type="submit">Plan Route</button>
        </form>
        <button onClick={fetchWeather} disabled={weatherLoading || !form.origin || !form.destination} style={{ marginBottom: 16 }}>
          {weatherLoading ? 'Fetching Weather...' : 'Get Weather for Route'}
        </button>
        {weather && (
          <div style={{ background: '#113', padding: 16, borderRadius: 8, marginBottom: 16 }}>
            <h2>Weather</h2>
            {weather.error ? (
              <p style={{ color: 'red' }}>{weather.error}</p>
            ) : (
              <>
                <h3>Origin ({weather.origin}):</h3>
                <p>{weather.origin_weather.weather ? weather.origin_weather.weather[0].description : 'No data'}</p>
                <p>Temp: {weather.origin_weather.main ? weather.origin_weather.main.temp : 'N/A'}°C</p>
                <h3>Destination ({weather.destination}):</h3>
                <p>{weather.destination_weather.weather ? weather.destination_weather.weather[0].description : 'No data'}</p>
                <p>Temp: {weather.destination_weather.main ? weather.destination_weather.main.temp : 'N/A'}°C</p>
              </>
            )}
          </div>
        )}
        {routeResult && (
          <div style={{ background: '#222', padding: 16, borderRadius: 8 }}>
            <h2>Route Result</h2>
            {routeResult.error ? (
              <p style={{ color: 'red' }}>{routeResult.error}</p>
            ) : (
              <>
                <p>Route: {routeResult.route && routeResult.route.join(' → ')}</p>
                <p>Distance: {routeResult.distance_nm} nm</p>
                <p>Time: {routeResult.time_hr} hr</p>
                <p>Overflown Airports: {routeResult.overflown_airports && routeResult.overflown_airports.join(', ')}</p>
              </>
            )}
          </div>
        )}
        {legsTable}
        <div style={{ width: '80vw', height: '60vh', margin: '2em auto', borderRadius: 8, overflow: 'hidden', position: 'relative' }}>
          {airspacesLoading && <div style={{ position: 'absolute', top: 10, left: 10, color: 'yellow', zIndex: 1000 }}>Loading airspaces...</div>}
          {airspacesError && <div style={{ position: 'absolute', top: 10, left: 10, color: 'red', zIndex: 1000 }}>{airspacesError}</div>}
          <MapContainer center={[39.8283, -98.5795]} zoom={4} style={{ width: '100%', height: '100%' }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <AirspaceOverlay setAirspaces={setAirspaces} />
            {airspacePolygons}
            {originMarker}
            {overflownMarkers}
            {diversionMarkers}
            {destMarker}
            {segmentPolylines}
            {windBarbMarkers}
          </MapContainer>
        </div>
        <ElevationChart profile={terrainProfile} loading={terrainLoading} error={terrainError} />
      </header>
    </div>
  );
}

export default App;
