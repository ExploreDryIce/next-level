# Extended API Catalog — Future Swarm Nodes & Tools

Beyond the core domain feeds, these APIs serve future swarm nodes, product features, internal tooling, continuous model improvement, and personal use.

---

## 🧠 Future Swarm Node: LEGAL

For a legal intelligence node — contract analysis, regulatory tracking, case law patterns.

| API | Use Case | Auth | URL |
|-----|----------|------|-----|
| **Federal Register** | Daily US government regulations, proposed rules, notices | No | federalregister.gov/reader-aids/developer-resources |
| **OpenSanctions** | Sanctions lists, PEPs, crime databases — compliance signals | No | opensanctions.org/docs/api/ |
| **UK Companies House** | Corporate filings, director data, charges | OAuth | developer.company-information.service.gov.uk |
| **OpenCorporates** | Global corporate entity lookup | apiKey | api.opencorporates.com |
| **USPTO** | Patent data, trademark search | No | uspto.gov/learning-and-resources/open-data-and-mobility |
| **PatentsView** | US patent analytics, trends, assignees | No | patentsview.org/apis/purpose |
| **EPO** | European patent search | OAuth | developers.epo.org |
| **Court Listener (RECAP)** | US federal court documents, opinions | apiKey | courtlistener.com/api/ |
| **Data.parliament.uk** | UK parliamentary bills, votes, petitions | No | explore.data.parliament.uk |
| **OpenRegistry** | Company registries across 27 countries | OAuth | openregistry.sophymarine.com |
| **Gazette Data, UK** | Official UK public notices (insolvencies, incorporations) | OAuth | thegazette.co.uk/data |

---

## 🔄 Continuous Model Improvement

APIs that provide ongoing training signal — events, trends, patterns.

| API | Training Value | Auth | URL |
|-----|---------------|------|-----|
| **All Government Open Data** (see below) | Ground truth for geo/political events across 40+ countries | Varies | Multiple portals |
| **GDELT** (via BigQuery) | 300M+ events, sentiment, themes from global news | No | gdeltproject.org |
| **Crossref** | 130M+ academic publications metadata | No | github.com/CrossRef/rest-api-doc |
| **OpenAlex** | Open catalog of scholarly works | No | docs.openalex.org |
| **Kaggle** | Datasets for benchmarking and augmentation | apiKey | kaggle.com/docs/api |
| **Archive.org** | Historical web, text, media data | No | archive.readme.io/docs |
| **Wikidata** | Structured knowledge graph | OAuth | wikidata.org/w/api.php |
| **Wikipedia** | Encyclopedic event descriptions | No | mediawiki.org/wiki/API:Main_page |
| **Chronicling America** | Historical US newspapers (Library of Congress) | No | chroniclingamerica.loc.gov/about/api/ |

---

## 🛠️ Product & Internal Tooling

APIs you specifically flagged for product features or ops.

| API | What It's For | Auth | URL |
|-----|--------------|------|-----|
| **Screenshotlayer** | Capture screenshots of any web page (crawled portal previews) | apiKey | screenshotlayer.com |
| **Clearbit Logo** | Company logos for UI/reports | apiKey | clearbit.com/docs#logo-api |
| **Google Analytics** | Track usage of DVCE/title products | OAuth | developers.google.com/analytics |
| **Instatus** | Status page for title search API uptime | apiKey | instatus.com/help/api |
| **SwiftKanban** | Kanban board for tracking crawl/build tasks | apiKey | digite.com |
| **Tomba email finder** | Find decision-maker emails for title company outreach | apiKey | tomba.io/api |
| **Bitrise** | CI/CD for mobile app builds (if doing mobile title app) | apiKey | api-docs.bitrise.io |
| **Auth0** | Authentication for title search product users | apiKey | auth0.com |
| **Micro User Service** | Lightweight user management | apiKey | m3o.com/user |
| **Web3 Storage** | Decentralized storage for document images/PDFs (IPFS) | apiKey | web3.storage |
| **UpRes** | AI image upscaling for scanned deed documents (OCR quality) | apiKey | upres.ai/docs/api |

---

## 🎨 Design & Visual

| API | Use | Auth | URL |
|-----|-----|------|-----|
| **Colormind** | AI color scheme generation for UI | No | colormind.io/api-access/ |
| **ColourLovers** | Palettes, patterns for dashboards | No | colourlovers.com/api |
| **Dribbble** | Design inspiration, UI patterns | OAuth | developer.dribbble.com |
| **xColors** | Color conversion + generation | No | x-colors.herokuapp.com |

---

## 📧 Email (All)

For outreach, verification, notifications, and monitoring alerts.

