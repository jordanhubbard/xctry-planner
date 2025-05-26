# Cross Country Flight Planning Web Application

## Overview
A web application for aviators to plan cross-country flights between two airports, considering airspace, terrain, weather, and safety (overflying airports). The app visually plots the route, overlays weather, wind, airspace, and terrain data, and allows user preferences for route planning.

## Features
- Specify origin and destination airports by ICAO code
- Planned speed (knots or mph), cruise altitude, and VFR altitude dropdown
- Checkboxes for "avoid airspaces" and "avoid high terrain"
- Map overlays: route, airports, overflown airports, airspaces, weather, wind barbs, and terrain
- Table view of all flight legs (distance, time, altitude, endpoints)
- Elevation profile chart for the route
- Robust error handling and loading states
- Fully containerized with Docker Compose

## Data Sources
- **Airport Data:** [OurAirports](https://ourairports.com/data/airports.csv)
- **Airspace Data:** [Swiss FSVL Airspace GeoJSON](https://airspace.shv-fsvl.ch/api/beta/geojson/airspaces) (demo)
- **Weather & Wind:** [OpenWeatherMap API](https://openweathermap.org/api)
- **Terrain:** [OpenTopography SRTM API](https://portal.opentopography.org/)

## Setup & Usage

### Prerequisites
- Docker and Docker Compose installed
- (Optional) OpenWeatherMap API key (set in docker-compose.yml)

### Quick Start
1. Clone the repository:
   ```sh
   git clone <repo-url>
   cd xctry-planner
   ```
2. (Optional) Set your OpenWeatherMap API key in `docker-compose.yml`:
   ```yaml
   environment:
     - OPENWEATHERMAP_API_KEY=your_api_key_here
   ```
3. Build and start the containers:
   ```sh
   docker compose up --build
   ```
4. Open your browser to [http://localhost:3000](http://localhost:3000)

### Development
- Source code is bind-mounted for live reload.
- Backend: FastAPI (Python 3.11)
- Frontend: React (Node 20, Leaflet.js)

## Notes
- Airspace overlay uses Swiss data for demonstration; swap in other country files as needed.
- Terrain and weather APIs are public/free for demo but may have rate limits.
- All logic runs in containers; no host dependencies required.

## License
This project is for demonstration and educational use. Data sources may have their own licenses and restrictions. 