# Cross Country Flight Planning Web Application: Implementation Plan

## 1. Project Overview
A web application for aviators to plan cross-country flights between two airports, considering airspace, terrain, weather, and safety (overflying airports). The app will visually plot the route, overlay weather and wind data, and allow user preferences for route planning.

---

## 2. Tech Stack & Containerization Approach
- All components must run in docker containers to allow the application to run on any linux host
- **Backend:** Python (FastAPI), developed and run in a container based on the official `python:3.11-slim` DockerHub image.
- **Frontend:** React (with Leaflet.js for mapping), developed and run in a container based on the official `node:20-alpine` DockerHub image.
- **Data Sources:**
  - Aviation Maps: OpenAIP, FAA Sectionals, or similar
  - Airport Data: OurAirports, OpenAIP
  - Weather: OpenWeatherMap API
- **Orchestration:** Docker Compose to manage multi-container setup (backend, frontend, and optionally a reverse proxy like Nginx for production best practices).
- **Best Practices:**
  - Separate containers for backend and frontend for modularity and scalability.
  - Use environment variables for configuration and secrets.
  - Bind-mount source code for live development, or use multi-stage builds for production images.
  - Optionally, use a reverse proxy (Nginx) container for production to serve the frontend and proxy API requests to the backend.

---

## 3. Features & UI Elements
### Input Section
- Origin ICAO (autocomplete)
- Destination ICAO (autocomplete)
- Planned Speed (knots or mph, toggle)
- Cruise Altitude (number input)
- VFR Altitude Dropdown (auto-suggest based on course)
- Checkboxes: Avoid airspaces, Avoid high terrain

### Map Section
- Base Map: VFR sectional or OpenAIP tiles
- Route Plot: Polyline for planned route (may deviate for airspace/terrain/airport overflight)
- Airports: Markers for origin, destination, and suggested overflight airports
- Weather Overlay: OpenWeatherMap layers (clouds, precipitation, wind)
- Wind Barbs: Standard wind barb symbols along route (every 20nm)
- Route Segments: Color-coded for climb, cruise, descent, and weather impact
- Annotate possible diversion airports for any leg >= 50nm
- Table view of all flight legs which lists the endpoints for that route, the distance of the leg in nm, the approximate time en route using the user entered cruise speed, and the altitude for that segment.
---

## 4. Implementation Steps

### 4.1. Project Setup
- [x] Initialize Git repository
- [x] Create backend and frontend directories
- [x] Create Dockerfile placeholders for backend and frontend, and a docker-compose.yml file

### 4.2. Backend Development (in Docker)
- [ ] Write a Dockerfile for backend using `python:3.11-slim` as base
- [ ] Set up FastAPI project structure in backend directory
- [ ] Implement endpoint: Airport lookup (ICAO to lat/lon, elevation, runways)
- [ ] Implement endpoint: Route calculation (direct, then with airspace/terrain/airport constraints)
- [ ] Integrate airspace and terrain data (OpenAIP or similar)
- [ ] Implement endpoint: Weather fetch (OpenWeatherMap API for route corridor)
- [ ] Implement endpoint: Wind data extraction and interpolation
- [ ] Write tests for backend endpoints

### 4.3. Frontend Development (in Docker)
- [ ] Write a Dockerfile for frontend using `node:20-alpine` as base
- [ ] Initialize React project in frontend directory (using Docker container)
- [ ] Build input form (origin, destination, speed, altitude, checkboxes)
- [ ] Implement VFR altitude dropdown logic
- [ ] Display map with aviation tiles
- [ ] Plot route from backend
- [ ] Overlay airports, weather, and wind barbs
- [ ] Color-code route segments
- [ ] Show route summary (distance, time, altitudes, airports overflown, weather hazards)

### 4.4. Data Integration
- [ ] Download/cache airport, airspace, and terrain data (in backend container)
- [ ] Set up scheduled updates for data sources

### 4.5. Weather & Wind Visualization
- [ ] Fetch and display weather overlays from OpenWeatherMap
- [ ] Draw wind barbs along route (every 20nm)
- [ ] Indicate weather/wind impact on route segments

### 4.6. Dockerization & Orchestration
- [ ] Write Dockerfile for backend (FastAPI, Python base)
- [ ] Write Dockerfile for frontend (React, Node base)
- [ ] Set up docker-compose.yml to run backend and frontend containers together
- [ ] (Optional for production) Add Nginx container as reverse proxy
- [ ] Test build and run in containerized environment

### 4.7. Finalization
- [ ] Polish UI/UX
- [ ] Add error handling and loading states
- [ ] Write documentation (README.md)
- [ ] Prepare for deployment (multi-stage Docker builds, production Compose file)

---

## 5. Data Sources & API Keys
- [ ] Register and store OpenWeatherMap API key (use Docker secrets or environment variables)
- [ ] Document sources for airport, airspace, and terrain data

---

## 6. Future Enhancements (Optional)
- [ ] User authentication and saved plans
- [ ] Export/print flight plan
- [ ] Mobile-friendly UI
- [ ] More advanced route optimization (fuel stops, NOTAMs, etc.) 
