"""RapidAPI Integrations — Utility Rates, GeoDB Cities, Company Name Match.

Pulls supplemental data from RapidAPI services to enrich the swarm's
understanding of infrastructure, geography, and corporate entities.

APIs used:
    - GeoDB Cities (wft-geo-db.p.rapidapi.com) — city/region data, populations
    - Company Name Match (TODO — when we find a good free one)
    - NREL Utility Rates (developer.nrel.gov) — free, no RapidAPI needed
    - Emission Factors (emission-factors.com) — grid carbon + rates by ZIP

Free tier limits (GeoDB):
    - 1000 requests/day on Basic plan
    - Must subscribe at: https://rapidapi.com/wirefreethought/api/geodb-cities/pricing

Usage:
    python -m src.ingestion.rapidapi_feeds

    # Or import specific pulls:
    from src.ingestion.rapidapi_feeds import pull_geodb_cities, pull_utility_rates
"""

import httpx
import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
KEYS_FILE = BASE_DIR / ".keys.json"
FEEDS_DIR = BASE_DIR / "data" / "live_feeds"

# Infrastructure ZIP codes to query for utility rates
# These match our 117 infrastructure nodes' approximate locations
INFRASTRUCTURE_ZIPS = {
    "37203": "Nashville TN (grid hub)",
    "64108": "Kansas City MO (logistics)",
    "30303": "Atlanta GA (logistics hub)",
    "77002": "Houston TX (energy corridor)",
    "90001": "Los Angeles CA (port)",
    "10001": "New York NY (financial)",
    "60601": "Chicago IL (logistics)",
    "98101": "Seattle WA (tech/port)",
    "33101": "Miami FL (shipping)",
    "75201": "Dallas TX (grid/energy)",
    "85001": "Phoenix AZ (solar/grid)",
    "15201": "Pittsburgh PA (manufacturing)",
    "48201": "Detroit MI (auto manufacturing)",
    "94102": "San Francisco CA (tech)",
    "70112": "New Orleans LA (port/energy)",
}


def load_rapidapi_key() -> str:
    """Load RapidAPI key from .keys.json."""
    if KEYS_FILE.exists():
        keys = json.loads(KEYS_FILE.read_text())
        return keys.get("rapidapi", "")
    return ""


def pull_geodb_cities() -> Dict[str, Any]:
    """Pull city data from GeoDB Cities API.
    
    Gets major cities near infrastructure nodes + population/elevation data.
    Useful for: population density near infrastructure, urbanization signals.
    
    Subscribe free at: https://rapidapi.com/wirefreethought/api/geodb-cities/pricing
    """
    api_key = load_rapidapi_key()
    if not api_key:
        return {"error": "No RapidAPI key"}

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "wft-geo-db.p.rapidapi.com",
    }

    results = {}
    client = httpx.Client(timeout=15, headers=headers)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    # Get major cities in key infrastructure regions
    queries = [
        ("us_major_cities", "/v1/geo/cities?countryIds=US&minPopulation=500000&limit=10&sort=-population"),
        ("china_major_cities", "/v1/geo/cities?countryIds=CN&minPopulation=5000000&limit=10&sort=-population"),
        ("europe_major_cities", "/v1/geo/cities?countryIds=DE,FR,GB,NL&minPopulation=500000&limit=10&sort=-population"),
        ("middle_east_cities", "/v1/geo/cities?countryIds=SA,AE,QA,KW&minPopulation=200000&limit=10&sort=-population"),
        ("asia_pacific_cities", "/v1/geo/cities?countryIds=JP,KR,SG,TW&minPopulation=500000&limit=10&sort=-population"),
    ]

    for name, endpoint in queries:
        try:
            r = client.get(f"https://wft-geo-db.p.rapidapi.com{endpoint}")
            if r.status_code == 200:
                data = r.json()
                (FEEDS_DIR / f"geodb_{name}.json").write_text(json.dumps(data, indent=2))
                results[name] = f"ok ({len(data.get('data', []))} cities)"
            elif r.status_code == 403:
                results[name] = "not_subscribed (subscribe at rapidapi.com/wirefreethought/api/geodb-cities/pricing)"
                break  # No point trying more
            else:
                results[name] = f"http_{r.status_code}"
        except Exception as e:
            results[name] = f"error: {str(e)[:60]}"
        time.sleep(1.5)  # Respect rate limits

    client.close()
    return results


