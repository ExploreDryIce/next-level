# Public API Feeds for the Swarm

Free and low-cost APIs that feed real-time event data into domain specialists. Each API maps to one or more swarm domains and generates pattern-extractable event sequences.

Source: github.com/public-apis/public-apis (curated June 2026)

---

## 🟢 NO AUTH REQUIRED (Hit immediately)

### Finance & Economics

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **FRED** (Federal Reserve Economic Data) | Interest rates, GDP, unemployment, CPI — macro signals | Financial | fred.stlouisfed.org/docs/api/fred/ |
| **SEC EDGAR** | Annual reports, 10-K/10-Q filings for public US companies | Financial | sec.gov/edgar/sec-api-documentation |
| **Fed Treasury (Fiscal Data)** | US Treasury spending, debt, revenue — real-time fiscal | Financial | fiscaldata.treasury.gov/api-documentation/ |
| **Econdb** | Global macro data — GDP, inflation, trade across countries | Financial | econdb.com/api/ |
| **CoinGecko** | Crypto prices, market caps, volume — no key needed | Financial | coingecko.com/api |
| **CoinCap** | Real-time crypto prices via REST | Financial | docs.coincap.io |
| **Coinpaprika** | Crypto prices, volume, market data | Financial | api.coinpaprika.com |
| **Portfolio Optimizer** | Portfolio analysis, optimization, risk metrics | Financial | portfoliooptimizer.io |
| **WallstreetBets Sentiment** | Reddit WSB stock sentiment analysis | Financial | dashboard.nbshare.io/apps/reddit/api/ |
| **Frankfurter** | ECB exchange rates, conversion, time series | Financial | frankfurter.app/docs |
| **Currency-api** | 150+ currency exchange rates, no rate limits | Financial | github.com/fawazahmed0/currency-api |
| **Exchangerate.host** | Forex & crypto rates, free, no key | Financial | exchangerate.host |
| **Indian Mutual Fund** | Complete history of India mutual fund data | Financial | mfapi.in |
| **Binlist** | IIN/BIN card number info (bank identification) | Financial | binlist.net |

### Weather & Environment

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **Open-Meteo** | Global hourly weather forecast, historical data — no key! | Weather | open-meteo.com |
| **US Weather (NWS)** | NOAA forecasts, alerts, observations for all US | Weather | weather.gov/documentation/services-web-api |
| **7Timer!** | Astronomy weather forecasts | Weather | 7timer.info/doc.php |
| **wttr.in** | Weather in terminal, JSON output | Weather | wttr.in/:help |
| **Pirate Weather** | Dark Sky-compatible forecast API, free | Weather | pirateweather.net |
| **AviationWeather** | NOAA aviation METARs, TAFs, SIGMETs | Weather | aviationweather.gov/dataserver |
| **RainViewer** | Global radar data from multiple sources | Weather | rainviewer.com/api.html |
| **openSenseMap** | Personal weather station data worldwide | Weather | api.opensensemap.org |
| **UK Carbon Intensity** | GB electricity carbon intensity (National Grid) | Weather/Grid | carbon-intensity.github.io |
| **Danish Energy Data** | Danish open energy data (Energinet) | Grid | energidataservice.dk |
| **National Grid ESO** | GB electricity system operator open data | Grid | data.nationalgrideso.com |
| **GrünstromIndex** | German green power index | Grid | gruenstromindex.de |
| **PVWatts** | Solar energy production estimates by location | Grid | developer.nrel.gov/docs/solar/pvwatts/v6/ |
| **CO2 Offset** | Carbon footprint calculation | Weather | co2offset.io/api.html |
| **OpenAQ** | Global air quality measurements | Weather | docs.openaq.org |
| **PM2.5 Open Data** | Low-cost air quality sensor data | Weather | pm25.lass-net.org |

### Geopolitical & Government

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **USGS Earthquakes** | Real-time global earthquake data | Geo | earthquake.usgs.gov/fdsnws/event/1/ |
| **USGS Water Services** | River/lake water levels and quality | Geo/Weather | waterservices.usgs.gov |
| **FBI Wanted** | FBI wanted persons data | Cyber/Security | fbi.gov/wanted/api |
| **OpenFEMA** | Disaster declarations, flood zones, grants — free, no key | Geo/Title | fema.gov/about/openfema/api |
| **USAspending.gov** | Federal spending data | Financial | api.usaspending.gov |
| **Federal Register** | Daily Journal of US Government | Geo/Financial | federalregister.gov/reader-aids/developer-resources |
| **Census.gov** | US demographics, economics, population | Geo | census.gov/data/developers/data-sets.html |
| **Data USA** | US public data (demographics, economics, education) | Geo | datausa.io/about/api/ |
| **EPA** | Environmental Protection Agency data | Geo/Weather | epa.gov/developers |
| **Interpol Red Notices** | International wanted persons | Security | interpol.api.bund.dev |
| **OpenSanctions** | Sanctions, crime, politically exposed persons | Security/Financial | opensanctions.org/docs/api/ |
| **UK Police** | UK crime data by location | Security | data.police.uk/docs/ |

