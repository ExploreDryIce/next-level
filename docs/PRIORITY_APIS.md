# Priority APIs — Webber's Picks

Specific APIs flagged for immediate integration or bookmarking.

---

## 🚀 NASA APIs
**URL:** https://api.nasa.gov/

Free API key (instant, no approval). Endpoints:

| Endpoint | What It Feeds | Swarm Value |
|----------|--------------|-------------|
| **DONKI** (Space Weather) | Solar flares, geomagnetic storms, CMEs | Grid specialist — solar events cause power grid disruptions |
| **NEO** (Near Earth Objects) | Asteroid close approaches | Geo specialist — impact risk modeling |
| **EONET** (Earth Observatory Natural Events) | Wildfires, storms, volcanic eruptions | Weather + Geo — real-time natural disaster feed |
| **EPIC** (Earth Imaging) | Daily color images of Earth | Visualization |
| **Mars Weather** | InSight weather data from Mars | Cool factor |
| **APOD** | Astronomy Picture of the Day | Content |
| **Exoplanet Archive** | Confirmed exoplanet data | Future |
| **TLE** | Two-Line Element satellite orbit data | Logistics — satellite tracking |
| **FIRMS** | Active fire/hotspot data (global) | Weather specialist — wildfire events → title insurance claims |

**Key:** Get one at https://api.nasa.gov/ — covers ALL endpoints.

---

## ⚡ Energy APIs (RapidAPI Hub)
**URL:** https://rapidapi.com/search/Energy

| API | What | Free Tier | Swarm Value |
|-----|------|-----------|-------------|
| **Utility Rate Database (Wattbuy)** | Electric rates for 1700+ US utilities, 600+ non-default rates | Free tier | Grid specialist — power cost by location for title/site selection |
| **CAISO Data** | California grid: emissions, demand, supply, prices (daily updates) | Free tier | Grid specialist — real-time power market |
| **Electricity Maps** | Real-time carbon intensity of electricity worldwide | Free (non-commercial) | Grid specialist — green energy signals |
| **emission-factors.com** | EPA eGRID + EIA-930 + NREL PVWatts unified by ZIP code | Free | Grid + Title — infrastructure scoring per property |

---

## 🌐 RapidAPI Hub (General)
**URL:** https://rapidapi.com/hub

Free APIs marketplace. Thousands available with free tiers. Key ones:

| API | Category | Free Tier |
|-----|----------|-----------|
| **Company Name Match** | Business intelligence — fuzzy match company names | Yes |
| **URL Intelligence** | Analyze URLs for category, language, safety | Yes |
| **Bloomberg Market News** (unofficial scrapers) | Financial news headlines | Some free |

---

## 📍 IPWHOIS.io
**URL:** https://ipwhois.io/

| Feature | Detail |
|---------|--------|
| Auth | **None required** |
| Rate | 60 requests/min (free, non-commercial) |
| Returns | Country, region, city, lat/lon, ISP, ASN, timezone, currency |
| Format | JSON, XML, CSV |
| Value | Cyber specialist (IP attribution), Geo specialist (location from IP) |

```
GET https://ipwhois.io/json/8.8.4.4
```

No key. No signup. Just hit it.

---

## 📮 Zippopotam.us
**URL:** http://www.zippopotam.us

| Feature | Detail |
|---------|--------|
| Auth | **None** |
| Returns | Country, state, city, lat/lon from any zip/postal code |
| Coverage | US, CA, UK, DE, FR, AU, and more |
| Value | Title node — zip code to geography for parcel mapping |

```
GET http://api.zippopotam.us/us/90210
```

Instant, free, no limits worth worrying about.

---

## 🏙️ GeoDB Cities
**URL:** http://geodb-cities-api.wirefreethought.com/

| Feature | Detail |
|---------|--------|
| Auth | Free tier (apiKey via RapidAPI) |
| Returns | Cities, regions, countries with population, coordinates, timezone |
| Features | Radius search, distance calculation, nearby cities |
| Value | Geo specialist + Title node — find cities near properties, population density |

---

## 📰 Bloomberg Market & Financial News

Bloomberg's official API requires a Terminal subscription ($24K/year). But alternatives:

| Source | Access | What |
|--------|--------|------|
| **MarketAux** | apiKey (free tier) | Stock news with tickers + sentiment, JSON API |
| **Finnhub** | apiKey (free) | Market news, company news, earnings |
| **Alpha Vantage News** | apiKey (free) | News sentiment + ticker mentions |
| **FinceptTerminal** (GitHub) | Free | Open-source Bloomberg Terminal clone with real data |
| **BriefTape** | apiKey | AI-summarized SEC filings, Fed, FDA data |

For Bloomberg-grade data without Bloomberg pricing, stack: **Finnhub + Alpha Vantage + MarketAux + SEC EDGAR + FRED**. Covers 90% of what a Terminal gives you for $0.

---

## 🏢 Company Name Match
**RapidAPI** — fuzzy matching for company names across registries.

Use case: When the title node finds "WELLS FARGO BANK NA" as grantee, match it to the canonical entity. When the swarm sees "WFC" in financial data, link it back.

---

## 🔗 URL Intelligence
Analyze URLs for category, safety, language detection.

Use case: When crawling county recorder portals, classify what type of system each URL represents. Detect if a portal has moved or gone malicious.

---

## Summary — Add to Swarm Feed Pipeline

| API | Domain | Priority | Auth |
|-----|--------|----------|------|
| NASA (all endpoints) | Geo, Weather, Grid | HIGH | Free key |
| IPWHOIS.io | Cyber, Geo | HIGH | None |
| Zippopotam.us | Title, Geo | HIGH | None |
| Utility Rate Database | Grid, Title | HIGH | RapidAPI free |
| emission-factors.com | Grid, Title | HIGH | Free |
| Electricity Maps | Grid | MEDIUM | Free non-commercial |
| CAISO | Grid | MEDIUM | RapidAPI free |
| GeoDB Cities | Geo | MEDIUM | RapidAPI free |
| MarketAux | Financial | HIGH | Free key |
| Company Name Match | Title, Financial | MEDIUM | RapidAPI free |
| NASA FIRMS (fire data) | Weather, Title | HIGH | Free key |
