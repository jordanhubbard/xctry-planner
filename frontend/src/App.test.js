import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

// Mock fetch for backend endpoints
beforeEach(() => {
  global.fetch = jest.fn((url, opts) => {
    if (url.includes('/route')) {
      // Simulate a route with a diversion airport
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          route: ['KJFK', 'DIVERT', 'KBOS'],
          distance_nm: 200,
          time_hr: 1.5,
          overflown_airports: ['DIVERT'],
          origin_coords: [40.6413, -73.7781],
          destination_coords: [42.3656, -71.0096],
          overflown_coords: [[41.5, -72.5]],
          overflown_names: ['Divert Airport'],
          segments: [
            { start: [40.6413, -73.7781], end: [41.5, -72.5], type: 'climb' },
            { start: [41.5, -72.5], end: [42.3656, -71.0096], type: 'descent' }
          ]
        })
      });
    }
    if (url.includes('/terrain-profile')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
          { lat: 40.6413, lon: -73.7781, elevation: 10 },
          { lat: 41.5, lon: -72.5, elevation: 100 },
          { lat: 42.3656, lon: -71.0096, elevation: 20 }
        ])
      });
    }
    if (url.includes('/airspaces')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ features: [] }) });
    }
    if (url.includes('/weather')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          origin: 'KJFK',
          destination: 'KBOS',
          origin_weather: { main: { temp: 20 }, weather: [{ description: 'clear' }] },
          destination_weather: { main: { temp: 18 }, weather: [{ description: 'cloudy' }] },
          wind_points: []
        })
      });
    }
    // Default root
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ message: 'Backend is running' }) });
  });
});

afterEach(() => {
  jest.resetAllMocks();
});

test('renders planner form with all fields', () => {
  render(<App />);
  expect(screen.getByPlaceholderText(/Origin ICAO/i)).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Destination ICAO/i)).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Speed/i)).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Max leg distance/i)).toBeInTheDocument();
  expect(screen.getByText(/Avoid airspaces/i)).toBeInTheDocument();
  expect(screen.getByText(/Avoid high terrain/i)).toBeInTheDocument();
});

test('user can input values and see diversion UI after planning', async () => {
  render(<App />);
  fireEvent.change(screen.getByPlaceholderText(/Origin ICAO/i), { target: { value: 'KJFK' } });
  fireEvent.change(screen.getByPlaceholderText(/Destination ICAO/i), { target: { value: 'KBOS' } });
  fireEvent.change(screen.getByPlaceholderText(/Speed/i), { target: { value: '120' } });
  fireEvent.change(screen.getByPlaceholderText(/Max leg distance/i), { target: { value: '30' } });
  // Select VFR altitude (simulate dropdown)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '3500' } });
  fireEvent.click(screen.getByText(/Plan Route/i));

  // Wait for route result
  await waitFor(() => expect(screen.getByText(/Route Result/i)).toBeInTheDocument());
  expect(screen.getByText(/DIVERT/)).toBeInTheDocument();
  expect(screen.getByText(/Overflown Airports/i)).toBeInTheDocument();
  expect(screen.getByText(/Divert Airport/)).toBeInTheDocument();

  // Legs table should show diversion airport
  expect(screen.getByText(/Diversion Airport/i)).toBeInTheDocument();
  expect(screen.getAllByText(/Divert Airport/).length).toBeGreaterThan(0);

  // Map should have a diversion marker (look for SVG with 'D')
  // (We can't fully test Leaflet rendering, but can check for SVG in the DOM)
  expect(document.querySelector('svg')).toBeInTheDocument();
});