### Science & Space

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **NASA** | Imagery, NEO asteroids, Mars weather, APOD | Geo | api.nasa.gov |
| **Launch Library 2** | Spaceflight launches and events | Geo | thespacedevs.com/llapi |
| **SpaceX** | Launch data, rockets, capsules | Geo | github.com/r-spacex/SpaceX-API |
| **OpenSky Network** | Real-time global aircraft positions (ADS-B) | Logistics | opensky-network.org/apidoc |
| **ISS Location** | International Space Station current position | Geo | open-notify.org |

### Transportation & Logistics

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **OpenSky Network** | Real-time aircraft tracking | Logistics | opensky-network.org/apidoc |
| **ADS-B Exchange** | All airborne aircraft data | Logistics | adsbexchange.com/data/ |
| **Open Charge Map** | Global EV charging station locations | Grid/Logistics | openchargemap.org/site/develop/api |
| **City Bikes** | Bike sharing systems worldwide | Logistics | api.citybik.es/v2/ |
| **TransitLand** | Transit aggregation across agencies | Logistics | transit.land/documentation |
| **transport.rest** | Public transport APIs (developer-friendly) | Logistics | transport.rest |

### Health & Biotech

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **openFDA** | Drug adverse events, recalls, labels | Health | open.fda.gov |
| **Open Disease** | COVID-19 and influenza tracking | Health | disease.sh |
| **Healthcare.gov** | US health insurance marketplace data | Health | healthcare.gov/developers |
| **NPPES** | US healthcare provider registry | Health | npiregistry.cms.hhs.gov/registry/help-api |

### Security & Cyber

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **URLhaus** | Malicious URLs for malware distribution | Cyber | urlhaus-api.abuse.ch |
| **MalwareBazaar** | Malware samples sharing | Cyber | bazaar.abuse.ch/api/ |
| **Shodan** | Internet-connected device search (key needed but free tier) | Cyber | developer.shodan.io |
| **National Vulnerability DB** | US NVD vulnerability data | Cyber | nvd.nist.gov |
| **PhishStats** | Phishing database | Cyber | phishstats.info |
| **GreyNoise** | IP reputation and internet noise | Cyber | docs.greynoise.io |
| **AlienVault OTX** | Open threat exchange intelligence | Cyber | otx.alienvault.com/api |

### News & Events (Signal Sources)

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **Spaceflight News** | Space-related news | Geo | spaceflightnewsapi.net |
| **Chronicling America** | Historical US newspapers (Library of Congress) | Geo/Historical | chroniclingamerica.loc.gov/about/api/ |
| **HackerNews** | Tech/startup news feed | Cyber/Financial | github.com/HackerNews/API |

### Open Data & Reference

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **REST Countries** | Country info (borders, currencies, languages, population) | Geo | restcountries.com |
| **Wikidata** | Structured knowledge base | All | wikidata.org/w/api.php |
| **Wikipedia** | Encyclopedia content | All | mediawiki.org/wiki/API:Main_page |
| **Nobel Prize** | Nobel laureates and events | Historical | nobelprize.org/about/developer-zone-2 |
| **Archive.org** | Internet Archive data | Historical | archive.readme.io/docs |
| **OpenCorporates** | Global corporate entity data | Financial | api.opencorporates.com |
| **Crossref** | Academic publication metadata | Health/All | github.com/CrossRef/rest-api-doc |

---

## 🟡 FREE API KEY REQUIRED (Register once, use forever)

### Finance

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **Alpha Vantage** | Real-time & historical stock data | Financial | alphavantage.co |
| **Finnhub** | Real-time stocks, forex, crypto via REST + WebSocket | Financial | finnhub.io/docs/api |
| **Twelve Data** | Stock market data (real-time & historical) | Financial | twelvedata.com |
| **Polygon.io** | Historical stock market data | Financial | polygon.io |
| **Marketstack** | Real-time worldwide stock data | Financial | marketstack.com |
| **Financial Modeling Prep** | Stock data, financials, SEC filings | Financial | financialmodelingprep.com |
| **IEX Cloud** | Real-time & historical market data | Financial | iexcloud.io/docs/api |
| **FRED** | Federal Reserve economic data (key = free) | Financial | fred.stlouisfed.org |
| **Nasdaq Data Link** | Stock market data | Financial | docs.data.nasdaq.com |
| **FEC** | Campaign finance / donations data | Financial/Geo | api.open.fec.gov |

