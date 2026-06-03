# Training Plan
## From Existing Model → Swarm-Ready Specialized Models → Validated Pattern Sharing

**Hardware**: MacBook Pro M4 Max, 48GB unified memory  
**Cloud**: AWS SageMaker (us-east-1), S3 bucket `dvce-event-prediction-dev-data`  
**Existing Assets**: 1.3M events, 30+ domains, 51 trained models, best val_loss=2.80  
**Architecture**: d=256, L=4, H=8, 4.5M params, domain tokens, continuous time encoding

---

## PHASE 0: THE CRITICAL EXPERIMENT (Weekend — 2-3 Days)

This is the experiment that validates or kills the swarm thesis. Everything else in this plan is contingent on this working.

### Goal
Prove that sharing patterns between domain-specialized models improves prediction accuracy compared to isolated models.

### Experiment Design

```
┌──────────────────────────────────────────────────────────────────────┐
│  EXPERIMENT: Pattern Sharing Value Proof                              │
├──────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Step 1: Partition data into domain groups (simulate separate nodes)   │
│  Step 2: Train solo models per domain group                            │
│  Step 3: Extract patterns from each solo model's predictions           │
│  Step 4: Augment each domain's training data with cross-domain         │
│           patterns                                                      │
│  Step 5: Train swarm-augmented models                                  │
│  Step 6: Compare solo vs swarm accuracy on held-out test set           │
│                                                                        │
│  SUCCESS CRITERIA:                                                     │
│    >5% improvement  = thesis validated, proceed                        │
│    >15% improvement = strong signal, accelerate                        │
│    >25% improvement = exceptional, this is a platform                  │
│    <5% improvement  = rethink pattern abstraction layer                │
│    Worse accuracy   = fundamental problem with approach                │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Execution

#### 0.1 — Data Partitioning

Split the 1.3M events into domain clusters. You already have domain tokens, so this is straightforward.

```python
# Suggested domain groups (simulate 6-8 "nodes"):
DOMAIN_GROUPS = {
    "supply_chain": ["logistics", "manufacturing", "e-commerce", "construction"],
    "geopolitical": ["geopolitics", "economic_cycles"],
    "natural":     ["earthquakes", "weather", "agriculture"],
    "financial":   ["financial_markets", "commodities", "DeFi"],
    "health":      ["healthcare", "clinical_trials", "drug_development"],
    "tech":        ["cyber", "IT_incidents", "tech_adoption"],
    "energy":      ["energy_grid"],
    "science":     ["scientific_discovery"],
}

# Hold out 20% per domain for testing
# Use 80% for training (split again: 70% train, 10% validation)
```

#### 0.2 — Train Solo Models (Baseline)

Train one model per domain group using ONLY that group's data. Same architecture (d=256, L=4, H=8) but trained on subset data.

```
Training config per solo model:
  - Architecture: identical to current best (4.5M params)
  - Data: only events from that domain group
  - Epochs: same as current best training run
  - Hyperparams: same as current best
  - Output: solo_model_{domain_group}.pt + val_loss metric