| API | What | Auth | URL |
|-----|------|------|-----|
| **Disify** | Detect disposable/temp emails (fraud prevention) | No | disify.com |
| **EVA** | Validate email deliverability | No | eva.pingutil.com |
| **Kickbox** | Email verification (open) | No | open.kickbox.com |
| **MailCheck.ai** | Block temp email signups | No | mailcheck.ai |
| **mail.gw** | 10-minute disposable email | No | docs.mail.gw |
| **mail.tm** | Temp email service | No | docs.mail.tm |
| **EmailJS** | Send emails from client-side JS | apiKey | emailjs.com/docs |
| **ImprovMX** | Free email forwarding | apiKey | improvmx.com/api |
| **Sendgrid** | Transactional email (alerts, reports) | apiKey | docs.sendgrid.com/api-reference |
| **Mailtrap** | Email testing in dev/staging | apiKey | mailtrap.docs.apiary.io |
| **DropMail** | Ephemeral inboxes via GraphQL | No | dropmail.me/api |
| **Guerrilla Mail** | Disposable email addresses | No | guerrillamail.com/GuerrillaMailAPI.html |

---

## 🌍 Environment (All)

Feeds the weather and grid specialists with climate/energy data.

| API | What | Auth | URL |
|-----|------|------|-----|
| **Carbon Interface** | Calculate CO2 from activities | apiKey | docs.carboninterface.com |
| **Climatiq** | Emission factors for activities | apiKey | docs.climatiq.io |
| **CO2 Offset** | Carbon footprint calculator | No | co2offset.io/api.html |
| **Danish Energy Data (Energinet)** | Open energy data from Denmark | No | energidataservice.dk |
| **GrünstromIndex** | German green power index | No | gruenstromindex.de |
| **IQAir** | Air quality worldwide | apiKey | iqair.com/air-pollution-data-api |
| **National Grid ESO** | GB electricity open data | No | data.nationalgrideso.com |
| **OpenAQ** | Open air quality data | apiKey | docs.openaq.org |
| **PM2.5 Open Data** | Low-cost PM2.5 sensors | No | pm25.lass-net.org |
| **PVWatts** | Solar energy production estimates | apiKey | developer.nrel.gov/docs/solar/pvwatts/v6/ |
| **Srp Energy** | Hourly usage energy reports | apiKey | srpenergy-api-client-python.readthedocs.io |
| **UK Carbon Intensity** | GB electricity carbon intensity | No | carbon-intensity.github.io |
| **Website Carbon** | Estimate carbon footprint of loading pages | No | api.websitecarbon.com |
| **BreezoMeter Pollen** | Daily pollen forecasts | apiKey | docs.breezometer.com |

---

## 🗺️ Geocoding (All)

Critical for title node (property → coordinates) and geo specialist.

| API | What | Auth | URL |
|-----|------|------|-----|
| **Nominatim (OpenStreetMap)** | Free geocoding/reverse geocoding | No | nominatim.org |
| **Geocode.xyz** | Worldwide forward/reverse geocoding | No | geocode.xyz/api |
| **GeoNames** | Place names, postal codes, elevation | No | geonames.org |
| **Zippopotam.us** | Zip code → city/state/country | No | zippopotam.us |
| **ip-api** | IP geolocation | No | ip-api.com |
| **ipapi.co** | IP geolocation + country info | No | ipapi.co |
| **GeoDB Cities** | Global city/region/country data | apiKey | geodb-cities-api.wirefreethought.com |
| **Geoapify** | Geocoding, autocomplete, routing | apiKey | geoapify.com |
| **OpenCage** | Geocoding using open data | apiKey | opencagedata.com |
| **LocationIQ** | Geocoding + routing + maps | apiKey | locationiq.org |
| **Mapbox** | Custom maps, geocoding, directions | apiKey | docs.mapbox.com |
| **Google Maps** | Geocoding, places, directions | apiKey | developers.google.com/maps |
| **HERE Maps** | Maps, routing, geocoding | apiKey | developer.here.com |
| **TomTom** | Maps, traffic, routing | apiKey | developer.tomtom.com |
| **PostcodeData.nl** | Dutch postcode geolocation | No | api.postcodedata.nl |
| **Postcodes.io** | UK postcode geolocation | No | postcodes.io |
| **ViaCep** | Brazil zip code API | No | viacep.com.br |
| **REST Countries** | Country info (borders, currencies, etc.) | No | restcountries.com |
| **CountryStateCity** | World countries/states/cities database | apiKey | countrystatecity.in |
| **US ZipCode (Smarty)** | US zip code validation + data | apiKey | smarty.com |
| **bng2latlong** | British National Grid → lat/lon | No | getthedata.com/bng2latlong |
| **Hong Kong GeoData** | HK geo data | No | geodata.gov.hk/gs/ |
| **IBGE** | Brazilian geographic/statistical data | No | servicodados.ibge.gov.br/api/docs |
| **Open Topo Data** | Elevation + ocean depth by lat/lon | No | opentopodata.org |
| **Google Earth Engine** | Planetary-scale environmental analysis | apiKey | developers.google.com/earth-engine |

---

## 🏛️ Government Open Data (All — Training Fuel)

Every government open data portal is training signal for geo, financial, health, and logistics models.

