"""Write the new DVCE README."""
from pathlib import Path

readme = '''# DVCE — Event Prediction Engine for Supply Chain Intelligence

An AI system that predicts what happens next across 30+ real-world domains. Trained on 1.3 million events for $8 total. Deployed live. Published on HuggingFace.

**[Live Demo](https://dvce-dvce.streamlit.app/)** | **[Model on HuggingFace](https://huggingface.co/muddsmasher/dvce-event-grammar-model)** | **[Intelligence Layer (next-level)](https://github.com/ExploreDryIce/next-level)**

---

## What It Does

Feed it a sequence of events, it predicts what comes next, when, and how severe.

```
Input:  [port_congestion] -> [lead_time_spike] -> [cost_increase]
Output: "stockout" (P=0.73, ETA: 14 days, severity: 0.8)
```

Works across domains: supply chain disruptions, financial markets, cyber attacks, weather cascades, clinical trials, energy grid failures, geopolitical events, and 20+ more.

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Training events | 1,320,000+ |
| Domains | 30+ |
| Event types | 500+ |
| Model size | 4.5M parameters |
| Architecture | Transformer: d=256, L=4, H=8 |
| Training cost | $8 (AWS SageMaker) |
| Trained models | 51+ experiments |
| Best val_loss | 2.80 |
| Inference | <10ms on CPU, <5ms on GPU |

---

## The Product

A full supply chain intelligence platform with:

- **Product Risk Explorer** — 3D globe showing cascade propagation and financial impact
- **Build Your Product** — Describe a product in natural language, AI generates the supply chain
- **Signal Propagation** — Visualize how disruptions cascade through supplier networks
- **What-If Analysis** — "What happens if China restricts rare earth exports?"
- **Financial Risk** — Revenue-at-risk, VaR calculations, cost modeling
- **Event Predictions** — Next-event forecasting powered by the trained transformer
- **Graph Explorer** — Interactive supply chain graph visualization
- **Compound Signals** — Detect multi-event patterns that amplify risk

All pages share a unified product context — define your supply chain once, analyze from every angle.

---

## Architecture

```
+--- Operator Interface ------------------------------------------+
|  Streamlit (10 pages) + FastAPI REST                            |
+--- Intelligence Layer ------------------------------------------+
|  Event Transformer (4.5M params, 30+ domains)                   |
|  Cascade Engine (deterministic graph propagation)               |
|  LLM Layer (Ollama local + Groq cloud via LiteLLM)             |
+--- Infrastructure ----------------------------------------------+
|  NATS JetStream (event bus)                                     |
|  Neo4j (supply chain graph)                                     |
|  PostGIS (geospatial)                                           |
|  AWS S3 + SageMaker (training)                                  |
|  Docker Compose (local dev)                                     |
+-----------------------------------------------------------------+
```

---

## Technical Decisions That Matter

- **Width > depth** for event grammar — d=384 beats d=192xL=12 at this task
- **Domain tokens** prevent cross-domain bleed during training
- **Balanced training data** — cap dominant domains to prevent mode collapse
- **Continuous time encoding** (sinusoidal, multi-frequency) — not discrete positions
- **Multi-task output** — predict event type + time delta + severity simultaneously
- **Hybrid mode** — deterministic cascade + learned predictions fused for robustness

---

## Quick Start

```bash
# Clone
git clone https://github.com/ExploreDryIce/dvce-engine.git
cd dvce-engine

# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the product
streamlit run streamlit_app.py

# Run prediction API
uvicorn dvce.services.api.prediction_api:app --port 8000

# Train a model (uses SageMaker or local)
python src/dvce/services/event_prediction/train_multi_domain.py
```

---

## Model Training

Trained 51+ models on AWS SageMaker. Total spend: **$8**.

```
Data sources:
  - EasyTPP (Amazon, StackOverflow, Earthquake sequences)
  - Commodity prices (gold, oil real market data)
  - Soccer match events (StatsBomb open data)
  - Clinical trials (synthesized from published success rates)
  - Weather cascades (NOAA storm progression patterns)
  - Cyber attacks (MITRE ATT&CK kill chains)
  - Prediction markets (Polymarket probability shifts)
  - + 15 more domain-specific generators
```

Models published on HuggingFace: [muddsmasher/dvce-event-grammar-model](https://huggingface.co/muddsmasher/dvce-event-grammar-model)

---

## What Next: Distributed Intelligence

DVCE is the single-node product. The [next-level](https://github.com/ExploreDryIce/next-level) repo adds a **distributed swarm layer** — multiple DVCE nodes share anonymized patterns to collectively predict better than any individual.

Proven: pattern sharing between domain-specialized models improves accuracy by **+64.4%**. A 3-node swarm (Mac + NVIDIA + Raspberry Pi) is running live.

---

## Deployment

| Tier | Stack | Purpose |
|------|-------|---------|
| Local | Docker Compose (Neo4j, PostGIS, NATS, MinIO) | Development |
| Cloud | Streamlit Cloud | Live demo |
| Production | AWS (S3, SageMaker, ECR) | Training + model hosting |

---

## License

MIT
'''

Path('/Users/webber/Desktop/dvce/README.md').write_text(readme)
print('DVCE README written successfully')
