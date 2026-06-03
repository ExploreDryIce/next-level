---
inclusion: auto
---

# Next-Level Project Context

## What This Is
A distributed AI prediction swarm — multiple specialized models on heterogeneous hardware sharing anonymized temporal patterns to collectively predict events better than any individual node.

## Relationship to DVCE
- **DVCE** (`/Users/webber/Desktop/dvce`) is the product — customer-facing prediction engine
- **next-level** is the intelligence layer underneath DVCE
- The `SwarmPredictor` in `src/integrations/dvce_swarm_bridge.py` is a drop-in replacement for DVCE's `EventPredictor`
- Every DVCE prediction can feed patterns into the swarm
- The swarm makes DVCE predictions better over time

## What's Been Proven
- Pattern sharing improves predictions by +64.4% (Phase 0 experiment)
- 3-node swarm running live: Mac (MPS) + MSI TerrorNode (CUDA) + Raspberry Pi (ARM CPU)
- 7/7 integration tests passing
- Sub-millisecond broker latency
- Query routing by expertise domain works
- Cross-domain cascade propagation works

## Key Architecture
- **Broker**: `src/swarm/broker.py` — runs on Mac port 9876, relays patterns
- **Node**: `src/node/swarm_node.py` — runs on any machine, connects to broker
- **Bridge**: `src/integrations/dvce_swarm_bridge.py` — connects DVCE to swarm
- **Command Center**: `src/command_center/control.py` — CLI monitoring
- **Discord**: `src/command_center/discord_reporter.py` — push notifications

## Running Services (persistent, auto-start on boot)
- Mac: `com.dvce.broker` + `com.dvce.node` (launchd)
- TerrorNode: `DVCE-SwarmNode` (Windows Scheduled Task)
- TowerSeven: `@reboot` cron job

## SSH Access
- TerrorNode: `sshpass -p '3614' ssh "jwebber533@gmail.com@100.99.237.66"`
- TowerSeven: `sshpass -p 'jbooger33%' ssh webber@towerseven.local`

## What to Build Next
- Wire SwarmPredictor into DVCE's prediction_api.py
- Add live data feeds to nodes (free APIs: NOAA, Yahoo Finance, GDELT)
- Build the pattern extraction pipeline as a proper background service
- Production UI (React/Next.js) for DVCE
