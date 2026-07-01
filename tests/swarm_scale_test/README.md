# 10+ Node Swarm Scale Test

Tests the pattern broker with 12 simulated nodes across 5 domains.

## Run

```bash
cd tests/swarm_scale_test
docker compose up --build
```

## What it does

- Starts 1 broker + 12 simulated nodes
- Nodes: 3 financial, 3 weather, 2 geo, 2 cyber, 2 grid
- Each node generates synthetic patterns at 3-6 per 10 seconds
- Broker relays with quality scoring active
- Nodes log cross-domain pattern receipt
- After 120s, each node prints final stats

## Expected results

- All 12 nodes connect and register
- Patterns flow cross-domain (financial → weather, geo → cyber, etc.)
- Quality scorer filters proven-bad patterns after accumulating data
- No message loss, no disconnects under steady load
- Broker handles ~50 patterns/10s aggregate throughput

## Cleanup

```bash
docker compose down -v
```