def pull_utility_rates() -> Dict[str, Any]:
    """Pull US utility rates from EIA (Energy Information Administration).
    
    EIA API v2: https://www.eia.gov/opendata/
    Uses DEMO_KEY (free, rate limited) — gets electricity prices by state.
    """
    results = {}
    client = httpx.Client(timeout=15)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    # States where we have infrastructure nodes
    states = ["TN", "MO", "GA", "TX", "CA", "NY", "IL", "WA", "FL", "AZ", "PA", "MI", "LA", "OH"]

    all_rates = []

    for state in states:
        try:
            r = client.get(
                "https://api.eia.gov/v2/electricity/retail-sales/data/",
                params={
                    "api_key": "DEMO_KEY",
                    "frequency": "monthly",
                    "data[0]": "price",
                    "facets[stateid][]": state,
                    "facets[sectorid][]": "RES",  # Residential
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 1,
                },
            )
            if r.status_code == 200:
                data = r.json()
                records = data.get("response", {}).get("data", [])
                if records:
                    entry = records[0]
                    all_rates.append({
                        "state": state,
                        "period": entry.get("period"),
                        "price_cents_kwh": float(entry.get("price", 0)),
                        "sector": "residential",
                    })
                    results[state] = "ok"
                else:
                    results[state] = "no_data"
            else:
                results[state] = f"http_{r.status_code}"
        except Exception as e:
            results[state] = f"error: {str(e)[:60]}"
        time.sleep(0.5)

    # Also get industrial rates
    for state in states[:8]:  # Limit to avoid rate limits
        try:
            r = client.get(
                "https://api.eia.gov/v2/electricity/retail-sales/data/",
                params={
                    "api_key": "DEMO_KEY",
                    "frequency": "monthly",
                    "data[0]": "price",
                    "facets[stateid][]": state,
                    "facets[sectorid][]": "IND",  # Industrial
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": 1,
                },
            )
            if r.status_code == 200:
                data = r.json()
                records = data.get("response", {}).get("data", [])
                if records:
                    entry = records[0]
                    all_rates.append({
                        "state": state,
                        "period": entry.get("period"),
                        "price_cents_kwh": float(entry.get("price", 0)),
                        "sector": "industrial",
                    })
        except:
            pass
        time.sleep(0.5)

    if all_rates:
        (FEEDS_DIR / "eia_utility_rates.json").write_text(json.dumps(all_rates, indent=2))

    client.close()
    return results


def pull_emission_factors() -> Dict[str, Any]:
    """Pull grid emission factors and energy mix from emission-factors.com.
    
    Free API — carbon intensity by ZIP code.
    """
    results = {}
    client = httpx.Client(timeout=15)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    all_data = []

    # Just sample a few key ZIPs
    sample_zips = list(INFRASTRUCTURE_ZIPS.keys())[:8]

    for zipcode in sample_zips:
        try:
            r = client.get(f"https://emission-factors.com/api/v1/zip/{zipcode}")
            if r.status_code == 200:
                data = r.json()
                data["_zipcode"] = zipcode
                data["_description"] = INFRASTRUCTURE_ZIPS[zipcode]
                all_data.append(data)
                results[zipcode] = "ok"
            elif r.status_code == 404:
                results[zipcode] = "not_found"
            else:
                results[zipcode] = f"http_{r.status_code}"
        except Exception as e:
            results[zipcode] = f"error: {str(e)[:60]}"
        time.sleep(1)

    if all_data:
        (FEEDS_DIR / "emission_factors.json").write_text(json.dumps(all_data, indent=2))

    client.close()
    return results


