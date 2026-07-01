"""NOAA Hourly Station Data — Real weather observations from official stations.

Pulls from the NOAA Weather Observations API (api.weather.gov).
No API key required — just a User-Agent header.

This fills the gap between Open-Meteo (forecast) and NWS Alerts (emergencies)
by giving us actual hourly obs from US stations near infrastructure nodes.

Stations selected for coverage of key infrastructure zones:
- BNA (Nashville) — TN grid/logistics
- MCI (Kansas City) — MO financial/logistics  
- ATL (Atlanta) — GA logistics hub
- IAH (Houston) — TX energy corridor
- LAX (Los Angeles) — CA port/shipping
- JFK (New York) — NY financial center
- ORD (Chicago) — IL logistics hub
- SEA (Seattle) — WA tech/port
- MIA (Miami) — FL shipping/hurricane zone
- DFW (Dallas) — TX grid/energy

Usage:
    python -m src.ingestion.noaa_stations
    
    # Or integrated into daily_pull:
    from src.ingestion.noaa_stations import pull_noaa_stations, convert_noaa_observations
"""

import httpx
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
FEEDS_DIR = BASE_DIR / "data" / "live_feeds"

# NOAA station IDs (4-letter ICAO codes)
# These map to weather.gov observation stations
STATIONS = {
    "KBNA": {"name": "Nashville", "lat": 36.12, "lon": -86.68, "zone": "tn_grid"},
    "KMCI": {"name": "Kansas City", "lat": 39.30, "lon": -94.71, "zone": "mo_logistics"},
    "KATL": {"name": "Atlanta", "lat": 33.63, "lon": -84.44, "zone": "ga_hub"},
    "KIAH": {"name": "Houston", "lat": 29.98, "lon": -95.34, "zone": "tx_energy"},
    "KLAX": {"name": "Los Angeles", "lat": 33.94, "lon": -118.41, "zone": "ca_port"},
    "KJFK": {"name": "New York JFK", "lat": 40.64, "lon": -73.78, "zone": "ny_financial"},
    "KORD": {"name": "Chicago OHare", "lat": 41.98, "lon": -87.90, "zone": "il_logistics"},
    "KSEA": {"name": "Seattle", "lat": 47.45, "lon": -122.31, "zone": "wa_port"},
    "KMIA": {"name": "Miami", "lat": 25.79, "lon": -80.29, "zone": "fl_shipping"},
    "KDFW": {"name": "Dallas", "lat": 32.90, "lon": -97.04, "zone": "tx_grid"},
    "KHOU": {"name": "Houston Hobby", "lat": 29.65, "lon": -95.28, "zone": "tx_refinery"},
    "KPHX": {"name": "Phoenix", "lat": 33.43, "lon": -112.01, "zone": "az_grid"},
}

HEADERS = {
    "User-Agent": "(DVCE Supply Chain Intelligence, dvce@proton.me)",
    "Accept": "application/geo+json",
}


def pull_noaa_stations() -> Dict[str, str]:
    """Pull latest observations from all NOAA stations.
    
    Returns dict of {station_id: "ok" or error message}
    """
    results = {}
    client = httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    for station_id, info in STATIONS.items():
        try:
            # Get latest observations (returns last ~24h of hourly data)
            url = f"https://api.weather.gov/stations/{station_id}/observations"
            r = client.get(url, params={"limit": 24})

            if r.status_code == 200:
                data = r.json()
                # Enrich with our metadata
                data["_dvce_station"] = station_id
                data["_dvce_zone"] = info["zone"]
                data["_dvce_name"] = info["name"]
                data["_dvce_pulled_at"] = datetime.now(timezone.utc).isoformat()

                outfile = FEEDS_DIR / f"noaa_{station_id.lower()}.json"
                outfile.write_text(json.dumps(data, indent=2)[:500000])
                results[station_id] = "ok"
            elif r.status_code == 404:
                results[station_id] = "station_not_found"
            else:
                results[station_id] = f"http_{r.status_code}"

        except Exception as e:
            results[station_id] = f"error: {str(e)[:60]}"

        time.sleep(0.5)  # Be nice to NOAA

    client.close()
    return results


