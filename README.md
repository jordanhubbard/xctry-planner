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

## API Keys Required

This application requires API keys for the following services:

### 1. OpenWeatherMap
- **Purpose:** Fetches current weather and wind data for airports and route points.
- **Get your key:** [Sign up at OpenWeatherMap](https://home.openweathermap.org/users/sign_up)
- **API key name:** `OPENWEATHERMAP_API_KEY`

### 2. OpenAIP
- **Purpose:** Fetches authoritative airport and airspace data for the United States.
- **Get your key:** [Register for a free OpenAIP account](https://www.openaip.net/)
- **API key name:** `OPENAIP_API_KEY`

## Setting up your `.env` file

Create a file named `.env` in the project root (same directory as `docker-compose.yml`). Add the following lines, replacing the values with your actual API keys:

```ini
OPENWEATHERMAP_API_KEY=your_openweathermap_key_here
OPENAIP_API_KEY=your_openaip_key_here
```

- **Never commit your `.env` file to version control.** It is already included in `.gitignore` for safety.
- You may also create `.env.local` or other variants for different environments.

## Using API Keys in Deployment

- **Docker Compose:** The backend service automatically loads these keys from the `.env` file at startup.
- **Local Development:** The backend will also read the `.env` file if you run it outside Docker.

## Security Tips
- Treat your API keys as secrets. Never share or commit them.
- Rotate your keys if you believe they have been exposed.
- For production, consider using a secrets manager or environment variable injection.

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

## Large Files: Git LFS

This repository uses [Git Large File Storage (LFS)](https://git-lfs.github.com/) to manage large data files (such as airports_us.json, airspaces_us.json, and other .json/.geojson/.csv files in the backend directory).

### How to use Git LFS
- **Install Git LFS:**
  - macOS: `brew install git-lfs`
  - Ubuntu: `sudo apt-get install git-lfs`
  - Windows: [Download installer](https://git-lfs.github.com/)
- **Initialize in your repo:**
  - `git lfs install`
- **Clone with LFS support:**
  - `git clone <repo-url>` (LFS files will be fetched automatically)
- **If you add or update large files:**
  - They will be tracked automatically if they match the patterns in `.gitattributes`.
  - Commit and push as usual; LFS will handle the large files.

**Note:** If you do not have Git LFS installed, large files will appear as small pointer files and the app will not work correctly.

## License
This project is for demonstration and educational use. Data sources may have their own licenses and restrictions. 