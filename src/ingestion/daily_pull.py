"""Daily Feed Pull — Automated data ingestion from all free APIs.

Run this daily via cron/launchd to keep the swarm fed with fresh data.
Pulls from all no-auth APIs, converts to events, and feeds the broker.

Usage:
    python -m src.ingestion.daily_pull

Cron (daily at 6am):
    0 6 * * * cd /Users/webber/Desktop/next-level && /Users/webber/Desktop/dvce/.venv/bin/python -m src.ingestion.daily_pull

LaunchD: see services/com.dvce.swarm-feed.plist
"""

import httpx
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
FEEDS_DIR = BASE_DIR / "data" / "live_feeds"
EVENTS_DIR = BASE_DIR / "data" / "event_sequences"
HISTORY_DIR = BASE_DIR / "data" / "pull_history"

# API key file (create this after registering)
KEYS_FILE = BASE_DIR / ".keys.json"

HEADERS = {"User-Agent": "DVCE-Swarm/1.0 (automated-daily-pull)"}


def load_keys() -> dict:
    """Load API keys from .keys.json (gitignored)."""
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text())
    return {}


def pull_no_auth_feeds() -> dict:
    """Pull all APIs that need zero authentication."""
    results = {}
    today = datetime.now().strftime("%Y-%m-%d")

    feeds = [
        # Geo
        ("usgs_earthquakes", f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"),
        ("usgs_significant", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"),

        # Weather
        ("open_meteo_nashville", "https://api.open-meteo.com/v1/forecast?latitude=36.16&longitude=-86.78&hourly=temperature_2m,precipitation,windspeed_10m,weathercode&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max&timezone=America/Chicago&forecast_days=7"),
        ("open_meteo_air_quality", "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=36.16&longitude=-86.78&hourly=pm2_5,pm10,us_aqi&timezone=America/Chicago"),
        ("open_meteo_flood", "https://flood-api.open-meteo.com/v1/flood?latitude=36.16&longitude=-86.78&daily=river_discharge"),
        ("open_meteo_solar", "https://api.open-meteo.com/v1/forecast?latitude=36.16&longitude=-86.78&daily=sunshine_duration,uv_index_max,shortwave_radiation_sum&timezone=America/Chicago&forecast_days=7"),
        ("nws_alerts_tn", "https://api.weather.gov/alerts/active?area=TN"),
        ("nws_alerts_mo", "https://api.weather.gov/alerts/active?area=MO"),
        ("nws_alerts_ga", "https://api.weather.gov/alerts/active?area=GA"),

        # Financial
        ("fed_treasury_debt", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?sort=-record_date&page[size]=10"),
        ("fed_treasury_rates", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=30"),
        ("coingecko_top10", "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1"),
        ("frankfurter_rates", "https://api.frankfurter.app/latest?from=USD"),
        ("coinpaprika_btc", "https://api.coinpaprika.com/v1/tickers/btc-bitcoin"),

        # Grid
        ("uk_carbon_intensity", "https://api.carbonintensity.org.uk/intensity"),
        ("uk_carbon_regional", "https://api.carbonintensity.org.uk/regional"),

        # Cyber
        ("nvd_cve_recent", "https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=20"),
        ("hackernews_top", "https://hacker-news.firebaseio.com/v0/topstories.json"),

        # Logistics
        ("opensky_tn", "https://opensky-network.org/api/states/all?lamin=35&lamax=37&lomin=-87&lomax=-85"),

        # Government
        ("fema_disasters", f"https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$filter=declarationDate%20gt%20%272024-01-01T00:00:00.000z%27&$top=20&$orderby=declarationDate%20desc"),
        ("usaspending_recent", "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"),

        # Space
        ("spaceflight_news", "https://api.spaceflightnewsapi.net/v4/articles/?limit=10"),

        # Geocoding/reference
        ("ipwhois_self", "https://ipwhois.app/json/"),
    ]

    client = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)

    for name, url in feeds:
        try:
            if name == "usaspending_recent":
                # POST endpoint
                r = client.post(url, json={
                    "filters": {
                        "time_period": [{"start_date": "2026-01-01", "end_date": today}],
                        "award_type_codes": ["A", "B", "C", "D"]
                    }
                })
            else:
                r = client.get(url)

            if r.status_code == 200:
                data = r.json() if "json" in r.headers.get("content-type", "") else {"raw": r.text[:5000]}
                (FEEDS_DIR / f"{name}.json").write_text(json.dumps(data, indent=2)[:500000])
                results[name] = "ok"
            else:
                results[name] = f"http_{r.status_code}"
        except Exception as e:
            results[name] = f"error: {str(e)[:40]}"

        time.sleep(1)  # Rate limit between calls

    client.close()
    return results


def pull_keyed_feeds(keys: dict) -> dict:
    """Pull APIs that require a free API key."""
    results = {}

    if not keys:
        logger.info("No API keys found. Create .keys.json to enable keyed feeds.")
        return results

    client = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # NASA (if key available)
    nasa_key = keys.get("nasa", "DEMO_KEY")
    nasa_feeds = [
        ("nasa_apod", f"https://api.nasa.gov/planetary/apod?api_key={nasa_key}"),
        ("nasa_neo_today", f"https://api.nasa.gov/neo/rest/v1/feed/today?api_key={nasa_key}"),
        ("nasa_donki_flares", f"https://api.nasa.gov/DONKI/FLR?startDate={week_ago}&endDate={today}&api_key={nasa_key}"),
        ("nasa_donki_cme", f"https://api.nasa.gov/DONKI/CME?startDate={week_ago}&endDate={today}&api_key={nasa_key}"),
        ("nasa_donki_gst", f"https://api.nasa.gov/DONKI/GST?startDate={week_ago}&endDate={today}&api_key={nasa_key}"),
    ]

    for name, url in nasa_feeds:
        try:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                (FEEDS_DIR / f"{name}.json").write_text(json.dumps(data, indent=2)[:500000])
                results[name] = "ok"
            else:
                results[name] = f"http_{r.status_code}"
        except Exception as e:
            results[name] = f"error: {str(e)[:40]}"
        time.sleep(1)

    # FRED (if key available)
    fred_key = keys.get("fred")
    if fred_key:
        fred_series = ["FEDFUNDS", "UNRATE", "CPIAUCSL", "GDP", "DGS10", "T10Y2Y"]
        for series in fred_series:
            name = f"fred_{series.lower()}"
            try:
                r = client.get(
                    f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={fred_key}&file_type=json&sort_order=desc&limit=30"
                )
                if r.status_code == 200:
                    (FEEDS_DIR / f"{name}.json").write_text(r.text[:100000])
                    results[name] = "ok"
            except:
                pass
            time.sleep(1)

    # Finnhub (if key available)
    finnhub_key = keys.get("finnhub")
    if finnhub_key:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        finnhub_feeds = [
            ("finnhub_market_news", f"https://finnhub.io/api/v1/news?category=general&token={finnhub_key}"),
            ("finnhub_crypto_news", f"https://finnhub.io/api/v1/news?category=crypto&token={finnhub_key}"),
            ("finnhub_spy_quote", f"https://finnhub.io/api/v1/quote?symbol=SPY&token={finnhub_key}"),
            ("finnhub_aapl_quote", f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={finnhub_key}"),
            ("finnhub_economic_calendar", f"https://finnhub.io/api/v1/calendar/economic?token={finnhub_key}"),
            ("finnhub_earnings_calendar", f"https://finnhub.io/api/v1/calendar/earnings?from={week_ago}&to={today}&token={finnhub_key}"),
            ("finnhub_ipo_calendar", f"https://finnhub.io/api/v1/calendar/ipo?from={week_ago}&to={today}&token={finnhub_key}"),
            ("finnhub_market_status", f"https://finnhub.io/api/v1/stock/market-status?exchange=US&token={finnhub_key}"),
        ]
        for name, url in finnhub_feeds:
            try:
                r = client.get(url)
                if r.status_code == 200:
                    (FEEDS_DIR / f"{name}.json").write_text(json.dumps(r.json(), indent=2)[:200000])
                    results[name] = "ok"
                else:
                    results[name] = f"http_{r.status_code}"
            except Exception as e:
                results[name] = f"error: {str(e)[:40]}"
            time.sleep(1)

    # NewsAPI (if key available)
    newsapi_key = keys.get("newsapi")
    if newsapi_key:
        news_feeds = [
            ("newsapi_top_us", f"https://newsapi.org/v2/top-headlines?country=us&apiKey={newsapi_key}"),
            ("newsapi_business", f"https://newsapi.org/v2/top-headlines?category=business&country=us&apiKey={newsapi_key}"),
            ("newsapi_real_estate", f"https://newsapi.org/v2/everything?q=real+estate+market&sortBy=publishedAt&pageSize=20&apiKey={newsapi_key}"),
            ("newsapi_supply_chain", f"https://newsapi.org/v2/everything?q=supply+chain+disruption&sortBy=publishedAt&pageSize=20&apiKey={newsapi_key}"),
            ("newsapi_cybersecurity", f"https://newsapi.org/v2/everything?q=cybersecurity+breach&sortBy=publishedAt&pageSize=20&apiKey={newsapi_key}"),
        ]
        for name, url in news_feeds:
            try:
                r = client.get(url)
                if r.status_code == 200:
                    (FEEDS_DIR / f"{name}.json").write_text(json.dumps(r.json(), indent=2)[:200000])
                    results[name] = "ok"
                else:
                    results[name] = f"http_{r.status_code}"
            except Exception as e:
                results[name] = f"error: {str(e)[:40]}"
            time.sleep(1)

    # Alpha Vantage (if key available) — 5 calls/min limit, space them out
    av_key = keys.get("alpha_vantage")
    if av_key:
        av_feeds = [
            ("alpha_spy_daily", f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&outputsize=compact&apikey={av_key}"),
            ("alpha_real_gdp", f"https://www.alphavantage.co/query?function=REAL_GDP&interval=quarterly&apikey={av_key}"),
            ("alpha_cpi", f"https://www.alphavantage.co/query?function=CPI&interval=monthly&apikey={av_key}"),
            ("alpha_unemployment", f"https://www.alphavantage.co/query?function=UNEMPLOYMENT&apikey={av_key}"),
            ("alpha_news_sentiment", f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=SPY&apikey={av_key}"),
        ]
        for name, url in av_feeds:
            try:
                r = client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    if "Note" not in data and "Information" not in data:
                        (FEEDS_DIR / f"{name}.json").write_text(json.dumps(data, indent=2)[:300000])
                        results[name] = "ok"
                    else:
                        results[name] = "rate_limited"
                else:
                    results[name] = f"http_{r.status_code}"
            except Exception as e:
                results[name] = f"error: {str(e)[:40]}"
            time.sleep(15)  # 5 calls/min = 12sec spacing minimum

    # OpenWeatherMap (if key available)
    owm_key = keys.get("openweathermap")
    if owm_key:
        owm_cities = [
            ("nashville", 36.16, -86.78), ("memphis", 35.15, -90.05),
            ("atlanta", 33.749, -84.388), ("kansas_city", 39.099, -94.578),
            ("boston", 42.36, -71.06), ("cleveland", 41.50, -81.69),
            ("philadelphia", 39.95, -75.17), ("phoenix", 33.45, -112.07),
            ("dallas", 32.78, -96.80), ("seattle", 47.61, -122.33),
        ]
        for city, lat, lon in owm_cities:
            try:
                r = client.get(f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={owm_key}&units=imperial")
                if r.status_code == 200:
                    (FEEDS_DIR / f"owm_{city}.json").write_text(json.dumps(r.json(), indent=2))
                    results[f"owm_{city}"] = "ok"
                else:
                    results[f"owm_{city}"] = f"http_{r.status_code}"
            except Exception as e:
                results[f"owm_{city}"] = f"error: {str(e)[:40]}"
            time.sleep(1)

    client.close()
    return results


def run_conversion():
    """Run the feed converter to produce event sequences."""
    from src.ingestion.feed_converter import convert_all
    import sys

    all_events = convert_all()

    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for domain, events in all_events.items():
        if events:
            (EVENTS_DIR / f"{domain}_events.json").write_text(json.dumps(events, indent=2))
            total += len(events)

    # Combined
    combined = []
    for events in all_events.values():
        combined.extend(events)
    combined.sort(key=lambda e: e["timestamp"])
    (EVENTS_DIR / "all_events_combined.json").write_text(json.dumps(combined, indent=2))

    return total


def save_history(pull_results: dict, event_count: int):
    """Save pull history for tracking."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d_%H%M")
    history = {
        "timestamp": datetime.now().isoformat(),
        "feeds_attempted": len(pull_results),
        "feeds_successful": sum(1 for v in pull_results.values() if v == "ok"),
        "events_generated": event_count,
        "results": pull_results,
    }
    (HISTORY_DIR / f"pull_{today}.json").write_text(json.dumps(history, indent=2))
    return history


if __name__ == "__main__":
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("DAILY SWARM FEED PULL")
    logger.info("=" * 60)

    # Phase 1: No-auth feeds
    logger.info("Phase 1: Pulling no-auth feeds...")
    no_auth_results = pull_no_auth_feeds()
    ok_count = sum(1 for v in no_auth_results.values() if v == "ok")
    logger.info(f"  No-auth: {ok_count}/{len(no_auth_results)} successful")

    # Phase 2: Keyed feeds
    logger.info("Phase 2: Pulling keyed feeds...")
    keys = load_keys()
    keyed_results = pull_keyed_feeds(keys)
    ok_count2 = sum(1 for v in keyed_results.values() if v == "ok")
    logger.info(f"  Keyed: {ok_count2}/{len(keyed_results)} successful")

    # Phase 3: Convert to events
    logger.info("Phase 3: Converting to event sequences...")
    event_count = run_conversion()
    logger.info(f"  Generated: {event_count} events")

    # Save history
    all_results = {**no_auth_results, **keyed_results}
    history = save_history(all_results, event_count)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"COMPLETE: {history['feeds_successful']}/{history['feeds_attempted']} feeds → {event_count} events")
    logger.info("=" * 60)