def convert_utility_events() -> List[Dict[str, Any]]:
    """Convert utility rate data into grid domain events.
    
    Generates events for:
    - High electricity rates (above national average) — cost pressure on infrastructure
    """
    events = []
    path = FEEDS_DIR / "eia_utility_rates.json"
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    import time as time_mod
    now = time_mod.time()

    # US average residential rate is ~16 cents/kWh (2026)
    US_AVG_RESIDENTIAL = 16.0
    US_AVG_INDUSTRIAL = 8.5

    for entry in data:
        rate = entry.get("price_cents_kwh", 0)
        sector = entry.get("sector", "residential")
        state = entry.get("state", "??")

        if sector == "residential" and rate > US_AVG_RESIDENTIAL * 1.2:
            # 20%+ above average
            severity = min(1.0, (rate - US_AVG_RESIDENTIAL) / 15.0)
            events.append({
                "event_type": "high_utility_rate_residential",
                "timestamp": now,
                "severity_score": round(severity, 3),
                "domain": "grid",
                "source": "eia_utility_rates",
                "metadata": {
                    "state": state,
                    "rate_cents_kwh": rate,
                    "above_avg_pct": round((rate / US_AVG_RESIDENTIAL - 1) * 100, 1),
                    "period": entry.get("period"),
                },
            })

        elif sector == "industrial" and rate > US_AVG_INDUSTRIAL * 1.3:
            severity = min(1.0, (rate - US_AVG_INDUSTRIAL) / 10.0)
            events.append({
                "event_type": "high_utility_rate_industrial",
                "timestamp": now,
                "severity_score": round(severity, 3),
                "domain": "grid",
                "source": "eia_utility_rates",
                "metadata": {
                    "state": state,
                    "rate_cents_kwh": rate,
                    "above_avg_pct": round((rate / US_AVG_INDUSTRIAL - 1) * 100, 1),
                    "period": entry.get("period"),
                },
            })

    return events


def convert_geodb_events() -> List[Dict[str, Any]]:
    """Convert GeoDB city data into geo domain events (population signals)."""
    events = []
    import time as time_mod
    now = time_mod.time()

    for filename in FEEDS_DIR.glob("geodb_*.json"):
        try:
            data = json.loads(filename.read_text())
            cities = data.get("data", [])
            for city in cities:
                pop = city.get("population", 0)
                if pop > 5_000_000:
                    events.append({
                        "event_type": "megacity_population_center",
                        "timestamp": now,
                        "severity_score": round(min(1.0, pop / 30_000_000), 3),
                        "domain": "geo",
                        "source": "geodb",
                        "metadata": {
                            "city": city.get("name"),
                            "country": city.get("country"),
                            "population": pop,
                            "latitude": city.get("latitude"),
                            "longitude": city.get("longitude"),
                        },
                    })
        except (json.JSONDecodeError, OSError):
            continue

    return events


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("RAPIDAPI + FREE API INTEGRATIONS")
    logger.info("=" * 60)

    # 1. NREL Utility Rates (free, no subscription needed)
    logger.info("")
    logger.info("1. NREL Utility Rates (free)...")
    rate_results = pull_utility_rates()
    ok = sum(1 for v in rate_results.values() if v == "ok")
    logger.info(f"   {ok}/{len(rate_results)} ZIP codes pulled")

    # 2. Emission Factors (free)
    logger.info("")
    logger.info("2. Emission Factors (free)...")
    emission_results = pull_emission_factors()
    ok2 = sum(1 for v in emission_results.values() if v == "ok")
    logger.info(f"   {ok2}/{len(emission_results)} ZIP codes pulled")

    # 3. GeoDB Cities (RapidAPI — requires free subscription)
    logger.info("")
    logger.info("3. GeoDB Cities (RapidAPI)...")
    geo_results = pull_geodb_cities()
    for name, status in geo_results.items():
        icon = "✅" if "ok" in str(status) else "❌"
        logger.info(f"   {icon} {name}: {status}")

    # 4. Convert to events
    logger.info("")
    logger.info("Converting to swarm events...")
    utility_events = convert_utility_events()
    geo_events = convert_geodb_events()
    logger.info(f"   Utility rate events: {len(utility_events)}")
    logger.info(f"   GeoDB events: {len(geo_events)}")

    # Save events
    all_events = utility_events + geo_events
    if all_events:
        outfile = BASE_DIR / "data" / "event_sequences" / "rapidapi_events.json"
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.write_text(json.dumps(all_events, indent=2))
        logger.info(f"   Saved: {outfile}")

    logger.info("")
    logger.info("=" * 60)
    logger.info("DONE")
    logger.info("")
    logger.info("If GeoDB failed with 'not_subscribed', go to:")
    logger.info("  https://rapidapi.com/wirefreethought/api/geodb-cities/pricing")
    logger.info("  Click 'Subscribe' on the Basic (free) plan.")
    logger.info("=" * 60)
