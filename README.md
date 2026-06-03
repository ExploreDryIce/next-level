# Next Level — Distributed AI Prediction Swarm

A network of specialized AI models on heterogeneous hardware that share anonymized temporal patterns to collectively predict events better than any individual node. No central server. No data sharing. Intelligence emerges from connection.

**Proven**: Pattern sharing between domain-specialized models improves prediction accuracy by **+64.4%**. Tested live across 3 physical machines (Apple Silicon + NVIDIA CUDA + ARM CPU).

---

## Architecture

```
                    ┌─────────────────────────┐
                    │    Pattern Broker        │
                    │    (coordinator)         │
                    └─────┬─────────┬─────────┘
                          │         │         │
              ┌───────────┘         │         └───────────┐
              │                     │                     │
     ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐
     │  Node: Financial │  │  Node: Tech     │  │  Node: Natural  │
     │  MacBook M4 Max  │  │  MSI GP63       │  │  Raspberry Pi 3 │
     │  4.4M params     │  │  1.1M params    │  │  143K params    │
     │  MPS GPU         │  │  CUDA GTX 1050  │  │  ARM CPU        │
     └─────────────────┘  └─────────────────┘  └─────────────────┘
```

Each node runs a right-sized model for its hardware, shares patterns (not data) with the network, and routes queries to the most qualified specialist.

---

## What's Been Proven

| Experiment | Result | Method |
|-----------|--------|--------|
| Pattern sharing improves accuracy | **+64.4% relative** (9.0% → 14.9% top-1) | Split data by domain, train solo vs swarm-augmented models |
| Tech domain bootstrapping | **0% → 23.1%** accuracy via cross-domain patterns | Domain that couldn't predict alone became functional from shared patterns |
| Small models are sufficient | 156K params achieves 45% accuracy | Tiny/Standard/Large comparison — diminishing returns above 1.1M |
| 3-node heterogeneous swarm | **7/7 integration tests pass** | Mac + MSI + Pi communicating over Tailscale mesh |
| Sub-millisecond routing | **0.6ms average** broker latency | 10-request latency benchmark |
| Cross-domain cascade propagation | Weather events alert financial + tech nodes | Pattern injection and broadcast test |

---

## Quick Start

```bash
# Start the broker (coordinator)
python src/swarm/broker.py --host 0.0.0.0 --port 9876

# Start a node (auto-detects hardware)
python src/node/swarm_node.py --profile mac        # Apple Silicon
python src/node/swarm_node.py --profile terrornode  # NVIDIA CUDA
python src/node/swarm_node.py --profile towerseven  # Raspberry Pi

# Check swarm status
python src/command_center/control.py status

# Run integration tests
python src/swarm/test_swarm.py

# Send status to Discord
python src/command_center/discord_reporter.py status
```

---

## How It Works

1. **Each node trains a specialized model** for its domain (financial, cyber, weather, etc.)
2. **High-confidence predictions generate patterns** — abstract event sequences like `[port_scan → exploit → privilege_escalation]`
3. **Patterns flow through the broker** to all connected nodes (no raw data leaves any node)
4. **Nodes incorporate foreign patterns** to augment their local training data
5. **Queries route by expertise** — a financial question goes to the financial specialist, not the weather node
6. **The network compounds** — more nodes = more patterns = better predictions = more value per node

---

## Tech Stack

- **Models**: PyTorch transformers (64-256 dim, 2-4 layers), trained on 1.3M events across 30+ domains
- **Inference**: ONNX-compatible, runs on MPS (Apple), CUDA (NVIDIA), CPU (ARM/x86)
- **Communication**: Async TCP broker with JSON protocol (upgradeable to NATS JetStream)
- **Networking**: Tailscale mesh for secure cross-machine connectivity
- **Monitoring**: CLI command center + Discord webhook notifications
- **Deployment**: launchd (Mac), Windows Scheduled Tasks, cron (Linux)

---

## Project Structure

```
next-level/
├── src/
│   ├── node/               # Swarm node (runs on any machine)
│   │   ├── swarm_node.py   # Core node runtime
│   │   ├── config.py       # Node profiles (mac/terrornode/towerseven)
│   │   └── network.py      # Broker communication client
│   ├── swarm/              # Swarm protocol
│   │   ├── broker.py       # Pattern relay + routing
│   │   └── test_swarm.py   # Integration test suite
│   ├── command_center/     # System control
│   │   ├── control.py      # CLI: status, watch, route, inject
│   │   └── discord_reporter.py  # Push notifications
│   └── integrations/       # DVCE product bridge
│       └── dvce_swarm_bridge.py  # Drop-in predictor replacement
├── experiments/
│   ├── phase0_pattern_sharing.py   # Critical experiment (+64.4%)
│   ├── phase1_specialization.py    # Multi-scale model training
│   └── results/                    # Experiment data (JSON)
├── docs/
│   ├── SWARM_ARCHITECTURE.md       # Full technical specification
│   ├── FEASIBILITY_ANALYSIS.md     # Research-backed feasibility review
│   ├── TECHNICAL_REVIEW.md         # Principal engineer architecture review
│   ├── FINANCIAL_DEEP_DIVE.md      # Market analysis + unit economics
│   └── TRAINING_PLAN.md            # 18-week model training roadmap
├── scripts/                # Deployment automation
├── services/               # Persistent service configs (launchd, etc.)
└── README.md
```

---

## The Economics

Traditional AI companies pay for every inference call (GPU cost scales linearly with usage). This architecture inverts that:

- **Customer hardware runs inference** — provider cost per query approaches zero
- **Margins improve with scale** — more nodes = more free compute capacity
- **Network effects compound** — each node makes all others more accurate
- **Can't be replicated by spending** — the intelligence IS the network

---

## Relationship to DVCE

[DVCE](https://github.com/ExploreDryIce/dvce-engine) is the customer-facing product — a prediction engine with 3D globe visualization, cascade analysis, and AI recommendations. This repo is the intelligence layer underneath it.

- **DVCE** = what the customer sees (predictions, alerts, dashboards)
- **next-level** = what makes those predictions get better over time (the swarm)

Every DVCE prediction feeds patterns into this network. Every pattern from the network improves DVCE predictions. The system compounds.

---

## Status

- [x] Phase 0: Pattern sharing validated (+64.4% improvement)
- [x] Phase 1: Multi-scale model training + expertise calibration
- [x] 3-node swarm deployed and tested (Mac + MSI + Raspberry Pi)
- [x] Command center + Discord integration
- [x] Persistent services (survive reboots)
- [ ] Live data feeds (NOAA, Yahoo Finance, GDELT)
- [ ] Production React/Next.js UI
- [ ] NATS JetStream upgrade (from TCP broker)
- [ ] 10+ node network test

---

## License

MIT