| Country/Region | Portal | URL |
|---------------|--------|-----|
| **USA** | data.gov | data.gov |
| **USA (Census)** | Census Bureau | census.gov/data/developers |
| **UK** | data.gov.uk | data.gov.uk |
| **Canada** | Open Canada | open.canada.ca |
| **Australia** | data.gov.au | data.gov.au |
| **France** | data.gouv.fr | data.gouv.fr |
| **Germany** | GovData | govdata.de |
| **India** | data.gov.in | data.gov.in |
| **Brazil** | dados.gov.br | brasilapi.com.br |
| **Ireland** | data.gov.ie | data.gov.ie/pages/developers |
| **Netherlands** | data.overheid.nl | data.overheid.nl |
| **New Zealand** | data.govt.nz | data.govt.nz |
| **Singapore** | data.gov.sg | data.gov.sg/developer |
| **Spain** | datos.gob.es | datos.gob.es |
| **Italy** | dati.gov.it | dati.gov.it |
| **Korea** | data.go.kr | data.go.kr |
| **Mexico** | datos.gob.mx | datos.gob.mx |
| **Poland** | dane.gov.pl | dane.gov.pl |
| **Portugal** | dados.gov.pt | dados.gov.pt |
| **Norway** | data.norge.no | data.norge.no |
| **Sweden** | dataportal.se | dataportal.se |
| **Finland** | avoindata.fi | avoindata.fi |
| **Denmark** | opendata.dk | opendata.dk |
| **Estonia** | avaandmed.eesti.ee | avaandmed.eesti.ee |
| **Belgium** | data.gov.be | data.gov.be |
| **Switzerland** | opendata.swiss | opendata.swiss |
| **Czech Republic** | data.gov.cz | data.gov.cz |
| **Romania** | data.gov.ro | data.gov.ro |
| **Indonesia** | data.go.id | data.go.id |
| **Thailand** | data.go.th | data.go.th |
| **Taiwan** | data.gov.tw | data.gov.tw |
| **NYC** | NYC Open Data | opendata.cityofnewyork.us |
| **Berlin** | daten.berlin.de | daten.berlin.de |
| **Helsinki** | hri.fi | hri.fi |
| **Colorado** | data.colorado.gov | data.colorado.gov |
| **DC** | opendata.dc.gov | opendata.dc.gov |
| **Istanbul** | data.ibb.gov.tr | data.ibb.gov.tr |
| **Minneapolis** | opendata.minneapolismn.gov | opendata.minneapolismn.gov |

---

## 💼 Jobs (All — Personal + Market Intelligence)

Market signals for the financial specialist (hiring = growth, layoffs = contraction) AND personal use.

| API | What | Auth | URL |
|-----|------|------|-----|
| **Adzuna** | Job board aggregator (global) | apiKey | developer.adzuna.com |
| **Arbeitnow** | European/Remote job aggregator | No | arbeitnow (Postman docs) |
| **Arbeitsamt** | German federal job board | OAuth | jobsuche.api.bund.dev |
| **Careerjet** | Job search engine | apiKey | careerjet.com/partners/api |
| **Findwork** | Dev jobs with company data | apiKey | findwork.dev/developers |
| **GraphQL Jobs** | Dev jobs via GraphQL | No | graphql.jobs/docs/api |
| **Jooble** | Global job search | apiKey | jooble.org/api/about |
| **Open Skills** | Job titles, skills, related jobs | No | github.com/workforce-data-initiative |
| **Reed** | UK job board aggregator | apiKey | reed.co.uk/developers |
| **The Muse** | Job board + company profiles | apiKey | themuse.com/developers/api/v2 |
| **USAJOBS** | US government jobs | apiKey | developer.usajobs.gov |
| **WhatJobs** | Job search engine | apiKey | whatjobs.com/affiliates |
| **ZipRecruiter** | Job search platform | apiKey | ziprecruiter.com/publishers |
| **DevITjobs UK** | UK dev jobs (GraphQL) | No | devitjobs.uk |
| **Upwork** | Freelance marketplace | OAuth | developers.upwork.com |
| **Jobs2Careers** | Job aggregator | apiKey | api.jobs2careers.com |

**Swarm value**: Job posting volume by sector/region = leading indicator for economic health. Sudden drops in a region's tech hiring → financial specialist predicts market correction. Surge in logistics/warehouse jobs → logistics specialist predicts supply chain expansion.

---

## Summary

| Category | APIs | Primary Value |
|----------|------|---------------|
| Legal Node | 11 | Future swarm specialist for regulatory/compliance |
| Model Improvement | 9 | Ongoing training data + benchmarking |
| Product Tooling | 11 | Screenshots, auth, CI/CD, email outreach, storage |
| Design | 4 | UI/UX for products |
| Email | 12 | Outreach, alerts, verification, testing |
| Environment | 14 | Weather + grid specialist feeds |
| Geocoding | 25 | Title node (parcel→coords) + geo specialist |
| Government Data | 38 portals | Training fuel for ALL specialists |
| Jobs | 16 | Market intelligence + personal |

**Grand Total: 85 (core feeds) + 140 (extended) = 225 APIs cataloged**

All free or free-tier. The swarm has access to more real-time data than most funded startups pay for.