### Weather

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **OpenWeatherMap** | Current weather, forecasts, historical | Weather | openweathermap.org/api |
| **Weatherstack** | Real-time weather for any location | Weather | weatherstack.com |
| **Visual Crossing** | Global historical + forecast weather | Weather | visualcrossing.com/weather-api |
| **WeatherAPI** | Weather + astronomy + geolocation | Weather | weatherapi.com |
| **Tomorrow.io** | Proprietary weather intelligence | Weather | docs.tomorrow.io |
| **Storm Glass** | Marine weather from multiple sources | Weather | stormglass.io |
| **IQAir** | Air quality data worldwide | Weather | iqair.com/air-pollution-data-api |

### Security

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **AbuseIPDB** | IP/domain reputation | Cyber | docs.abuseipdb.com |
| **VirusTotal** | File/URL malware analysis | Cyber | docs.virustotal.com |
| **Shodan** | Internet device search engine | Cyber | developer.shodan.io |
| **SecurityTrails** | DNS, WHOIS, domain history | Cyber | securitytrails.com/corp/apidocs |
| **HaveIBeenPwned** | Data breach exposure check | Cyber | haveibeenpwned.com/API/v3 |

### Geolocation & Mapping

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **ipstack** | IP geolocation | Geo | ipstack.com |
| **Geoapify** | Geocoding, routing, places | Geo | geoapify.com |
| **OpenCage** | Forward/reverse geocoding (open data) | Geo | opencagedata.com |
| **LocationIQ** | Geocoding, routing, maps | Geo | locationiq.org |
| **Google Earth Engine** | Planetary-scale environmental analysis | Geo/Weather | developers.google.com/earth-engine |

### News

| API | What It Feeds | Swarm Domain | URL |
|-----|--------------|--------------|-----|
| **NewsAPI** | Headlines from 80K+ sources | All | newsapi.org |
| **GNews** | Global news search | All | gnews.io |
| **TheNews** | Aggregated headlines | All | thenewsapi.com |
| **The Guardian** | Guardian content API | All | open-platform.theguardian.com |
| **New York Times** | NYT article search, top stories | All | developer.nytimes.com |
| **Currents** | Real-time global news, multilingual | All | currentsapi.services |

---

## 🔴 PAID (But High Value for Production)

| API | What It Feeds | Domain | Why It Matters |
|-----|--------------|--------|---------------|
| **ATTOM Data** | National property records, deeds, mortgages | Title | The paid version of what we're building free |
| **Regrid** | 155M parcel boundaries, national | Title/Geo | Best parcel data (free for nonprofits) |
| **GDELT** | Global events database, real-time | All | Largest open event dataset globally |
| **Refinitiv/LSEG** | Institutional financial data | Financial | What hedge funds use |
| **Bloomberg** | Terminal-grade market data | Financial | Gold standard |

---

## Priority Integration Order

### Phase 1: Immediate (No auth, no cost, instant value)

1. **Open-Meteo** → Weather specialist (replaces any paid weather API)
2. **US Weather (NWS)** → Weather specialist (US-specific alerts + forecasts)
3. **USGS Earthquakes** → Geo specialist (real-time seismic events)
4. **OpenFEMA** → Title node (flood zones) + Geo specialist (disasters)
5. **FRED** → Financial specialist (macro indicators)
6. **SEC EDGAR** → Financial specialist (corporate filings)
7. **Fed Treasury** → Financial specialist (fiscal data)
8. **OpenSky Network** → Logistics specialist (air traffic)
9. **URLhaus + NVD** → Cyber specialist (threat feeds)
10. **UK Carbon Intensity + National Grid ESO** → Grid specialist

### Phase 2: Free Key (Register `uppittylocker@proton.me` once)

11. **OpenWeatherMap** → Weather specialist (broader coverage)
12. **Alpha Vantage** → Financial specialist (stock data)
13. **Finnhub** → Financial specialist (real-time + WebSocket)
14. **NewsAPI** → All specialists (event signals from news)
15. **Shodan** → Cyber specialist (internet exposure)
16. **AbuseIPDB** → Cyber specialist (IP reputation)
17. **Visual Crossing** → Weather specialist (70+ year historical)

### Phase 3: High-Value Paid

18. **GDELT** (free but massive) → Global event detection
19. **Regrid** (free for research) → National parcel boundaries
20. **ATTOM** → National title/property data (once revenue justifies)

---

## Swarm Domain Coverage Map

| Domain | No-Auth APIs | Key-Required APIs | Total Sources |
|--------|-------------|-------------------|---------------|
| **Financial** | 14 | 10 | 24 |
| **Weather** | 11 | 7 | 18 |
| **Geo** | 9 | 4 | 13 |
| **Cyber** | 7 | 5 | 12 |
| **Logistics** | 6 | 0 | 6 |
| **Health** | 4 | 0 | 4 |
| **Grid** | 5 | 1 | 6 |
| **Title** | 2 | 0 | 2 |
| **TOTAL** | **58** | **27** | **85** |

85 free or free-tier APIs across 8 swarm domains. The swarm can ingest events from all of these simultaneously, extract cross-domain patterns, and compound intelligence across every specialist.
