import React, { useEffect, useState, useRef } from 'react';
import './App.css';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Polygon, useMapEvent, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

function WindBarbMarker({ lat, lon, wind_deg, wind_speed }) {
  // Standard VFR wind barb SVG
  // wind_deg: direction wind is FROM (meteorological)
  // wind_speed: in knots
  const speed = wind_speed ? Math.round(wind_speed) : 0;
  let remaining = speed;
  const barbs = [];
  let y = 6; // Start 6px from top
  // Staff: always 24px long
  // Draw triangles (50kt)
  let x0 = 16, y0 = 28, x1 = 16, y1 = 4;
  let barbX = x1, barbY = y1;
  let barbLen = 12;
  let barbAngle = 60 * Math.PI / 180; // 60 degrees
  let pos = 0;
  while (remaining >= 50) {
    // Triangle (flag)
    barbs.push(<polygon key={pos} points={`${barbX},${barbY} ${barbX + barbLen * Math.cos(barbAngle)},${barbY + barbLen * Math.sin(barbAngle)} ${barbX},${barbY + 6}`} fill="black" />);
    barbY += 6;
    remaining -= 50;
    pos++;
  }
  while (remaining >= 10) {
    // Full barb
    barbs.push(<line key={pos} x1={barbX} y1={barbY} x2={barbX + barbLen * Math.cos(barbAngle)} y2={barbY + barbLen * Math.sin(barbAngle)} stroke="black" strokeWidth="2" />);
    barbY += 4;
    remaining -= 10;
    pos++;
  }
  if (remaining >= 5) {
    // Half barb
    barbs.push(<line key={pos} x1={barbX} y1={barbY} x2={barbX + barbLen * Math.cos(barbAngle) * 0.5} y2={barbY + barbLen * Math.sin(barbAngle) * 0.5} stroke="black" strokeWidth="2" />);
  }
  return (
    <Marker position={[lat, lon]} icon={L.divIcon({
      className: '',
      html: `<svg width='32' height='32' style='transform: rotate(${wind_deg || 0}deg);'>
        <g>
          <line x1='16' y1='28' x2='16' y2='4' stroke='black' stroke-width='3' />
        </g>
        ${barbs.map(b => b.props ? b.props.points ? `<polygon points='${b.props.points}' fill='black' />` : `<line x1='${b.props.x1}' y1='${b.props.y1}' x2='${b.props.x2}' y2='${b.props.y2}' stroke='black' stroke-width='2' />` : '').join('')}
        <text x='16' y='30' text-anchor='middle' font-size='10' fill='black'>${speed}</text>
      </svg>`
    })} />
  );
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

// Weather category function
function getWeatherCategory(wx) {
  if (!wx || !wx.weather || !wx.main) return { cat: 'Unknown', color: '#888' };
  // Visibility in meters, convert to sm
  const vis = wx.visibility ? wx.visibility / 1609.34 : null;
  // Find lowest cloud base (if any)
  let ceiling = null;
  if (wx.clouds && wx.clouds.all !== undefined) {
    // OpenWeatherMap does not provide cloud base directly, so we can't get true ceiling
    // For demo, treat scattered/broken/overcast as 1500 ft if clouds.all > 40, else 5000 ft
    ceiling = wx.clouds.all > 40 ? 1500 : 5000;
  }
  // VFR: ceiling > 3000 ft and vis > 5sm
  // MVFR: ceiling 1000-3000 or vis 3-5
  // IFR: ceiling 500-1000 or vis 1-3
  // LIFR: ceiling < 500 or vis < 1
  if ((ceiling === null || ceiling > 3000) && vis !== null && vis > 5) return { cat: 'VFR', color: '#00FF00' };
  if ((ceiling !== null && ceiling > 1000 && ceiling <= 3000) || (vis !== null && vis > 3 && vis <= 5)) return { cat: 'MVFR', color: '#3399FF' };
  if ((ceiling !== null && ceiling > 500 && ceiling <= 1000) || (vis !== null && vis > 1 && vis <= 3)) return { cat: 'IFR', color: '#FF3333' };
  if ((ceiling !== null && ceiling <= 500) || (vis !== null && vis <= 1)) return { cat: 'LIFR', color: '#FF00FF' };
  return { cat: 'Unknown', color: '#888' };
}

// Fit map to route bounds when route changes
function FitRouteBounds({ routeResult }) {
  const map = useMap();
  React.useEffect(() => {
    if (routeResult && routeResult.origin_coords && routeResult.destination_coords) {
      const points = [routeResult.origin_coords, ...(routeResult.overflown_coords || []), routeResult.destination_coords];
      if (points.length > 1) {
        const bounds = L.latLngBounds(points.map(([lat, lon]) => [lat, lon]));
        map.fitBounds(bounds.pad(0.25), { animate: true });
      }
    }
  }, [routeResult, map]);
  return null;
}

function getRecommendedVFRAltitude(heading, minAltitude) {
  // Odd thousands + 500 for 0-179, even + 500 for 180-359
  let base = heading < 180 ? 3500 : 4500;
  while (base < minAltitude) base += 2000;
  return base;
}

function App() {
  const [backendMsg, setBackendMsg] = useState('');
  const [form, setForm] = useState({
    origin: '',
    destination: '',
    speed: '',
    speed_unit: 'knots',
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
  const [terrainProfile, setTerrainProfile] = useState([]);
  const [terrainLoading, setTerrainLoading] = useState(false);
  const [terrainError, setTerrainError] = useState(null);
  const [selectedLeg, setSelectedLeg] = useState(null);
  const [legPopup, setLegPopup] = useState(null);
  const [legLoading, setLegLoading] = useState(false);
  const [legTerrain, setLegTerrain] = useState([]); // [{maxElev, loading, error}]
  const [legTerrainLoading, setLegTerrainLoading] = useState(false);

  useEffect(() => {
    fetch('http://localhost:8000/')
      .then((res) => res.json())
      .then((data) => setBackendMsg(data.message))
      .catch(() => setBackendMsg('Could not reach backend'));
  }, []);

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

  // Fetch terrain for all legs when route changes and avoid_terrain is checked
  useEffect(() => {
    if (
      routeResult &&
      routeResult.route &&
      routeResult.route.length >= 2 &&
      form.avoid_terrain
    ) {
      const points = [routeResult.origin_coords, ...(routeResult.overflown_coords || []), routeResult.destination_coords];
      setLegTerrainLoading(true);
      Promise.all(
        points.slice(0, -1).map((from, i) => {
          const to = points[i + 1];
          return fetch('http://localhost:8000/terrain-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: [from, to] }),
          })
            .then((res) => res.json())
            .then((data) => ({
              maxElev: Math.max(...data.map((p) => p.elevation || 0)),
              error: null,
            }))
            .catch(() => ({ maxElev: 0, error: 'Could not fetch terrain' }));
        })
      ).then((results) => {
        setLegTerrain(results);
        setLegTerrainLoading(false);
      });
    } else {
      setLegTerrain([]);
      setLegTerrainLoading(false);
    }
  }, [routeResult, form.avoid_terrain]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
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
      .then((result) => {
        setRouteResult(result);
        if (!result.error) fetchWeather();
      })
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
    let prevAlt = parseInt(form.altitude, 10) || 0;
    let magVar = 13; // Demo: fixed 13°W for CONUS
    for (let i = 0; i < points.length - 1; i++) {
      const from = points[i];
      const to = points[i + 1];
      const dist = haversine(from[0], from[1], to[0], to[1]);
      const time = form.speed ? dist / parseFloat(form.speed) : 0;
      let diversion = '';
      if (routeResult.overflown_coords && routeResult.overflown_coords.length > 0 && i < routeResult.overflown_coords.length) {
        const icao = routeResult.overflown_airports && routeResult.overflown_airports[i] ? routeResult.overflown_airports[i] : '';
        const name = routeResult.overflown_names && routeResult.overflown_names[i] ? routeResult.overflown_names[i] : '';
        diversion = icao && name ? `${icao} — ${name}` : (icao || name);
      }
      const course = calculateCourse(from[0], from[1], to[0], to[1]);
      let magHeading = course - magVar;
      if (magHeading < 0) magHeading += 360;
      // VFR altitude logic
      let vfrAlt = magHeading < 180 ? 3500 : 4500;
      while (vfrAlt < prevAlt) vfrAlt += 2000;
      // Terrain logic
      let minAlt = prevAlt;
      let altUsed = prevAlt;
      let maxElev = 0;
      let terrainError = null;
      if (form.avoid_terrain && legTerrain && legTerrain[i]) {
        maxElev = legTerrain[i].maxElev;
        terrainError = legTerrain[i].error;
        minAlt = Math.max(prevAlt, vfrAlt, maxElev + 2000);
        altUsed = minAlt;
      } else {
        altUsed = Math.max(prevAlt, vfrAlt);
      }
      legs.push({
        from: routeResult.route[i],
        to: routeResult.route[i + 1],
        dist: dist.toFixed(1),
        time: time > 0 ? time.toFixed(2) : '-',
        magHeading: magHeading.toFixed(0),
        vfrAlt: vfrAlt.toFixed(0),
        altUsed: altUsed.toFixed(0),
        maxElev: maxElev ? maxElev.toFixed(0) : '',
        terrainError,
        diversion,
      });
      // Descend if possible for next leg
      if (form.avoid_terrain && altUsed > prevAlt && (!legTerrain[i + 1] || (legTerrain[i + 1] && altUsed > Math.max(parseInt(form.altitude, 10) || 0, vfrAlt)))) {
        prevAlt = Math.max(parseInt(form.altitude, 10) || 0, vfrAlt);
      } else {
        prevAlt = altUsed;
      }
    }
    legsTable = (
      <table style={{ margin: '1em auto', background: '#222', color: 'white', borderRadius: 8 }}>
        <thead>
          <tr>
            <th>From</th>
            <th>To</th>
            <th>Distance (nm)</th>
            <th>Time (hr)</th>
            <th>Mag Heading</th>
            <th>VFR Altitude</th>
            <th>Altitude Used</th>
            {form.avoid_terrain && <th>Max Terrain (ft)</th>}
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
              <td>{leg.magHeading}</td>
              <td>{leg.vfrAlt}</td>
              <td>{leg.altUsed}</td>
              {form.avoid_terrain && <td>{leg.terrainError ? <span style={{ color: 'red' }}>{leg.terrainError}</span> : leg.maxElev}</td>}
              <td>{leg.diversion}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
    if (form.avoid_terrain && legTerrainLoading) {
      legsTable = <div style={{ color: 'yellow', margin: '1em' }}>Loading terrain for legs...</div>;
    }
  }

  // Route Result as a compact row above the legs table
  let routeSummaryRow = null;
  if (routeResult && !routeResult.error && routeResult.route && routeResult.route.length >= 2) {
    routeSummaryRow = (
      <table style={{ margin: '1em auto', background: '#222', color: 'white', borderRadius: 8, minWidth: 700 }}>
        <thead>
          <tr>
            <th style={{ minWidth: 120 }}>From</th>
            <th style={{ minWidth: 120 }}>To</th>
            <th>Distance (nm)</th>
            <th>Time (hr)</th>
            <th>Overflown Airports</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ fontWeight: 600 }}>{routeResult.route[0]}</td>
            <td style={{ fontWeight: 600 }}>{routeResult.route[routeResult.route.length - 1]}</td>
            <td>{routeResult.distance_nm}</td>
            <td>{routeResult.time_hr}</td>
            <td>{routeResult.overflown_airports && routeResult.overflown_airports.length > 0 ? routeResult.overflown_airports.join(', ') : '-'}</td>
          </tr>
        </tbody>
      </table>
    );
  }

  // Color-coded route segments (now clickable)
  let segmentPolylines = [];
  if (routeResult && routeResult.segments) {
    segmentPolylines = routeResult.segments.map((seg, i) => {
      const from = seg.start;
      const to = seg.end;
      const mid = [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2];
      return (
        <Polyline
          key={i}
          positions={[[from[0], from[1]], [to[0], to[1]]]}
          color={SEGMENT_COLORS[seg.type] || 'lime'}
          weight={5}
          eventHandlers={{
            click: async () => {
              setLegLoading(true);
              const course = calculateCourse(from[0], from[1], to[0], to[1]);
              const magVar = 13; // Demo: fixed 13°W for CONUS
              let magHeading = course - magVar;
              if (magHeading < 0) magHeading += 360;
              let minAlt = 0;
              let terrainMsg = '';
              if (form.avoid_terrain) {
                // Fetch terrain profile for this leg
                try {
                  const res = await fetch('http://localhost:8000/terrain-profile', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ points: [from, to] }),
                  });
                  const data = await res.json();
                  const maxElev = Math.max(...data.map(p => p.elevation || 0));
                  minAlt = maxElev + 1000;
                  terrainMsg = `Highest terrain: ${maxElev.toFixed(0)} ft. Must cruise at least ${minAlt.toFixed(0)} ft.`;
                } catch {
                  terrainMsg = 'Could not fetch terrain info.';
                }
              }
              const vfrAlt = getRecommendedVFRAltitude(magHeading, minAlt);
              setLegPopup({
                lat: mid[0],
                lon: mid[1],
                content: (
                  <div style={{ minWidth: 200 }}>
                    <b>Leg {i + 1}</b><br />
                    Magnetic Heading: {magHeading.toFixed(0)}°<br />
                    Recommended VFR Altitude: {vfrAlt.toFixed(0)} ft<br />
                    {terrainMsg && <span>{terrainMsg}<br /></span>}
                  </div>
                )
              });
              setLegLoading(false);
            }
          }}
        />
      );
    });
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

  // Weather status dots for each airport
  let airportWeatherMarkers = [];
  if (weather && routeResult && routeResult.origin_coords && routeResult.destination_coords) {
    // Origin
    const originWx = weather.origin_weather;
    const { cat: originCat, color: originColor } = getWeatherCategory(originWx);
    airportWeatherMarkers.push(
      <Marker key="origin-wx" position={routeResult.origin_coords} icon={L.divIcon({ className: '', html: `<svg width='18' height='18'><circle cx='9' cy='9' r='7' fill='${originColor}' stroke='black' stroke-width='2'/></svg>` })}>
        <Popup>
          <b>{weather.origin} Weather: {originCat}</b><br />
          {originWx.weather && originWx.weather[0] && originWx.weather[0].description ? originWx.weather[0].description : 'No data'}
        </Popup>
      </Marker>
    );
    // Destination
    const destWx = weather.destination_weather;
    const { cat: destCat, color: destColor } = getWeatherCategory(destWx);
    airportWeatherMarkers.push(
      <Marker key="dest-wx" position={routeResult.destination_coords} icon={L.divIcon({ className: '', html: `<svg width='18' height='18'><circle cx='9' cy='9' r='7' fill='${destColor}' stroke='black' stroke-width='2'/></svg>` })}>
        <Popup>
          <b>{weather.destination} Weather: {destCat}</b><br />
          {destWx.weather && destWx.weather[0] && destWx.weather[0].description ? destWx.weather[0].description : 'No data'}
        </Popup>
      </Marker>
    );
    // Overflown airports (if any, and if weather data available)
    if (routeResult.overflown_coords && routeResult.overflown_airports) {
      routeResult.overflown_coords.forEach((coords, i) => {
        // For demo, use origin weather for all (real: fetch each airport's weather)
        const { cat, color } = getWeatherCategory(originWx);
        airportWeatherMarkers.push(
          <Marker key={`overflown-wx-${i}`} position={coords} icon={L.divIcon({ className: '', html: `<svg width='18' height='18'><circle cx='9' cy='9' r='7' fill='${color}' stroke='black' stroke-width='2'/></svg>` })}>
            <Popup>
              <b>{routeResult.overflown_airports[i]} Weather: {cat}</b><br />
              {originWx.weather && originWx.weather[0] && originWx.weather[0].description ? originWx.weather[0].description : 'No data'}
            </Popup>
          </Marker>
        );
      });
    }
  }

  // Add a marker for the selected leg popup
  let legPopupMarker = null;
  if (legPopup) {
    legPopupMarker = (
      <Marker position={[legPopup.lat, legPopup.lon]} icon={L.divIcon({ className: '', html: `<svg width='1' height='1'></svg>` })}>
        <Popup position={[legPopup.lat, legPopup.lon]} onClose={() => setLegPopup(null)}>
          {legLoading ? 'Loading...' : legPopup.content}
        </Popup>
      </Marker>
    );
  }

  return (
    <div className="App">
      <header className="App-header">
        <h1>Cross Country Flight Planner</h1>
        {backendMsg !== 'Backend is running' && (
          <p>Backend says: {backendMsg}</p>
        )}
        <div style={{
          background: 'rgba(30, 32, 40, 0.95)',
          padding: '2em',
          borderRadius: 16,
          boxShadow: '0 4px 24px rgba(0,0,0,0.15)',
          maxWidth: 1100,
          margin: '2em auto 1em auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}>
          <form onSubmit={handleSubmit} style={{ width: '100%' }}>
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 24,
              alignItems: 'flex-end',
              justifyContent: 'center',
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 160 }}>
                <label htmlFor="origin" style={{ fontWeight: 500, marginBottom: 6 }}>Origin</label>
                <input
                  id="origin"
                  name="origin"
                  placeholder="e.g. KJFK"
                  value={form.origin}
                  onChange={handleChange}
                  required
                  style={{ padding: '10px 12px', borderRadius: 6, border: '1px solid #888', fontSize: 16 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 160 }}>
                <label htmlFor="destination" style={{ fontWeight: 500, marginBottom: 6 }}>Destination</label>
                <input
                  id="destination"
                  name="destination"
                  placeholder="e.g. KBOS"
                  value={form.destination}
                  onChange={handleChange}
                  required
                  style={{ padding: '10px 12px', borderRadius: 6, border: '1px solid #888', fontSize: 16 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 160 }}>
                <label htmlFor="speed" style={{ fontWeight: 500, marginBottom: 6 }}>Speed</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    id="speed"
                    name="speed"
                    placeholder="e.g. 120"
                    value={form.speed}
                    onChange={handleChange}
                    type="number"
                    required
                    style={{ padding: '10px 12px', borderRadius: 6, border: '1px solid #888', fontSize: 16, width: 100 }}
                  />
                  <select name="speed_unit" value={form.speed_unit} onChange={handleChange} style={{ padding: '8px', borderRadius: 6, border: '1px solid #888', fontSize: 15 }}>
                    <option value="knots">knots</option>
                    <option value="mph">mph</option>
                  </select>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 180 }}>
                <label htmlFor="altitude" style={{ fontWeight: 500, marginBottom: 6 }}>Cruise Altitude</label>
                <input
                  id="altitude"
                  name="altitude"
                  placeholder="feet"
                  value={form.altitude}
                  onChange={handleChange}
                  type="number"
                  required
                  style={{ padding: '10px 12px', borderRadius: 6, border: '1px solid #888', fontSize: 16 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 180 }}>
                <label htmlFor="max_leg_distance" style={{ fontWeight: 500, marginBottom: 6 }}>Max Leg Distance</label>
                <input
                  id="max_leg_distance"
                  name="max_leg_distance"
                  placeholder="nm"
                  value={form.max_leg_distance}
                  onChange={handleChange}
                  type="number"
                  min={50}
                  max={500}
                  step={10}
                  required
                  style={{ padding: '10px 12px', borderRadius: 6, border: '1px solid #888', fontSize: 16 }}
                  title="Maximum distance between diversion airports (nm)"
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 180, marginTop: 18 }}>
                <div style={{ display: 'flex', gap: 12 }}>
                  <label style={{ fontWeight: 400, fontSize: 15 }}>
                    <input
                      name="avoid_airspaces"
                      type="checkbox"
                      checked={form.avoid_airspaces}
                      onChange={handleChange}
                      style={{ marginRight: 6 }}
                    />
                    Avoid airspaces
                  </label>
                  <label style={{ fontWeight: 400, fontSize: 15 }}>
                    <input
                      name="avoid_terrain"
                      type="checkbox"
                      checked={form.avoid_terrain}
                      onChange={handleChange}
                      style={{ marginRight: 6 }}
                    />
                    Avoid high terrain
                  </label>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', minWidth: 120, marginTop: 18 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" style={{ padding: '12px 24px', borderRadius: 6, fontSize: 16, fontWeight: 600, background: '#2e7dff', color: 'white', border: 'none', boxShadow: '0 2px 8px rgba(30,60,180,0.08)', cursor: 'pointer' }}>Plan Route</button>
                  <button type="button" onClick={fetchWeather} disabled={weatherLoading || !form.origin || !form.destination} style={{ padding: '12px 18px', borderRadius: 6, fontSize: 16, fontWeight: 600, background: '#444', color: 'white', border: 'none', boxShadow: '0 2px 8px rgba(30,60,180,0.08)', cursor: 'pointer' }}>
                    {weatherLoading ? 'Refreshing...' : 'Refresh Weather'}
                  </button>
                </div>
              </div>
            </div>
          </form>
        </div>
        {/* Move the map up, right after the form/buttons */}
        <div style={{ width: '80vw', height: '60vh', margin: '2em auto 1em auto', borderRadius: 8, overflow: 'hidden', position: 'relative' }}>
          {airspacesLoading && <div style={{ position: 'absolute', top: 10, left: 10, color: 'yellow', zIndex: 1000 }}>Loading airspaces...</div>}
          {airspacesError && <div style={{ position: 'absolute', top: 10, left: 10, color: 'red', zIndex: 1000 }}>{airspacesError}</div>}
          <MapContainer center={[39.8283, -98.5795]} zoom={4} style={{ width: '100%', height: '100%' }}>
            <FitRouteBounds routeResult={routeResult} />
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
            {airportWeatherMarkers}
            {segmentPolylines}
            {legPopupMarker}
            {windBarbMarkers}
          </MapContainer>
        </div>
        {/* Weather info as a compact row above the legs table */}
        {weather && !weather.error && routeResult && !routeResult.error && (
          <table style={{ margin: '1em auto', background: '#113', color: 'white', borderRadius: 8, minWidth: 900 }}>
            <thead>
              <tr>
                <th style={{ minWidth: 120 }}>Origin</th>
                <th>Status</th>
                <th>Temp (°C)</th>
                <th>Wind</th>
                <th style={{ minWidth: 120 }}>Destination</th>
                <th>Status</th>
                <th>Temp (°C)</th>
                <th>Wind</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 600 }}>{weather.origin}</td>
                <td>{getWeatherCategory(weather.origin_weather).cat}</td>
                <td>{weather.origin_weather.main ? weather.origin_weather.main.temp : 'N/A'}</td>
                <td>{weather.origin_weather.wind && weather.origin_weather.wind.speed !== undefined && weather.origin_weather.wind.deg !== undefined ? `${weather.origin_weather.wind.deg}° @ ${(weather.origin_weather.wind.speed * 1.94384).toFixed(1)} kt` : 'N/A'}</td>
                <td style={{ fontWeight: 600 }}>{weather.destination}</td>
                <td>{getWeatherCategory(weather.destination_weather).cat}</td>
                <td>{weather.destination_weather.main ? weather.destination_weather.main.temp : 'N/A'}</td>
                <td>{weather.destination_weather.wind && weather.destination_weather.wind.speed !== undefined && weather.destination_weather.wind.deg !== undefined ? `${weather.destination_weather.wind.deg}° @ ${(weather.destination_weather.wind.speed * 1.94384).toFixed(1)} kt` : 'N/A'}</td>
              </tr>
            </tbody>
          </table>
        )}
        {weather && weather.error && (
          <div style={{ background: '#113', color: 'red', padding: 8, borderRadius: 8, margin: '1em auto', maxWidth: 700 }}>{weather.error}</div>
        )}
        {routeResult && routeResult.error && (
          <div style={{ background: '#222', padding: 16, borderRadius: 8, color: 'red', marginBottom: 16 }}>{routeResult.error}</div>
        )}
        {routeSummaryRow}
        {legsTable}
        <ElevationChart profile={terrainProfile} loading={terrainLoading} error={terrainError} />
      </header>
    </div>
  );
}

export default App;
