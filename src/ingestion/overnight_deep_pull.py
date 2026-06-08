"""Overnight Deep Pull — Maximum data extraction while you sleep.

Pulls EVERYTHING available from all connected APIs at full depth.
Run this before bed, wake up to a fat dataset.

Usage:
    /Users/webber/Desktop/dvce/.venv/bin/python -m src.ingestion.overnight_deep_pull
"""

import httpx
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT = BASE_DIR / "data" / "overnight_pull" / datetime.now().strftime("%Y-%m-%d")
OUTPUT.mkdir(parents=True, exist_ok=True)

KEYS = json.loads((BASE_DIR / ".keys.json").read_text()) if (BASE_DIR / ".keys.json").exists() else {}
FINNHUB = KEYS.get("finnhub", "")
HEADERS = {"User-Agent": "DVCE-Swarm/1.0 (overnight-deep-pull)"}


def pull_section(name: str, calls: list, delay: float = 1.5):
    """Pull a section of APIs with rate limiting."""
    logger.info(f"\n{'='*60}")
    logger.info(f"  {name}")
    logger.info(f"{'='*60}")
    
    section_dir = OUTPUT / name.lower().replace(" ", "_").replace("&", "and")
    section_dir.mkdir(exist_ok=True)
    
    success = 0
    client = httpx.Client(timeout=25, headers=HEADERS, follow_redirects=True)
    
    for item in calls:
        fname = item[0]
        url = item[1]
        method = item[2] if len(item) > 2 else "GET"
        body = item[3] if len(item) > 3 else None
        
        try:
            if method == "POST":
                r = client.post(url, json=body)
            else:
                r = client.get(url)
            
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    data = r.json()
                    (section_dir / f"{fname}.json").write_text(json.dumps(data, indent=2)[:1000000])
                else:
                    (section_dir / f"{fname}.txt").write_text(r.text[:500000])
                success += 1
                logger.info(f"    ✅ {fname}")
            else:
                logger.warning(f"    ❌ {fname}: HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"    ❌ {fname}: {str(e)[:40]}")
        
        time.sleep(delay)
    
    client.close()
    logger.info(f"  → {success}/{len(calls)} successful")
    return success


def main():
    start = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    logger.info("🌙 OVERNIGHT DEEP PULL STARTING")
    logger.info(f"   Output: {OUTPUT}")
    logger.info(f"   Finnhub key: {'✅' if FINNHUB else '❌'}")
    
    total = 0
    
    # === FINANCIAL (Deep) ===
    total += pull_section("Financial", [
        # Finnhub - all major stocks
        *[(f"quote_{sym}", f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB}") 
          for sym in ["AAPL","MSFT","GOOGL","AMZN","NVDA","TSLA","META","JPM","V","WMT",
                     "JNJ","PG","HD","BAC","XOM","CVX","PFE","KO","DIS","NFLX",
                     "SPY","QQQ","DIA","IWM","VTI","GLD","TLT","HYG","XLF","XLE"]],
        # Market news - all categories
        (f"news_general", f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB}"),
        (f"news_forex", f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB}"),
        (f"news_crypto", f"https://finnhub.io/api/v1/news?category=crypto&token={FINNHUB}"),
        (f"news_merger", f"https://finnhub.io/api/v1/news?category=merger&token={FINNHUB}"),
        # Calendars
        (f"economic_calendar", f"https://finnhub.io/api/v1/calendar/economic?token={FINNHUB}"),
        (f"earnings_calendar", f"https://finnhub.io/api/v1/calendar/earnings?from={week_ago}&to={today}&token={FINNHUB}"),
        (f"ipo_calendar", f"https://finnhub.io/api/v1/calendar/ipo?from={month_ago}&to={today}&token={FINNHUB}"),
        # Company news for major players
        *[(f"company_news_{sym}", f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={week_ago}&to={today}&token={FINNHUB}")
          for sym in ["AAPL","MSFT","GOOGL","TSLA","NVDA","JPM","BAC","XOM"]],
        # Treasury
        ("treasury_debt", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?sort=-record_date&page[size]=90"),
        ("treasury_rates", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=90"),
        ("treasury_exchange", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/rates_of_exchange?sort=-record_date&page[size]=50"),
        # Crypto
        ("coingecko_top50", "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"),
        ("coinpaprika_btc", "https://api.coinpaprika.com/v1/tickers/btc-bitcoin"),
        ("coinpaprika_eth", "https://api.coinpaprika.com/v1/tickers/eth-ethereum"),
        ("frankfurter_rates", "https://api.frankfurter.dev/v1/latest?from=USD"),
        ("frankfurter_historical", f"https://api.frankfurter.dev/v1/{month_ago}..{today}?from=USD&to=EUR,GBP,JPY,CNY"),
    ])
    
    # === WEATHER & CLIMATE (Deep) ===
    cities = [
        ("nashville", 36.16, -86.78), ("atlanta", 33.749, -84.388),
        ("kansas_city", 39.099, -94.578), ("memphis", 35.15, -90.05),
        ("knoxville", 35.96, -83.92), ("chattanooga", 35.04, -85.31),
        ("boston", 42.36, -71.06), ("cleveland", 41.50, -81.69),
        ("philadelphia", 39.95, -75.17), ("phoenix", 33.45, -112.07),
        ("seattle", 47.61, -122.33), ("dallas", 32.78, -96.80),
    ]
    
    weather_calls = []
    for city, lat, lon in cities:
        weather_calls.append((f"forecast_{city}", f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,windspeed_10m,weathercode&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto&forecast_days=7"))
        weather_calls.append((f"air_quality_{city}", f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&hourly=pm2_5,pm10,us_aqi&timezone=auto"))
    
    weather_calls.extend([
        ("nws_alerts_us_severe", "https://api.weather.gov/alerts/active?status=actual&severity=Severe,Extreme"),
        ("nws_alerts_tn", "https://api.weather.gov/alerts/active?area=TN"),
        ("nws_alerts_mo", "https://api.weather.gov/alerts/active?area=MO"),
        ("nws_alerts_ga", "https://api.weather.gov/alerts/active?area=GA"),
        ("nws_alerts_ma", "https://api.weather.gov/alerts/active?area=MA"),
        ("nws_alerts_oh", "https://api.weather.gov/alerts/active?area=OH"),
        ("nws_alerts_tx", "https://api.weather.gov/alerts/active?area=TX"),
        ("nws_alerts_fl", "https://api.weather.gov/alerts/active?area=FL"),
        ("nws_alerts_nc", "https://api.weather.gov/alerts/active?area=NC"),
        ("nws_alerts_pa", "https://api.weather.gov/alerts/active?area=PA"),
        # Flood data for title-relevant areas
        *[(f"flood_{city}", f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}&daily=river_discharge")
          for city, lat, lon in cities],
    ])
    
    total += pull_section("Weather and Climate", weather_calls)
    
    # === GEO & DISASTERS ===
    total += pull_section("Geo and Disasters", [
        ("usgs_earthquakes_day", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"),
        ("usgs_earthquakes_week", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"),
        ("usgs_earthquakes_month", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"),
        ("usgs_significant_month", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"),
        ("fema_disasters_2024", "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$filter=declarationDate%20gt%20%272024-01-01T00:00:00.000z%27&$top=100&$orderby=declarationDate%20desc"),
        ("fema_disasters_2023", "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$filter=declarationDate%20gt%20%272023-01-01T00:00:00.000z%27%20and%20declarationDate%20lt%20%272024-01-01T00:00:00.000z%27&$top=100"),
        ("usaspending_awards", "https://api.usaspending.gov/api/v2/search/spending_by_award_count/", "POST", {"filters": {"time_period": [{"start_date": "2026-01-01", "end_date": today}], "award_type_codes": ["A","B","C","D"]}}),
    ])
    
    # === GRID & ENERGY ===
    total += pull_section("Grid and Energy", [
        ("uk_carbon_national", "https://api.carbonintensity.org.uk/intensity"),
        ("uk_carbon_regional", "https://api.carbonintensity.org.uk/regional"),
        ("uk_carbon_48h", "https://api.carbonintensity.org.uk/intensity/date"),
        ("nasa_donki_flares", f"https://api.nasa.gov/DONKI/FLR?startDate={month_ago}&endDate={today}&api_key=DEMO_KEY"),
        ("nasa_donki_cme", f"https://api.nasa.gov/DONKI/CME?startDate={month_ago}&endDate={today}&api_key=DEMO_KEY"),
        ("nasa_donki_gst", f"https://api.nasa.gov/DONKI/GST?startDate={month_ago}&endDate={today}&api_key=DEMO_KEY"),
        ("nasa_donki_ips", f"https://api.nasa.gov/DONKI/IPS?startDate={month_ago}&endDate={today}&api_key=DEMO_KEY"),
    ])
    
    # === CYBER & SECURITY ===
    total += pull_section("Cyber and Security", [
        ("nvd_cve_recent_50", "https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=50"),
        ("hackernews_top", "https://hacker-news.firebaseio.com/v0/topstories.json"),
        ("hackernews_new", "https://hacker-news.firebaseio.com/v0/newstories.json"),
        ("hackernews_best", "https://hacker-news.firebaseio.com/v0/beststories.json"),
    ])
    
    # === LOGISTICS ===
    total += pull_section("Logistics", [
        ("opensky_tn", "https://opensky-network.org/api/states/all?lamin=35&lamax=37&lomin=-87&lomax=-85"),
        ("opensky_ga", "https://opensky-network.org/api/states/all?lamin=33&lamax=35&lomin=-85&lomax=-83"),
        ("opensky_northeast", "https://opensky-network.org/api/states/all?lamin=39&lamax=42&lomin=-76&lomax=-73"),
    ])
    
    # === REFERENCE & GEOCODING ===
    zips = ["37201","37211","37215","38103","38118","64050","64111","30301","30318",
            "02101","02134","44101","44114","75201","75230","85001","98101","19101","28202"]
    
    total += pull_section("Reference and Geocoding", [
        *[(f"zip_{z}", f"http://api.zippopotam.us/us/{z}") for z in zips],
        ("rest_countries", "https://restcountries.com/v3.1/all?fields=name,capital,region,population,latlng,currencies,area"),
        ("ipwhois_self", "https://ipwhois.app/json/"),
    ])
    
    # === NASA SPACE ===
    total += pull_section("NASA Space", [
        ("apod", f"https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"),
        ("neo_today", f"https://api.nasa.gov/neo/rest/v1/feed/today?api_key=DEMO_KEY"),
        ("neo_week", f"https://api.nasa.gov/neo/rest/v1/feed?start_date={week_ago}&end_date={today}&api_key=DEMO_KEY"),
    ])
    
    elapsed = time.time() - start
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"🌙 OVERNIGHT PULL COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  APIs successful: {total}")
    logger.info(f"  Time elapsed: {elapsed/60:.1f} minutes")
    logger.info(f"  Output: {OUTPUT}")
    
    # Count total data
    total_files = list(OUTPUT.rglob("*.json")) + list(OUTPUT.rglob("*.txt"))
    total_kb = sum(f.stat().st_size for f in total_files) / 1024
    logger.info(f"  Files: {len(total_files)}")
    logger.info(f"  Data: {total_kb:.0f} KB ({total_kb/1024:.1f} MB)")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
