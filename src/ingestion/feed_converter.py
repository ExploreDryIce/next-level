"""Feed Converter — Transforms raw API data into swarm-compatible event sequences.

Takes the JSON files from data/live_feeds/ and converts them into
the event format the swarm pattern broker understands:
    {
        "event_type": "earthquake_M5.2_pacific",
        "timestamp": 1717800000.0,
        "severity_score": 0.72,
        "domain": "geo",
        "source": "usgs"
    }

Each converter maps a specific API's data structure into our universal event grammar.
The swarm broker then distributes these events to the appropriate domain specialist.

Usage:
    python -m src.ingestion.feed_converter

    Or import specific converters:
        from src.ingestion.feed_converter import convert_earthquakes
        events = convert_earthquakes()
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "live_feeds"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "event_sequences"


def convert_earthquakes() -> List[Dict[str, Any]]:
    """USGS earthquake data → geo domain events."""
    path = DATA_DIR / "usgs_earthquakes.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    for feature in data.get("features", []):
        props = feature["properties"]
        mag = props.get("mag", 0)
        place = props.get("place", "unknown")
        ts = props.get("time", 0) / 1000  # ms → seconds

        # Severity: M2.5=0.1, M5=0.5, M7+=0.9
        severity = min(1.0, max(0.0, (mag - 2.0) / 6.0))

        events.append({
            "event_type": f"earthquake_M{mag:.1f}",
            "timestamp": ts,
            "severity_score": round(severity, 3),
            "domain": "geo",
            "source": "usgs",
            "metadata": {"place": place, "magnitude": mag},
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_weather_forecast() -> List[Dict[str, Any]]:
    """Open-Meteo forecast → weather domain events."""
    path = DATA_DIR / "open_meteo_nashville.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip = hourly.get("precipitation", [])
    wind = hourly.get("windspeed_10m", [])

    events = []
    for i, time_str in enumerate(times):
        ts = datetime.fromisoformat(time_str).timestamp()
        temp = temps[i] if i < len(temps) else None
        rain = precip[i] if i < len(precip) else 0
        wspd = wind[i] if i < len(wind) else 0

        # Generate events for significant weather
        if rain and rain > 5:  # >5mm/hr = heavy rain
            severity = min(1.0, rain / 25.0)
            events.append({
                "event_type": "heavy_precipitation",
                "timestamp": ts,
                "severity_score": round(severity, 3),
                "domain": "weather",
                "source": "open_meteo",
                "metadata": {"precipitation_mm": rain, "location": "Nashville"},
            })

        if wspd and wspd > 40:  # >40 km/h = high wind
            severity = min(1.0, (wspd - 30) / 70.0)
            events.append({
                "event_type": "high_wind",
                "timestamp": ts,
                "severity_score": round(severity, 3),
                "domain": "weather",
                "source": "open_meteo",
                "metadata": {"windspeed_kmh": wspd, "location": "Nashville"},
            })

        if temp and temp > 38:  # >38°C = extreme heat
            events.append({
                "event_type": "extreme_heat",
                "timestamp": ts,
                "severity_score": round(min(1.0, (temp - 35) / 10.0), 3),
                "domain": "weather",
                "source": "open_meteo",
            })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_nws_alerts() -> List[Dict[str, Any]]:
    """NWS weather alerts → weather domain events."""
    path = DATA_DIR / "nws_alerts_tn.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    severity_map = {
        "Extreme": 1.0, "Severe": 0.8, "Moderate": 0.5, "Minor": 0.3, "Unknown": 0.4
    }

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        event_type = props.get("event", "unknown_alert")
        severity_text = props.get("severity", "Unknown")
        sent = props.get("sent", "")

        try:
            ts = datetime.fromisoformat(sent.replace("Z", "+00:00")).timestamp()
        except:
            ts = 0

        events.append({
            "event_type": f"nws_alert_{event_type.lower().replace(' ', '_')}",
            "timestamp": ts,
            "severity_score": severity_map.get(severity_text, 0.4),
            "domain": "weather",
            "source": "nws",
            "metadata": {
                "headline": props.get("headline", ""),
                "areas": props.get("areaDesc", ""),
            },
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_treasury() -> List[Dict[str, Any]]:
    """Fed Treasury data → financial domain events."""
    events = []

    # Interest rates
    path = DATA_DIR / "fed_treasury_rates.json"
    if path.exists():
        data = json.loads(path.read_text())
        for record in data.get("data", []):
            try:
                ts = datetime.strptime(record["record_date"], "%Y-%m-%d").timestamp()
                rate = float(record.get("avg_interest_rate_amt", 0))
                events.append({
                    "event_type": "treasury_rate_change",
                    "timestamp": ts,
                    "severity_score": round(min(1.0, rate / 10.0), 3),
                    "domain": "financial",
                    "source": "fed_treasury",
                    "metadata": {"rate": rate, "security": record.get("security_desc", "")},
                })
            except:
                continue

    # National debt
    path = DATA_DIR / "fed_treasury_debt.json"
    if path.exists():
        data = json.loads(path.read_text())
        for record in data.get("data", []):
            try:
                ts = datetime.strptime(record["record_date"], "%Y-%m-%d").timestamp()
                debt = float(record.get("tot_pub_debt_out_amt", 0))
                events.append({
                    "event_type": "national_debt_update",
                    "timestamp": ts,
                    "severity_score": 0.3,
                    "domain": "financial",
                    "source": "fed_treasury",
                    "metadata": {"total_debt": debt},
                })
            except:
                continue

    return sorted(events, key=lambda e: e["timestamp"])


def convert_crypto() -> List[Dict[str, Any]]:
    """CoinGecko market data → financial domain events."""
    path = DATA_DIR / "coingecko_top10.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    for coin in data:
        price_change = coin.get("price_change_percentage_24h", 0) or 0

        # Only generate events for significant moves (>5% in 24h)
        if abs(price_change) > 5:
            direction = "surge" if price_change > 0 else "crash"
            severity = min(1.0, abs(price_change) / 20.0)
            events.append({
                "event_type": f"crypto_{direction}_{coin['symbol']}",
                "timestamp": datetime.now().timestamp(),
                "severity_score": round(severity, 3),
                "domain": "financial",
                "source": "coingecko",
                "metadata": {
                    "coin": coin["name"],
                    "price": coin["current_price"],
                    "change_24h_pct": price_change,
                    "market_cap": coin.get("market_cap"),
                },
            })

    return events


def convert_solar_flares() -> List[Dict[str, Any]]:
    """NASA DONKI solar flare data → grid domain events."""
    path = DATA_DIR / "nasa_donki_flares.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    class_severity = {"X": 1.0, "M": 0.7, "C": 0.4, "B": 0.2, "A": 0.1}

    for flare in data:
        class_type = flare.get("classType", "C1.0")
        begin_time = flare.get("beginTime", "")

        try:
            ts = datetime.fromisoformat(begin_time.replace("Z", "+00:00")).timestamp()
        except:
            ts = 0

        # Get severity from class letter
        severity = class_severity.get(class_type[0], 0.3) if class_type else 0.3

        events.append({
            "event_type": f"solar_flare_{class_type}",
            "timestamp": ts,
            "severity_score": severity,
            "domain": "grid",
            "source": "nasa_donki",
            "metadata": {"class": class_type, "source_location": flare.get("sourceLocation", "")},
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_nvd_vulnerabilities() -> List[Dict[str, Any]]:
    """NVD CVE data → cyber domain events."""
    path = DATA_DIR / "nvd_cve_recent.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    for vuln in data.get("vulnerabilities", []):
        cve = vuln.get("cve", {})
        cve_id = cve.get("id", "unknown")
        published = cve.get("published", "")

        try:
            ts = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
        except:
            ts = datetime.now().timestamp()

        # Get CVSS score for severity
        metrics = cve.get("metrics", {})
        cvss_score = 5.0  # default
        for version in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            if version in metrics:
                cvss_data = metrics[version]
                if cvss_data:
                    cvss_score = cvss_data[0].get("cvssData", {}).get("baseScore", 5.0)
                    break

        severity = cvss_score / 10.0

        events.append({
            "event_type": f"cve_published_{cve_id}",
            "timestamp": ts,
            "severity_score": round(severity, 3),
            "domain": "cyber",
            "source": "nvd",
            "metadata": {"cve_id": cve_id, "cvss": cvss_score},
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_carbon_intensity() -> List[Dict[str, Any]]:
    """UK Carbon Intensity → grid domain events."""
    path = DATA_DIR / "uk_carbon_intensity.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    for item in data.get("data", []):
        intensity = item.get("intensity", {})
        actual = intensity.get("actual")
        forecast = intensity.get("forecast")
        ts_str = item.get("from", "")

        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except:
            ts = datetime.now().timestamp()

        if actual:
            # Severity based on carbon intensity (higher = worse)
            severity = min(1.0, actual / 400.0)
            events.append({
                "event_type": "grid_carbon_intensity",
                "timestamp": ts,
                "severity_score": round(severity, 3),
                "domain": "grid",
                "source": "uk_carbon_intensity",
                "metadata": {"actual_gCO2": actual, "forecast_gCO2": forecast},
            })

    return events


def convert_fema_disasters() -> List[Dict[str, Any]]:
    """FEMA disaster declarations → geo + title domain events."""
    path = DATA_DIR / "fema_disasters.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    events = []

    type_severity = {
        "DR": 0.8,  # Major disaster
        "EM": 0.6,  # Emergency
        "FM": 0.5,  # Fire management
        "FS": 0.4,  # Fire suppression
    }

    for record in data.get("DisasterDeclarationsSummaries", []):
        dec_date = record.get("declarationDate", "")
        dec_type = record.get("declarationType", "DR")
        state = record.get("state", "")
        title = record.get("declarationTitle", "")

        try:
            ts = datetime.fromisoformat(dec_date.replace("Z", "+00:00")).timestamp()
        except:
            continue

        events.append({
            "event_type": f"fema_disaster_{dec_type.lower()}",
            "timestamp": ts,
            "severity_score": type_severity.get(dec_type, 0.5),
            "domain": "geo",
            "source": "fema",
            "metadata": {"state": state, "title": title, "type": dec_type},
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_finnhub_news() -> List[Dict[str, Any]]:
    """Finnhub market news → financial domain events."""
    events = []

    for filename in ["finnhub_market_news.json", "finnhub_crypto_news.json"]:
        path = DATA_DIR / filename
        if not path.exists():
            continue

        data = json.loads(path.read_text())
        if not isinstance(data, list):
            continue

        for article in data[:50]:  # Cap at 50 per source
            ts = article.get("datetime", 0)
            headline = article.get("headline", "")
            category = article.get("category", "general")
            source = article.get("source", "unknown")

            # Classify severity by keywords
            severity = 0.3
            high_impact = ["crash", "surge", "plunge", "soar", "collapse", "rally",
                          "fed", "rate", "inflation", "recession", "crisis", "default"]
            if any(word in headline.lower() for word in high_impact):
                severity = 0.7

            events.append({
                "event_type": f"market_news_{category}",
                "timestamp": float(ts),
                "severity_score": severity,
                "domain": "financial",
                "source": f"finnhub_{source}",
                "metadata": {"headline": headline[:100], "category": category},
            })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_finnhub_economic_calendar() -> List[Dict[str, Any]]:
    """Finnhub economic calendar → financial domain events."""
    path = DATA_DIR / "finnhub_economic_calendar.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    calendar = data.get("economicCalendar", [])
    events = []

    high_impact_events = ["CPI", "GDP", "NFP", "Unemployment", "FOMC", "Fed",
                          "Interest Rate", "Retail Sales", "PMI", "Housing"]

    for item in calendar[:100]:
        event_name = item.get("event", "")
        country = item.get("country", "")
        time_str = item.get("time", "")
        impact = item.get("impact", "low")

        try:
            ts = datetime.fromisoformat(time_str.replace("Z", "+00:00")).timestamp()
        except:
            ts = datetime.now().timestamp()

        # Severity from impact
        severity_map = {"high": 0.8, "medium": 0.5, "low": 0.2}
        severity = severity_map.get(impact, 0.3)

        # Boost if it's a well-known indicator
        if any(term in event_name for term in high_impact_events):
            severity = min(1.0, severity + 0.2)

        events.append({
            "event_type": f"economic_event_{country.lower()}",
            "timestamp": ts,
            "severity_score": round(severity, 3),
            "domain": "financial",
            "source": "finnhub_calendar",
            "metadata": {"event": event_name, "country": country, "impact": impact},
        })

    return sorted(events, key=lambda e: e["timestamp"])


def convert_all() -> Dict[str, List[Dict[str, Any]]]:
    """Run all converters and return events by domain."""
    all_events = {
        "geo": [],
        "weather": [],
        "financial": [],
        "cyber": [],
        "grid": [],
    }

    converters = [
        ("geo", convert_earthquakes),
        ("weather", convert_weather_forecast),
        ("weather", convert_nws_alerts),
        ("financial", convert_treasury),
        ("financial", convert_crypto),
        ("financial", convert_finnhub_news),
        ("financial", convert_finnhub_economic_calendar),
        ("grid", convert_solar_flares),
        ("cyber", convert_nvd_vulnerabilities),
        ("grid", convert_carbon_intensity),
        ("geo", convert_fema_disasters),
    ]

    for domain, converter in converters:
        events = converter()
        all_events[domain].extend(events)
        print(f"  {converter.__name__}: {len(events)} events → {domain}")

    return all_events


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== CONVERTING API DATA → SWARM EVENT SEQUENCES ===")
    print()

    all_events = convert_all()

    print()
    print("=" * 60)
    total = 0
    for domain, events in all_events.items():
        count = len(events)
        total += count
        if events:
            # Save per-domain
            outfile = OUTPUT_DIR / f"{domain}_events.json"
            outfile.write_text(json.dumps(events, indent=2))
            print(f"  {domain:12}: {count:4} events → {outfile.name}")

    # Save combined
    combined = []
    for events in all_events.values():
        combined.extend(events)
    combined.sort(key=lambda e: e["timestamp"])

    (OUTPUT_DIR / "all_events_combined.json").write_text(json.dumps(combined, indent=2))
    print(f"\n  TOTAL: {total} events ready for swarm ingestion")
    print(f"  Saved to: {OUTPUT_DIR}")
    print()
    print("These events can now be fed to the swarm broker via:")
    print("  python src/swarm/broker.py --inject data/event_sequences/all_events_combined.json")