Expected: Each model will perform well on its domain, 
          poorly on other domains (that's the point).
```

**Time estimate**: 6-8 models × ~15-30 min each on M4 Max (small data subsets) = 2-4 hours.

#### 0.3 — Pattern Extraction

Run each solo model on its validation set. Extract the event sequences it predicts correctly with high confidence.

```python
# Pattern extraction algorithm:
def extract_patterns(model, data, confidence_threshold=0.7):
    patterns = []
    for sequence in data:
        predictions = model.predict_sequence(sequence)
        for i, pred in enumerate(predictions):
            if pred.confidence > confidence_threshold:
                # Extract the preceding context + predicted event as a pattern
                pattern = {
                    "context": abstract_sequence(sequence[max(0,i-3):i]),
                    "prediction": abstract_event(pred.event_type),
                    "confidence": pred.confidence,
                    "domain": get_domain_group(sequence),
                    "temporal_delta": pred.time_delta,
                    # NO raw data, NO customer info, NO specific entities
                }
                patterns.append(pattern)
    return patterns

def abstract_sequence(events):
    """Convert specific events to abstract pattern tokens.
    
    e.g., 'shenzhen_port_closure' → 'logistics_disruption'
          'lead_time_increase_45d' → 'time_impact_moderate'
    """
    return [EVENT_ABSTRACTION_MAP[e.event_type] for e in events]
```

**Key design decision**: The abstraction level. Start with your existing 500+ event type vocabulary — these are ALREADY abstractions. A "port_congestion" event type doesn't name the port. Try sharing at this level first. If it works, you can experiment with more/less abstraction later.

**Time estimate**: 1-2 hours to implement and run.

#### 0.4 — Pattern Incorporation (The Core Test)

Take each domain group's training data. Augment it with patterns extracted from OTHER domain groups. Then retrain.

```python
# Pattern incorporation strategies (try all three, compare):

# Strategy A: Synthetic sequence injection
# Generate synthetic training sequences that embed cross-domain patterns
def augment_with_patterns_synthetic(local_data, foreign_patterns):
    augmented = local_data.copy()
    for pattern in foreign_patterns:
        if is_relevant(pattern, local_domain):  # domain adjacency check
            synthetic_seq = generate_sequence_from_pattern(pattern)
            augmented.append(synthetic_seq)
    return augmented

# Strategy B: Pattern-conditioned training (multitask)
# Add a secondary objective: predict whether a foreign pattern 
# will manifest locally given the current sequence context
def add_pattern_prediction_head(model, foreign_patterns):
    # Additional output head: "Is pattern X active given context?"
    pass

# Strategy C: Training data reweighting
# Upweight local sequences that match cross-domain patterns
# (the foreign pattern validates that this sequence type matters)
def reweight_by_pattern_match(local_data, foreign_patterns):
    for seq in local_data:
        match_score = max_pattern_similarity(seq, foreign_patterns)
        seq.weight = 1.0 + (match_score * BOOST_FACTOR)
    return local_data
```

**Time estimate**: 3-5 hours (implementing 3 strategies + training 6-8 models per strategy = 18-24 training runs at ~20 min each, parallelizable on M4 Max).

#### 0.5 — Evaluation

```python
# For each domain group, on held-out test set:
results = {}
for domain in DOMAIN_GROUPS:
    solo_acc = evaluate(solo_models[domain], test_data[domain])
    for strategy in ['A', 'B', 'C']:
        swarm_acc = evaluate(swarm_models[domain][strategy], test_data[domain])
        results[domain][strategy] = {
            "solo_accuracy": solo_acc,
            "swarm_accuracy": swarm_acc,
            "delta": swarm_acc - solo_acc,
            "relative_improvement": (swarm_acc - solo_acc) / solo_acc
        }

# Metrics to compute:
# - Top-1 accuracy (correct next event type)
# - Top-5 accuracy (correct event in top 5 predictions)
# - val_loss (cross-entropy, comparable to your 2.80 baseline)
# - Domain-specific breakdown (which domains benefit most?)
# - Cross-domain detection rate (does supply_chain model catch geo patterns?)
```

#### 0.6 — What to Do With Results

| Result | Meaning | Next Action |
|--------|---------|-------------|
| Δ > 25% across domains | Exceptional. The swarm primitive works brilliantly. | Skip to Phase 2 immediately. This is your pitch deck. |
| Δ 15-25% | Strong. Clear value from pattern sharing. | Proceed to Phase 1 training plan. Prioritize pattern extraction quality. |
| Δ 5-15% | Moderate. Works but needs refinement. | Experiment with abstraction levels. Try richer pattern representations. |
| Δ 0-5% | Marginal. Patterns carry signal but not much. | Investigate: are patterns too abstract? Too few? Wrong domains? |
| Δ < 0% | Patterns are noise. | Try different abstraction levels. If still negative: pivot to pure ensemble (no pattern transfer, just routing + consensus). |

---

## PHASE 1: DOMAIN-SPECIALIZED MODEL TRAINING (Weeks 1-3)

*Proceed only if Phase 0 shows Δ > 5%*

### Goal
Train a family of specialized models at different scales, proving that right-sized models per domain outperform the single generalist.

### 1.1 — Model Size Experiments

Train models at 3 scales to determine the right sizing per node type:

```
┌─────────────────────────────────────────────────────────────────┐
│  MODEL SIZE MATRIX                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Tiny (500K params):   d=128, L=2, H=4                           │
│    Target: Edge/IoT, anomaly detection only                       │
│    Train on: Single domain, simplified event vocabulary            │
│    Goal: >80% accuracy on binary anomaly detection                │
│                                                                   │
│  Standard (4.5M params): d=256, L=4, H=8                         │
│    Target: Small business / Mac Mini nodes                        │
│    Train on: 1-4 domain cluster                                   │
│    Goal: Match or beat current best (val_loss ≤ 2.80)            │
│                                                                   │
│  Large (15-20M params): d=384, L=6, H=12                         │
│    Target: Enterprise nodes with GPU                              │
│    Train on: Full multi-domain data                               │
│    Goal: Beat standard by 10%+ on cross-domain tasks              │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 — Specialization Training Protocol

For each domain group, train a specialist:

```
Specialization Recipe:
  1. Start from the pre-trained generalist (your current best model)
  2. Fine-tune on domain-specific data (70% domain, 30% general)
     - The 30% general prevents catastrophic forgetting
     - The 70% domain drives specialization
  3. Gradually shift ratio over epochs: 70/30 → 80/20 → 90/10
     - "Curriculum-style" specialization
  4. Validate on domain-specific test set AND general test set
     - Track both: domain accuracy should climb
     - General accuracy will drop — that's ok, but monitor how fast

Training schedule per specialist:
  - Epochs: 50-100 (early stopping on domain val_loss)
  - LR: Start at 1e-4 (lower than initial training since fine-tuning)
  - LR schedule: Cosine annealing with warm restarts
  - Batch size: 64-128 (fits in M4 Max memory easily)
  - Time per model: 30-60 minutes local
```

### 1.3 — Expertise Score Calibration

Each specialized model needs a calibrated expertise score so the swarm can route queries correctly.

```python
# Expertise score computation:
def compute_expertise_scores(model, benchmark_datasets):
    """Run model against standardized benchmarks per domain.
    Returns a vector of expertise scores [0, 1] per domain."""
    
    scores = {}
    for domain, benchmark in benchmark_datasets.items():
        predictions = model.predict_batch(benchmark)
        
        # Compute calibrated accuracy:
        # Not just raw accuracy — calibrate probability estimates
        accuracy = top_k_accuracy(predictions, k=5)
        calibration = expected_calibration_error(predictions)
        
        # Expertise = accuracy * (1 - calibration_error)
        # High accuracy + well-calibrated = high expertise
        scores[domain] = accuracy * (1.0 - calibration)
    
    return scores

# Expected output for a supply_chain specialist:
# {
#   "supply_chain": 0.91,
#   "geopolitical": 0.35,  (some knowledge from fine-tuning base)
#   "financial": 0.42,
#   "natural": 0.15,
#   "health": 0.12,
#   "tech": 0.28,
#   "energy": 0.22,
#   "science": 0.10
# }
```

### 1.4 — ONNX Export for Cross-Platform Deployment

Every trained model needs to be deployable on customer hardware (x86, ARM, GPU, CPU).

```
Export pipeline per model:
  1. PyTorch → ONNX (torch.onnx.export)
  2. ONNX optimization (constant folding, fuse operations)
  3. Validate: compare ONNX output to PyTorch output (max delta < 1e-5)
  4. Benchmark inference speed:
     - M4 Max (Apple Silicon): target <5ms
     - x86 CPU (Intel i7): target <10ms
     - Raspberry Pi 5 (tiny model only): target <50ms
  5. Package: model.onnx + config.json + expertise_scores.json
```

---

## PHASE 2: PATTERN EXTRACTION & SHARING TRAINING (Weeks 4-6)

### Goal
Build and validate the pattern extraction pipeline. Determine the optimal abstraction level. Create the training loop that incorporates foreign patterns.

### 2.1 — Pattern Schema Definition

```protobuf
// Pattern message format (Protobuf for efficiency + versioning)

message EventPattern {
  string pattern_id = 1;           // UUID
  repeated string sequence = 2;     // Abstract event tokens
  float confidence = 3;             // Source model confidence [0, 1]
  string source_domain = 4;         // Which domain group observed this
  float temporal_span_hours = 5;    // How long the sequence took to unfold
  repeated float time_deltas = 6;   // Normalized time between events
  int32 observation_count = 7;      // How many times seen locally
  int64 first_observed_ts = 8;      // Unix timestamp
  int64 last_observed_ts = 9;       // For half-life computation
  float severity_range_min = 10;    // Severity envelope
  float severity_range_max = 11;
  
  // Privacy: NO customer identifiers, NO geographic specifics,
  // NO entity names, NO financial figures
}
```

### 2.2 — Abstraction Level Experiments

The key question: how abstract should patterns be?

```
Experiment: Test 4 abstraction levels

Level 1 (Raw event types — most specific):
  ["port_congestion", "lead_time_spike", "cost_increase"]
  → Carries most information, highest re-identification risk

Level 2 (Category abstraction — your existing vocabulary):
  ["logistics_disruption", "time_impact", "cost_impact"]
  → Good balance — preserves causal structure, removes specifics

Level 3 (Semantic roles only):
  ["disruption", "propagation", "financial_effect"]
  → Very private, but might lose domain-specific signal

Level 4 (Embedding vectors — opaque):
  [0.82, -0.15, 0.67, ...]  (pattern encoded as a dense vector)
  → Maximum privacy, but requires shared embedding space

For each level:
  1. Extract patterns from domain models at that abstraction
  2. Share across domains
  3. Measure prediction improvement (same as Phase 0)
  4. Measure re-identification risk (can an adversary infer source?)
  
Pick the level that maximizes: improvement / risk
```

### 2.3 — Pattern Relevance Model

Not every pattern is useful to every node. Train a lightweight relevance classifier:

```python
# Relevance model: should this node incorporate this pattern?
# Small model — runs on every incoming pattern

class PatternRelevanceModel:
    """Binary classifier: is this foreign pattern relevant to my domain?"""
    
    # Input features:
    # - Pattern embedding (from shared encoder)
    # - My domain expertise vector
    # - Semantic similarity score
    # - Source domain distance (domain graph)
    # - Pattern recency
    
    # Training data: 
    # Positive examples = foreign patterns that DID improve my predictions
    # Negative examples = foreign patterns that didn't help or hurt
    
    # Architecture: Simple MLP, <10K params, inference <1ms
    # Train on Phase 0 experiment results (you now have labeled data)
```

### 2.4 — Incremental Learning Protocol

When a node receives a relevant foreign pattern, how does it incorporate it without full retraining?

```
Strategy comparison (train all three, measure accuracy + cost):

Strategy A: Buffer and retrain periodically
  - Accumulate patterns in a buffer (100-1000 patterns)
  - Weekly: regenerate augmented training set, full retrain
  - Pro: Simple, well-understood
  - Con: Slow to adapt, wasteful compute
  - Best for: Phase 2 (weekly model updates)

Strategy B: Online fine-tuning with experience replay
  - Each new relevant pattern triggers a micro fine-tune step
  - Use experience replay buffer (mix old training data + new patterns)
  - 10-50 gradient steps per pattern batch
  - Pro: Adapts quickly, compute-efficient
  - Con: Catastrophic forgetting risk, needs careful LR scheduling
  - Best for: Phase 3+ (real-time adaptation)

Strategy C: Adapter modules (LoRA-style)
  - Base model stays frozen (your well-trained generalist)
  - Domain-specific LoRA adapter captures specialization
  - Pattern-informed adapter captures cross-domain knowledge
  - Pro: No forgetting, multiple adapters composable
  - Con: More complex architecture, slight inference overhead
  - Best for: Phase 3+ (heterogeneous model support)

Training configs for each:
  Strategy A:
    - Retrain trigger: every 7 days or 500 patterns (whichever first)
    - Training: same as original but with augmented dataset
    - Validation: must not regress on domain test set
    
  Strategy B:
    - Learning rate: 1e-5 (very conservative)
    - Replay ratio: 10:1 (10 old samples per 1 new pattern sample)
    - Steps per batch: 20
    - Checkpoint after each batch (rollback if val_loss increases)
    
  Strategy C:
    - LoRA rank: 8-16
    - Alpha: 16-32
    - Target modules: attention Q, K, V projections
    - Train adapter only, freeze base
    - Per-pattern adapter update: 50 steps, LR 5e-4
```

---

## PHASE 3: ENSEMBLE & CONSENSUS TRAINING (Weeks 7-9)

### Goal
Train the consensus mechanism that merges predictions from multiple specialized nodes into a superior combined prediction.

### 3.1 — Calibration Training

Before merging predictions, each model's outputs must be calibrated to a common scale.

```python
# Calibration protocol:
# A shared benchmark set (subset of original training data, held out)
# Every model runs predictions on this benchmark
# Temperature scaling calibrates each model's confidence

class ModelCalibrator:
    def __init__(self, model, benchmark_data):
        self.model = model
        # Find optimal temperature T such that:
        # calibrated_prob = softmax(logits / T)
        # minimizes Expected Calibration Error on benchmark
        self.temperature = optimize_temperature(model, benchmark_data)
    
    def calibrate(self, raw_logits):
        return softmax(raw_logits / self.temperature)

# Training procedure:
# 1. Hold out 5% of original data as "calibration benchmark"
#    (same across all models — this is the shared reference)
# 2. For each trained model, run on benchmark
# 3. Optimize temperature parameter (single scalar, trivial optimization)
# 4. Store temperature per model
# 5. All consensus merging uses calibrated probabilities

# Expected temperatures:
#   Overconfident models (small, specialized): T > 1.0 (softens predictions)
#   Underconfident models (large, general): T < 1.0 (sharpens predictions)
```

### 3.2 — Consensus Model Training

The consensus mechanism isn't just averaging — it's a learned merger.

```python
# Consensus model: given N predictions from N nodes, output best prediction

class ConsensusModel:
    """Lightweight model that learns optimal prediction merging.
    
    Input: 
      - N calibrated prediction distributions (each over 500+ event types)
      - N expertise scores for the query domain
      - N model confidence scores
      - Query domain embedding
      - Temporal context embedding
    
    Output:
      - Merged prediction distribution
      - Confidence interval
      - Disagreement signal (high entropy = nodes disagree = valuable info)
    """
    
    # Architecture: Attention over node predictions
    # Think of it as: "Which nodes should I listen to for THIS query?"
    #
    # cross_attention(
    #   query = query_context,
    #   keys = [node_expertise_vectors],
    #   values = [node_prediction_distributions]
    # )
    
    # Size: ~500K params (tiny, runs on coordinator node)
    # Training data: Generated from Phase 0/1 experiments
    #   - Input: multiple solo model predictions on same test examples
    #   - Label: ground truth event
    #   - Learn which combination strategy beats simple averaging

# Training data generation:
# For each test example:
#   1. Get predictions from all domain models
#   2. Record ground truth
#   3. Training input: [pred_1, confidence_1, expertise_1, ..., pred_N, ...]
#   4. Training target: ground truth event type + timing + severity

# This model learns:
#   - When to trust the specialist (high expertise, high confidence)
#   - When to trust the consensus (disagreement = uncertainty)
#   - When to flag contradictions as signals (not noise)
```

### 3.3 — Disagreement Detection Training

Train a classifier to distinguish "noise disagreement" (one model is wrong) from "signal disagreement" (models see different aspects of reality).

```python
# Training data for disagreement detector:
# 
# Label "signal_disagreement" when:
#   - Models disagree AND the minority prediction turns out correct
#     (the dissenter saw something others missed)
#   - Models disagree AND both partial predictions manifest
#     (multi-outcome scenario)
#
# Label "noise_disagreement" when:
#   - Models disagree AND the majority prediction is correct
#     (the dissenter was just wrong)
#
# Features:
#   - Entropy of prediction distribution across nodes
#   - Expertise score variance for query domain
#   - Temporal context similarity to training data
#   - Cross-domain signal strength (is dissenter from adjacent domain?)

# Model: Binary classifier (signal vs noise disagreement)
# Architecture: Small MLP, ~50K params
# Training: Standard binary cross-entropy
# Use: When disagreement detected, run this classifier
#      If "signal" → surface to user as elevated uncertainty
#      If "noise" → use majority prediction, discard outlier
```

---

## PHASE 4: SWARM SIMULATION TRAINING (Weeks 10-14)

### Goal
Simulate the full swarm lifecycle on your laptop using your existing data. Validate emergence, specialization dynamics, and scaling behavior.

### 4.1 — Multi-Node Simulation Framework

```python
# Simulate N nodes on single machine
# Each node: separate model instance + separate data partition + gossip interface

class SimulatedSwarm:
    def __init__(self, n_nodes, domain_assignments):
        self.nodes = []
        for i in range(n_nodes):
            node = SimulatedNode(
                node_id=i,
                domain=domain_assignments[i],
                model=load_specialized_model(domain_assignments[i]),
                local_data=get_domain_data(domain_assignments[i]),
                pattern_buffer=[],
                expertise_scores=compute_initial_expertise(...)
            )
            self.nodes.append(node)
    
    def simulate_epoch(self):
        # 1. Each node processes local events and makes predictions
        for node in self.nodes:
            node.process_local_events()
        
        # 2. Each node extracts patterns from successful predictions
        for node in self.nodes:
            node.extract_patterns()
        
        # 3. Gossip: each node shares with K random peers
        for node in self.nodes:
            peers = random.sample(self.nodes, k=3)
            for peer in peers:
                patterns = node.get_outgoing_patterns()
                peer.receive_patterns(patterns)
        
        # 4. Each node incorporates relevant foreign patterns
        for node in self.nodes:
            node.incorporate_patterns()
        
        # 5. Update expertise scores based on recent performance
        for node in self.nodes:
            node.update_expertise_scores()
    
    def simulate_query(self, query):
        """Route a query through the swarm and get consensus prediction."""
        entry_node = random.choice(self.nodes)
        
        # Entry node evaluates local expertise
        if entry_node.expertise_for(query) > 0.7:
            return entry_node.predict(query)
        
        # Route to specialists
        specialists = self.find_specialists(query)
        predictions = [s.predict(query) for s in specialists]
        
        # Consensus merge
        return self.consensus_model.merge(predictions, specialists)
```

### 4.2 — Scaling Experiments

Run the simulation at different network sizes. Measure when emergence appears.

```
Experiment matrix:

| N Nodes | Domains Covered | Metric: Accuracy vs Solo | Metric: Cross-Domain Detection |
|---------|-----------------|--------------------------|-------------------------------|
| 3       | 3               | Baseline comparison       | Can it detect 2-hop cascades? |
| 5       | 5               | Marginal improvement?     | 2-hop cascades                |
| 10      | 8+              | Meaningful improvement?   | 3-hop cascades                |
| 20      | 10+             | Clear improvement         | Cross-continent cascades?     |
| 50      | 15+             | Strong improvement        | Full cascade detection         |
| 100     | 20+             | Diminishing returns?      | Novel pattern discovery?       |

For each N:
  - Run 100 simulated "days" of events
  - Measure per-node accuracy improvement over time
  - Measure cross-domain cascade detection rate
  - Measure time-to-detection for planted cascades
  - Plot: accuracy vs simulation day (learning curve)
  - Plot: accuracy vs N (scaling curve)
```

### 4.3 — Planted Cascade Experiments

To test emergence, plant synthetic multi-step cascades in the simulation and measure whether the swarm detects them before individual nodes would.

```python
# Plant a cascade that spans 3 nodes/domains:
def plant_cascade(swarm, cascade_spec):
    """
    cascade_spec = [
        {"node": 2, "event": "raw_material_shortage", "day": 10},
        {"node": 5, "event": "production_delay", "day": 13},
        {"node": 1, "event": "delivery_failure", "day": 17},
    ]
    """
    for step in cascade_spec:
        swarm.nodes[step["node"]].inject_event(step["event"], step["day"])
    
    # Measure: 
    # - Does node 1 get warned BEFORE day 17?
    # - How many days early?
    # - What's the confidence of the warning?
    # - Compare: with gossip ON vs gossip OFF

# Generate 100 synthetic cascades across different domains
# Run swarm with gossip ON: measure detection rate and lead time
# Run swarm with gossip OFF: measure detection rate and lead time
# Delta = the VALUE of the swarm
```

### 4.4 — Specialization Dynamics Measurement

Track how expertise scores evolve over simulated time:

```
Metrics to track per node per epoch:
  - Expertise score per domain (are they converging to specialties?)
  - Generalist capability (are they maintaining cross-domain baseline?)
  - Pattern incorporation rate (what % of received patterns are useful?)
  - Query routing efficiency (are queries reaching the right node faster?)
  - Time to specialization (how many epochs until stable expertise profile?)

Plot:
  - Expertise score heatmap: nodes × domains × time
    (should show diagonal strengthening = specialization)
  - Diversity index over time
    (should NOT go to zero — that means tunnel vision)
```

---

## PHASE 5: PRODUCTION-READY MODEL PIPELINE (Weeks 15-18)

### Goal
Build the automated training pipeline that takes a new node from generic to specialized to swarm-integrated.

### 5.1 — New Node Onboarding Training

When a new customer deploys a node, it needs to rapidly specialize:

```
New Node Training Sequence:
  
  Day 0: Deploy with pre-trained generalist model (your current best)
         Node is immediately functional — just not specialized yet.
  
  Day 1-7: Collect local event data (customer's actual events)
           Run inference with generalist model (provides value immediately)
           Buffer all local events for fine-tuning
  
  Day 7: First specialization round
         Fine-tune on local data (Strategy C: LoRA adapter)
         Compute initial expertise scores
         Advertise expertise to swarm
         Begin receiving relevant patterns from peers
  
  Day 14: Second specialization round
          Incorporate received patterns (best strategy from Phase 2)
          Re-compute expertise scores
          Update routing tables
  
  Day 30: Stabilized specialist
          Model is now domain-adapted and swarm-integrated
          Expertise scores are calibrated
          Pattern extraction is flowing
          Full swarm participant
```

### 5.2 — Continuous Training Pipeline

```
Automated weekly training loop (per node):

  Monday:
    - Collect all local events from past week
    - Extract patterns from successful predictions
    - Share patterns with swarm (via gossip)
    
  Tuesday:
    - Receive and filter foreign patterns
    - Score pattern relevance
    - Add relevant patterns to training buffer
    
  Wednesday:
    - Run incremental training (Strategy B or C from Phase 2)
    - Validate: must not regress on domain test set
    - If regression: rollback to previous checkpoint
    
  Thursday:
    - Re-calibrate expertise scores
    - Update consensus model with new calibration
    - Publish updated expertise to swarm
    
  Friday-Sunday:
    - Normal inference operations (no training)
    - Accumulate next week's training data
    
  Compute cost per week per node:
    - Fine-tuning: ~30-60 minutes on customer hardware (background job)
    - Pattern extraction: ~5 minutes
    - Calibration: ~10 minutes
    - Total GPU/CPU time: <2 hours/week (insignificant)
```

### 5.3 — Model Registry & Versioning

```
Model artifact structure (per node):

node_{id}/
├── base_model.onnx              # Frozen generalist (shared across all nodes)
├── domain_adapter.onnx          # LoRA adapter for domain specialization
├── pattern_adapter.onnx         # LoRA adapter for cross-domain patterns
├── calibration.json             # Temperature scaling parameters
├── expertise_scores.json        # Current expertise vector
├── training_history.json        # All training runs, metrics, configs
├── pattern_buffer/              # Received patterns pending incorporation
│   ├── pending.jsonl
│   └── incorporated.jsonl
└── checkpoints/                 # Last 4 weekly checkpoints (rollback)
    ├── week_01/
    ├── week_02/
    ├── week_03/
    └── week_04/
```

---

## COMPUTE BUDGET & TIMELINE

### Local (M4 Max) — All experimentation

| Phase | Duration | Compute Hours | Cost |
|-------|----------|---------------|------|
| Phase 0 (Critical Experiment) | 2-3 days | 8-12 hours | $0 (local) |
| Phase 1 (Specialization) | 2-3 weeks | 30-50 hours | $0 (local) |
| Phase 2 (Pattern Extraction) | 2-3 weeks | 20-30 hours | $0 (local) |
| Phase 3 (Consensus) | 2-3 weeks | 15-25 hours | $0 (local) |
| Phase 4 (Simulation) | 3-4 weeks | 40-80 hours | $0 (local) |
| Phase 5 (Pipeline) | 3-4 weeks | 20-30 hours | $0 (local) |

**Total local compute**: ~150-230 hours over 14-18 weeks.

Your M4 Max with 48GB can run all of this. The models are small (4.5M params). Training data fits in memory. No cloud needed until you're training the 15-50M param enterprise models.

### Cloud (SageMaker) — Large model training only

| Task | Instance | Duration | Cost |
|------|----------|----------|------|
| Large model (15M params) training | ml.g4dn.xlarge | ~2 hours | ~$2 |
| Large model (50M params) training | ml.g4dn.2xlarge | ~4 hours | ~$6 |
| Scaling experiment (100 simulated nodes) | ml.g4dn.xlarge | ~8 hours | ~$8 |

**Total estimated cloud cost**: $15-30 for the entire training plan.

You spent $8 training 51 models before. This plan will cost roughly the same.

---

## DECISION GATES

```
After Phase 0:
  Δ > 5%?  → PROCEED to Phase 1
  Δ < 5%?  → ITERATE on abstraction level (2 more attempts)
  Still < 5% after 3 attempts? → PIVOT to ensemble routing only (no pattern transfer)

After Phase 1:
  Specialists beat generalist by >10% on domain tasks? → PROCEED
  Specialists don't outperform? → Check training data quality per domain

After Phase 2:
  Pattern incorporation stable (no regression)? → PROCEED
  Frequent regressions? → Strengthen relevance filtering

After Phase 3:
  Consensus beats best individual node? → PROCEED
  Consensus doesn't help? → Simplify to weighted average (skip learned merger)

After Phase 4:
  Emergence visible at N ≤ 50? → Full speed ahead to product
  Emergence only at N > 200? → Adjust Phase 3 timeline (more customers needed first)
  No emergence at any N? → Product is still valuable as expertise-routed ensemble
                            (just not "emergent intelligence" — still a great product)
```

---

## WHAT SUCCESS LOOKS LIKE

At the end of this training plan (18 weeks), you have:

1. **Empirical proof** that pattern sharing improves predictions (with exact % measured)
2. **A family of specialized models** at 3 scales, with calibrated expertise scores
3. **A validated pattern extraction pipeline** at the optimal abstraction level
4. **A trained consensus model** that provably outperforms individual nodes
5. **Simulation data** showing emergence thresholds and scaling curves
6. **A production-ready training pipeline** for onboarding new nodes
7. **ONNX-exported models** ready to deploy on customer hardware

All running on your laptop, with $15-30 of cloud spend, ready for Phase 2 of the product.

Run Phase 0 first. If it works, the rest is just execution.

---

*Let's go.*
