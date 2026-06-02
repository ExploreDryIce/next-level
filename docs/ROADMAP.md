# Roadmap — From Single Node to Swarm

## Phase 1: Foundation (Current — DVCE)
- [x] Event prediction model trained
- [x] 30+ domains, 500+ event types
- [x] Deterministic cascade engine
- [x] LLM assistant (local + cloud)
- [x] Product Risk Explorer with 3D globe
- [x] Build Your Product (AI-generated supply chains)
- [x] Shared product system across all pages
- [x] Streamlit Cloud deployed
- [x] HuggingFace published
- [x] FastAPI endpoint
- [ ] Get 5 paying customers
- [ ] Figma → React/Next.js production UI

## Phase 2: Pattern Sharing (5-10 Customers)
- [ ] Pattern extraction layer (anonymize local events → shareable patterns)
- [ ] Central pattern aggregator (simple — receives, stores, redistributes)
- [ ] Weekly model update push to all nodes
- [ ] Metrics: track prediction improvement from shared patterns
- [ ] Privacy audit: ensure no customer data leaks

## Phase 3: Mesh Network (50+ Customers)
- [ ] Gossip protocol (epidemic pattern spreading, no central broker)
- [ ] Expertise advertisement (each node publishes what it's good at)
- [ ] Request routing (query goes to most expert node)
- [ ] Multi-model support (different model sizes per node)
- [ ] Consensus mechanism (weighted voting for ambiguous predictions)
- [ ] Node health monitoring (detect and route around failed nodes)

## Phase 4: Full Swarm (500+ Customers)
- [ ] Self-organizing specialization (nodes naturally drift toward domains)
- [ ] Automatic model right-sizing (scale model up/down based on load)
- [ ] Cross-domain emergence (swarm discovers patterns no single node could)
- [ ] Zero central infrastructure (fully peer-to-peer)
- [ ] Edge device support (IoT sensors as tiny nodes)
- [ ] Real-time global event detection (port closure → all affected nodes alerted in seconds)

## Research Questions
- How much do shared patterns improve individual node accuracy?
- What's the minimum swarm size for emergent cross-domain intelligence?
- How to prevent adversarial nodes (poisoning the pattern pool)?
- Optimal gossip frequency vs bandwidth cost?
- When does a specialized small model beat a generalist large model?
