# Context — Picking Up Where DVCE Left Off

## What Exists (Parent Repo: ExploreDryIce/dvce-engine)

### The Foundation
- **Event Prediction Engine**: Transformer-based next-event predictor trained on 1.3M+ events across 30+ domains
- **Architecture**: d=256, L=4, H=8, 4.5M params, 500+ event types
- **Training**: 51+ models trained on AWS SageMaker, $8 total spend
- **Domains**: Geopolitics, earthquakes, sports, commodities, cyber, weather, clinical trials, logistics, financial markets, manufacturing, healthcare, e-commerce, energy grid, IT incidents, DeFi, agriculture, construction, drug development, tech adoption, scientific discovery, economic cycles
- **Best model**: val_loss=2.80, balanced with domain tokens to prevent cross-domain bleed

### The Product
- **Product Risk Explorer**: 3D globe, cascade propagation, financial impact, AI predictions
- **Build Your Product**: Natural language → supply chain (Ollama local + Groq cloud)
- **All analysis pages** share the user's product (Signal Propagation, What-If, Sensitivity, Financial Risk, Graph Explorer, Compound Signals)
- **Live deployment**: https://dvce-dvce.streamlit.app/
- **HuggingFace**: https://huggingface.co/muddsmasher/dvce-event-grammar-model

### The Infrastructure
- **AWS**: S3 (training data), SageMaker (GPU training), ECR, IAM — all via Terraform
- **Local**: Docker Compose (Neo4j, PostGIS, NATS JetStream, MinIO)
- **NATS JetStream**: Already the event bus — becomes the gossip layer for swarm
- **LiteLLM + Ollama**: Already configured for LLM routing
- **FastAPI**: Prediction API endpoint (code written, deployable)

### Key Technical Decisions Made
- Width > depth for event grammar (d=384 beat d=192 L=12)
- Domain tokens prevent cross-domain bleed
- Balanced training data critical (cap dominant domains)
- Continuous time encoding (sinusoidal, multi-frequency)
- Multi-task output (event type + time + severity)
- Hybrid mode: deterministic cascade + learned predictions together

### AWS Account
- Account: 262101604485
- Region: us-east-1
- S3 Bucket: dvce-event-prediction-dev-data
- SageMaker role: dvce-event-prediction-sagemaker-role
- ECR: dvce-event-prediction-training

### Hardware (Development Machine)
- MacBook Pro M4 Max
- 48GB unified memory
- Can run 70B LLM models locally
- Ollama installed with qwen2.5:14b

### Accounts
- GitHub: ExploreDryIce/dvce-engine
- HuggingFace: muddsmasher
- AWS: 262101604485
- Streamlit Cloud: dvce-dvce.streamlit.app
- Groq: API key configured

---

## The Vision (What This Repo Is For)

**Distributed Intelligence Swarm** — a network of heterogeneous AI nodes that:
1. Each run specialized models (right-sized for their domain)
2. Share patterns (not data) via gossip protocol
3. Route predictions by expertise (load-balanced)
4. Get smarter collectively without central control
5. Operate independently when disconnected
6. Different models per node (vertical specialization)
7. Customer hardware IS the compute (you don't pay for it)
8. Margins improve with scale (opposite of data centers)

This is NOT:
- Another centralized AI API
- A data center play
- A consulting service

This IS:
- A network where intelligence emerges from connection
- A product where every customer makes it better for all customers
- A moat that can't be replicated by spending more money
- The "electrical grid" of predictive intelligence

---

## Implementation Path

```
Phase 1 (NOW): DVCE single-node product → paying customers
Phase 2 (5 customers): Hub & spoke pattern sharing
Phase 3 (50 customers): Mesh network with gossip protocol
Phase 4 (500 customers): Full self-organizing swarm
```

---

## To Continue This Conversation

Start a new session with:
"I'm building a distributed AI swarm for event prediction. 
The parent project (DVCE) has a working single-node product with 
a trained model (1.3M events, 30+ domains). Now I need to build 
the swarm layer: gossip protocol, expertise routing, pattern 
extraction, and heterogeneous model support. The architecture 
spec is in docs/SWARM_ARCHITECTURE.md."