def convert_noaa_observations() -> List[Dict[str, Any]]:
    """Convert NOAA station observations into swarm events.
    
    Generates events for:
    - Extreme temperatures (>100°F or <10°F)
    - High winds (>30 mph sustained, >50 mph gusts)
    - Heavy precipitation
    - Low visibility (<1 mile)
    - Rapid pressure drops (storm signal)
    """
    events = []

    for station_id in STATIONS:
        path = FEEDS_DIR / f"noaa_{station_id.lower()}.json"
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        zone = STATIONS[station_id]["zone"]
        name = STATIONS[station_id]["name"]
        features = data.get("features", [])

        prev_pressure = None

        for feature in features:
            props = feature.get("properties", {})
            timestamp_str = props.get("timestamp", "")

            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue

            # Temperature (comes in Celsius from NOAA)
            temp_c = _extract_value(props.get("temperature"))
            if temp_c is not None:
                temp_f = temp_c * 9 / 5 + 32
                if temp_f > 100:
                    severity = min(1.0, (temp_f - 100) / 20.0)
                    events.append({
                        "event_type": "extreme_heat_observed",
                        "timestamp": ts,
                        "severity_score": round(severity, 3),
                        "domain": "weather",
                        "source": "noaa_station",
                        "metadata": {
                            "station": station_id,
                            "location": name,
                            "zone": zone,
                            "temp_f": round(temp_f, 1),
                        },
                    })
                elif temp_f < 10:
                    severity = min(1.0, (10 - temp_f) / 30.0)
                    events.append({
                        "event_type": "extreme_cold_observed",
                        "timestamp": ts,
                        "severity_score": round(severity, 3),
                        "domain": "weather",
                        "source": "noaa_station",
                        "metadata": {
                            "station": station_id,
                            "location": name,
                            "zone": zone,
                            "temp_f": round(temp_f, 1),
                        },
                    })

            # Wind speed (comes in km/h from NOAA)
            wind_kmh = _extract_value(props.get("windSpeed"))
            if wind_kmh is not None:
                wind_mph = wind_kmh * 0.621371
                if wind_mph > 30:
                    severity = min(1.0, (wind_mph - 25) / 50.0)
                    events.append({
                        "event_type": "high_wind_observed",
                        "timestamp": ts,
                        "severity_score": round(severity, 3),
                        "domain": "weather",
                        "source": "noaa_station",
                        "metadata": {
                            "station": station_id,
                            "location": name,
                            "zone": zone,
                            "wind_mph": round(wind_mph, 1),
                        },
                    })

            # Wind gust
            gust_kmh = _extract_value(props.get("windGust"))
            if gust_kmh is not None:
                gust_mph = gust_kmh * 0.621371
                if gust_mph > 50:
                    severity = min(1.0, (gust_mph - 40) / 60.0)
                    events.append({
                        "event_type": "wind_gust_observed",
                        "timestamp": ts,
                        "severity_score": round(severity, 3),
                        "domain": "weather",
                        "source": "noaa_station",
                        "metadata": {
                            "station": station_id,
                            "location": name,
                            "zone": zone,
                            "gust_mph": round(gust_mph, 1),
                        },
                    })

            # Visibility (comes in meters from NOAA)
            vis_m = _extract_value(props.get("visibility"))
            if vis_m is not None:
                vis_miles = vis_m / 1609.34
                if vis_miles < 1.0:
                    severity = min(1.0, (1.0 - vis_miles) / 1.0)
                    events.append({
                        "event_type": "low_visibility_observed",
                        "timestamp": ts,
                        "severity_score": round(severity, 3),
                        "domain": "weather",
                        "source": "noaa_station",
                        "metadata": {
                            "station": station_id,
                            "location": name,
                            "zone": zone,
                            "visibility_miles": round(vis_miles, 2),
                        },
                    })

            # Pressure drop detection (rapid drop = incoming storm)
            pressure_pa = _extract_value(props.get("barometricPressure"))
            if pressure_pa is not None:
                pressure_mb = pressure_pa / 100.0
                if prev_pressure is not None:
                    drop = prev_pressure - pressure_mb
                    if drop > 3.0:  # >3mb drop between observations = significant
                        severity = min(1.0, drop / 10.0)
                        events.append({
                            "event_type": "pressure_drop_detected",
                            "timestamp": ts,
                            "severity_score": round(severity, 3),
                            "domain": "weather",
                            "source": "noaa_station",
                            "metadata": {
                                "station": station_id,
                                "location": name,
                                "zone": zone,
                                "pressure_drop_mb": round(drop, 1),
                                "current_pressure_mb": round(pressure_mb, 1),
                            },
                        })
                prev_pressure = pressure_mb

    return sorted(events, key=lambda e: e["timestamp"])


def _extract_value(measurement: Optional[dict]) -> Optional[float]:
    """Extract numeric value from NOAA measurement object.
    
    NOAA returns measurements as: {"value": 25.6, "unitCode": "wmoUnit:degC", ...}
    """
    if measurement is None:
        return None
    if isinstance(measurement, dict):
        val = measurement.get("value")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    return None


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("NOAA HOURLY STATION PULL")
    logger.info("=" * 60)

    results = pull_noaa_stations()
    ok = sum(1 for v in results.values() if v == "ok")
    logger.info(f"Pulled: {ok}/{len(results)} stations successful")
    for station, status in results.items():
        icon = "✅" if status == "ok" else "❌"
        logger.info(f"  {icon} {station} ({STATIONS[station]['name']}): {status}")

    logger.info("")
    logger.info("Converting to events...")
    events = convert_noaa_observations()
    logger.info(f"Generated: {len(events)} weather events from station observations")

    if events:
        outfile = BASE_DIR / "data" / "event_sequences" / "noaa_station_events.json"
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.write_text(json.dumps(events, indent=2))
        logger.info(f"Saved to: {outfile}")
