#!/usr/bin/env python3
"""
PHASE 0: The Critical Experiment — Pattern Sharing Value Proof

Does sharing patterns between domain-specialized models improve predictions?

This script:
1. Loads the trained DVCE model and vocabulary
2. Partitions event data into domain groups (simulating separate nodes)
3. Trains solo models per domain group
4. Extracts patterns from each solo model
5. Augments training data with cross-domain patterns
6. Retrains "swarm-augmented" models
7. Compares solo vs swarm accuracy

Run from: /Users/webber/Desktop/next-level/
Requires: DVCE parent repo at /Users/webber/Desktop/dvce/
"""

import sys
import json
import time
import copy
import random
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

# Add DVCE to path
DVCE_ROOT = Path("/Users/webber/Desktop/dvce")
sys.path.insert(0, str(DVCE_ROOT / "src"))

from dvce.services.event_prediction.torch_model import (
    EventTransformerTorch,
    TorchModelConfig,
)
from dvce.services.event_prediction.torch_trainer import (
    EventSequenceTorchDataset,
    TorchEventTrainer,
    collate_fn,
)
from dvce.services.event_prediction.tokenizer import EventTokenizer, EventVocabulary


# ============================================================================
# CONFIGURATION
# ============================================================================

DEVICE = (
    torch.device("mps") if torch.backends.mps.is_available()
    else torch.device("cuda") if torch.cuda.is_available()
    else torch.device("cpu")
)

# Domain groupings (simulating separate swarm nodes)
DOMAIN_GROUPS = {
    "supply_chain": ["logistics", "mfg"],
    "geopolitical": ["geo"],
    "natural": ["quake", "weather", "fire", "ag"],
    "financial": ["market", "gold", "commodity", "defi"],
    "health": ["health", "trial"],
    "tech": ["cyber", "net", "incident"],
    "commerce": ["retail", "ecom", "corp"],
    "social": ["viral", "sport"],
}

# Model config for each domain specialist (smaller since less data per domain)
SPECIALIST_CONFIG = dict(
    context_dim=64,
    d_model=128,
    n_heads=4,
    n_layers=4,
    d_ff=512,
    dropout=0.1,
    max_seq_len=256,
    time_encoding_dim=32,
    learning_rate=3e-4,
    weight_decay=0.01,
    warmup_steps=100,
    max_grad_norm=1.0,
)

EPOCHS = 15
BATCH_SIZE = 32
PATTERN_CONFIDENCE_THRESHOLD = 0.6
TOP_K_PATTERNS_PER_DOMAIN = 200

# Reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


# ============================================================================
# STEP 1: LOAD DATA
# ============================================================================

def load_vocab() -> Dict[str, int]:
    """Load the trained vocabulary."""
    vocab_path = Path("/Users/webber/.dvce/models/dvce-MEGATRAIN/vocab.json")
    with open(vocab_path) as f:
        vocab_data = json.load(f)
    # vocab.json is a flat dict: event_type_name -> id
    return vocab_data


def classify_event_domain(event_type: str) -> str:
    """Determine which domain group an event belongs to."""
    for group_name, prefixes in DOMAIN_GROUPS.items():
        for prefix in prefixes:
            if event_type.startswith(prefix + "_") or event_type.startswith(prefix):
                return group_name
    return "other"


def generate_training_data(vocab: Dict[str, int]) -> Dict[str, List[List[Dict]]]:
    """Generate domain-partitioned training sequences using the multi-domain data loaders."""
    print("\n📥 Loading multi-domain training data...")
    
    # Import data loaders from DVCE
    sys.path.insert(0, str(DVCE_ROOT / "src"))
    from dvce.services.event_prediction.train_multi_domain import (
        load_commodity_prices,
        load_clinical_trial_events,
        load_weather_events,
        load_cyber_attack_events,
    )
    
    all_sequences = []
    
    # Load from HuggingFace datasets
    try:
        from datasets import load_dataset
        
        for dataset_id, max_seq in [
            ("easytpp/amazon", 300),
            ("easytpp/stackoverflow", 300),
            ("easytpp/earthquake", 300),
        ]:
            print(f"   Loading {dataset_id}...", end=" ", flush=True)
            try:
                ds = load_dataset(dataset_id, split="train")
                count = 0
                for i, row in enumerate(ds):
                    if i >= max_seq:
                        break
                    times = row.get("time_since_start", [])
                    types = row.get("type_event", [])
                    if times and types and len(times) >= 5:
                        seq = [
                            {
                                "event_id": f"{dataset_id.split('/')[-1]}_{i}_{j}",
                                "timestamp": float(t),
                                "event_type": f"tpp_type_{etype}",
                                "severity_score": 0.5,
                                "affected_node_ids": [],
                            }
                            for j, (t, etype) in enumerate(zip(times, types))
                        ]
                        all_sequences.append(seq)
                        count += 1
                print(f"✓ {count}")
            except Exception as e:
                print(f"✗ {e}")
    except ImportError:
        print("   datasets library not available, using generated data only")
    
    # Load generated domain data
    print("   Loading commodity prices...", end=" ", flush=True)
    all_sequences.extend(load_commodity_prices())
    
    print("   Loading clinical trials...", end=" ", flush=True)
    all_sequences.extend(load_clinical_trial_events())
    
    print("   Loading weather events...", end=" ", flush=True)
    all_sequences.extend(load_weather_events())
    
    print("   Loading cyber events...", end=" ", flush=True)
    all_sequences.extend(load_cyber_attack_events())
    
    # Partition by domain
    domain_sequences = defaultdict(list)
    
    for seq in all_sequences:
        if len(seq) < 5:
            continue
        # Classify by first event's domain
        first_event_type = seq[0]["event_type"]
        domain = classify_event_domain(first_event_type)
        if domain != "other":
            domain_sequences[domain].append(seq)
    
    print(f"\n   📊 Data partitioned into {len(domain_sequences)} domain groups:")
    for domain, seqs in sorted(domain_sequences.items()):
        events = sum(len(s) for s in seqs)
        print(f"      {domain:<15} {len(seqs):>5} sequences, {events:>7,} events")
    
    return dict(domain_sequences)


# ============================================================================
# STEP 2: TRAIN SOLO MODELS
# ============================================================================

def build_tokenizer_for_domain(sequences: List[List[Dict]], shared_vocab: Dict[str, int]) -> EventTokenizer:
    """Build a tokenizer that uses the shared vocabulary."""
    tokenizer = EventTokenizer(context_dim=64, max_sequence_length=256)
    
    # Register all known event types from the shared vocab
    for event_type, idx in shared_vocab.items():
        if isinstance(idx, int):
            tokenizer.vocabulary.encode(event_type)
    
    # Also tokenize local sequences to catch any new types
    for seq in sequences:
        tokenizer.tokenize_sequence(seq)
    
    tokenizer.vocabulary.freeze()
    return tokenizer


def train_model(
    sequences: List[List[Dict]],
    tokenizer: EventTokenizer,
    domain_name: str,
    epochs: int = EPOCHS,
) -> Tuple[EventTransformerTorch, Dict[str, float]]:
    """Train a single model on a domain's data."""
    
    # Split: 80% train, 20% val
    indices = np.random.permutation(len(sequences))
    split = int(len(indices) * 0.8)
    train_seqs = [sequences[i] for i in indices[:split]]
    val_seqs = [sequences[i] for i in indices[split:]]
    
    train_dataset = EventSequenceTorchDataset(train_seqs, tokenizer, max_len=256)
    val_dataset = EventSequenceTorchDataset(val_seqs, tokenizer, max_len=256)
    
    train_loader = DataLoader(
        train_dataset, batch_size=BATCH_SIZE, shuffle=True, 
        collate_fn=collate_fn, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=BATCH_SIZE, shuffle=False,
        collate_fn=collate_fn, num_workers=0
    )
    
    # Build model
    config = TorchModelConfig(
        vocab_size=tokenizer.vocabulary.size,
        **SPECIALIST_CONFIG,
    )
    
    model = EventTransformerTorch(config)
    
    # Train
    checkpoint_dir = Path(f"experiments/checkpoints/{domain_name}")
    trainer = TorchEventTrainer(
        model=model, config=config, device=DEVICE, checkpoint_dir=checkpoint_dir
    )
    
    results = trainer.train(train_loader, val_loader, epochs=epochs, log_every=50)
    
    return model, results


# ============================================================================
# STEP 3: EXTRACT PATTERNS
# ============================================================================

@dataclass
class ExtractedPattern:
    """A shareable pattern extracted from a model's predictions."""
    sequence: List[str]       # Abstract event type sequence
    confidence: float         # Model's confidence in this pattern
    source_domain: str        # Which domain group generated it
    avg_time_delta: float     # Average inter-event time in the pattern
    observation_count: int    # How many times this pattern was observed


def extract_patterns(
    model: EventTransformerTorch,
    sequences: List[List[Dict]],
    tokenizer: EventTokenizer,
    domain_name: str,
    confidence_threshold: float = PATTERN_CONFIDENCE_THRESHOLD,
    max_patterns: int = TOP_K_PATTERNS_PER_DOMAIN,
) -> List[ExtractedPattern]:
    """Extract high-confidence prediction patterns from a trained model."""
    
    model.eval()
    model.to(DEVICE)
    
    pattern_counts = defaultdict(lambda: {"count": 0, "confidence_sum": 0.0, "time_deltas": []})
    
    for seq in sequences:
        if len(seq) < 4:
            continue
        
        # Tokenize
        tokens = tokenizer.tokenize_sequence(seq)
        if len(tokens) < 4:
            continue
        
        # Build input for prediction at each position
        for pos in range(3, min(len(tokens), 50)):  # Predict from position 3 onward
            context = seq[:pos]
            
            try:
                item = EventSequenceTorchDataset([context], tokenizer, max_len=256)[0]
                batch = collate_fn([item])
                batch = {k: v.to(DEVICE) for k, v in batch.items()}
                
                with torch.no_grad():
                    outputs = model(
                        batch["token_ids"],
                        batch["inter_event_times"],
                        batch["severities"],
                        batch["context_vectors"],
                        batch["attention_mask"],
                    )
                
                # Get prediction at last real position
                last_pos = min(pos - 1, outputs["type_logits"].shape[1] - 1)
                logits = outputs["type_logits"][0, last_pos, :]
                probs = torch.softmax(logits, dim=-1)
                top_prob, top_idx = probs.max(dim=-1)
                
                if top_prob.item() >= confidence_threshold:
                    # Extract the pattern: last 3 events + predicted next
                    context_types = [e["event_type"] for e in context[-3:]]
                    predicted_type = tokenizer.vocabulary.decode(top_idx.item())
                    
                    pattern_key = tuple(context_types + [predicted_type])
                    pattern_counts[pattern_key]["count"] += 1
                    pattern_counts[pattern_key]["confidence_sum"] += top_prob.item()
                    
                    # Track time deltas
                    if pos > 1:
                        dt = context[-1].get("timestamp", 0) - context[-2].get("timestamp", 0)
                        pattern_counts[pattern_key]["time_deltas"].append(dt)
                        
            except Exception:
                continue
    
    # Convert to ExtractedPattern objects, sorted by frequency × confidence
    patterns = []
    for pattern_seq, stats in pattern_counts.items():
        if stats["count"] >= 2:  # Must be seen at least twice
            avg_conf = stats["confidence_sum"] / stats["count"]
            avg_dt = np.mean(stats["time_deltas"]) if stats["time_deltas"] else 0.0
            
            patterns.append(ExtractedPattern(
                sequence=list(pattern_seq),
                confidence=avg_conf,
                source_domain=domain_name,
                avg_time_delta=avg_dt,
                observation_count=stats["count"],
            ))
    
    # Sort by confidence × observation count and take top K
    patterns.sort(key=lambda p: p.confidence * p.observation_count, reverse=True)
    patterns = patterns[:max_patterns]
    
    return patterns


# ============================================================================
# STEP 4: AUGMENT WITH CROSS-DOMAIN PATTERNS
# ============================================================================

def augment_sequences_with_patterns(
    local_sequences: List[List[Dict]],
    foreign_patterns: List[ExtractedPattern],
    augmentation_ratio: float = 0.2,
) -> List[List[Dict]]:
    """Augment local training data with synthetic sequences from foreign patterns.
    
    Strategy: Generate synthetic event sequences based on high-confidence patterns
    from other domains and add them to the training set.
    """
    augmented = list(local_sequences)  # Keep all originals
    
    n_synthetic = int(len(local_sequences) * augmentation_ratio)
    
    for i in range(n_synthetic):
        pattern = foreign_patterns[i % len(foreign_patterns)]
        
        # Generate a synthetic sequence from the pattern
        synthetic_seq = []
        current_time = 0.0
        
        for j, event_type in enumerate(pattern.sequence):
            current_time += max(0.1, pattern.avg_time_delta + np.random.normal(0, 0.1))
            synthetic_seq.append({
                "event_id": f"synthetic_{pattern.source_domain}_{i}_{j}",
                "timestamp": current_time,
                "event_type": event_type,
                "severity_score": 0.5 + np.random.uniform(-0.1, 0.1),
                "affected_node_ids": [],
            })
        
        if len(synthetic_seq) >= 3:
            augmented.append(synthetic_seq)
    
    return augmented


# ============================================================================
# STEP 5: EVALUATE
# ============================================================================

def evaluate_model(
    model: EventTransformerTorch,
    sequences: List[List[Dict]],
    tokenizer: EventTokenizer,
) -> Dict[str, float]:
    """Evaluate a model on test sequences. Returns accuracy metrics."""
    
    model.eval()
    model.to(DEVICE)
    
    correct_top1 = 0
    correct_top5 = 0
    total = 0
    
    for seq in sequences:
        if len(seq) < 5:
            continue
        
        context = seq[:-1]
        actual = seq[-1]
        
        try:
            item = EventSequenceTorchDataset([context], tokenizer, max_len=256)[0]
            batch = collate_fn([item])
            batch = {k: v.to(DEVICE) for k, v in batch.items()}
            
            predictions = model.predict_next(
                batch["token_ids"],
                batch["inter_event_times"],
                batch["severities"],
                batch["context_vectors"],
                batch["attention_mask"],
                top_k=5,
            )
            
            actual_id = tokenizer.vocabulary.encode(actual["event_type"])
            pred_ids = [p["event_type_id"] for p in predictions]
            
            if pred_ids and pred_ids[0] == actual_id:
                correct_top1 += 1
            if actual_id in pred_ids:
                correct_top5 += 1
            total += 1
            
        except Exception:
            continue
    
    return {
        "top1_accuracy": correct_top1 / max(total, 1),
        "top5_accuracy": correct_top5 / max(total, 1),
        "total_samples": total,
    }


# ============================================================================
# MAIN EXPERIMENT
# ============================================================================

def main():
    print("\n" + "=" * 70)
    print("  PHASE 0: PATTERN SHARING VALUE PROOF")
    print("  Does sharing patterns between domains improve predictions?")
    print("=" * 70)
    print(f"\n  Device: {DEVICE}")
    print(f"  Epochs per model: {EPOCHS}")
    print(f"  Batch size: {BATCH_SIZE}")
    
    start_time = time.time()
    
    # ─── Load vocab ───
    vocab = load_vocab()
    print(f"\n  Loaded vocabulary: {len(vocab)} event types")
    
    # ─── Load and partition data ───
    domain_data = generate_training_data(vocab)
    
    # ─── Hold out test sets ───
    test_sets = {}
    train_sets = {}
    
    for domain, sequences in domain_data.items():
        np.random.shuffle(sequences)
        split = int(len(sequences) * 0.8)
        train_sets[domain] = sequences[:split]
        test_sets[domain] = sequences[split:]
        print(f"   {domain}: {len(train_sets[domain])} train, {len(test_sets[domain])} test")
    
    # ─── PHASE A: Train Solo Models (Baseline) ───
    print("\n" + "─" * 70)
    print("  PHASE A: Training SOLO models (isolated, no sharing)")
    print("─" * 70)
    
    solo_models = {}
    solo_tokenizers = {}
    solo_results = {}
    
    for domain in sorted(train_sets.keys()):
        if len(train_sets[domain]) < 10:
            print(f"\n  ⚠️  Skipping {domain} (too few sequences: {len(train_sets[domain])})")
            continue
            
        print(f"\n  🏋️ Training solo model: {domain} ({len(train_sets[domain])} sequences)")
        
        tokenizer = build_tokenizer_for_domain(train_sets[domain], vocab)
        solo_tokenizers[domain] = tokenizer
        
        model, results = train_model(
            train_sets[domain], tokenizer, f"solo_{domain}", epochs=EPOCHS
        )
        solo_models[domain] = model
        
        # Evaluate on held-out test set
        metrics = evaluate_model(model, test_sets[domain], tokenizer)
        solo_results[domain] = metrics
        
        print(f"     → Solo {domain}: top1={metrics['top1_accuracy']:.3f}, "
              f"top5={metrics['top5_accuracy']:.3f} ({metrics['total_samples']} samples)")
    
    # ─── PHASE B: Extract Patterns ───
    print("\n" + "─" * 70)
    print("  PHASE B: Extracting patterns from solo models")
    print("─" * 70)
    
    all_patterns = {}
    
    for domain, model in solo_models.items():
        print(f"\n  🔍 Extracting patterns from {domain}...", end=" ", flush=True)
        patterns = extract_patterns(
            model, train_sets[domain], solo_tokenizers[domain], domain
        )
        all_patterns[domain] = patterns
        print(f"✓ {len(patterns)} patterns (top conf: {patterns[0].confidence:.3f})" if patterns else "✗ 0 patterns")
    
    # ─── PHASE C: Train Swarm-Augmented Models ───
    print("\n" + "─" * 70)
    print("  PHASE C: Training SWARM models (augmented with cross-domain patterns)")
    print("─" * 70)
    
    swarm_models = {}
    swarm_results = {}
    
    for domain in sorted(solo_models.keys()):
        # Gather foreign patterns (from all OTHER domains)
        foreign_patterns = []
        for other_domain, patterns in all_patterns.items():
            if other_domain != domain:
                foreign_patterns.extend(patterns)
        
        if not foreign_patterns:
            print(f"\n  ⚠️  No foreign patterns available for {domain}")
            continue
        
        print(f"\n  🏋️ Training swarm model: {domain} "
              f"(+ {len(foreign_patterns)} foreign patterns)")
        
        # Augment training data
        augmented_train = augment_sequences_with_patterns(
            train_sets[domain], foreign_patterns, augmentation_ratio=0.25
        )
        
        print(f"     Original: {len(train_sets[domain])} → Augmented: {len(augmented_train)} sequences")
        
        tokenizer = build_tokenizer_for_domain(augmented_train, vocab)
        
        model, results = train_model(
            augmented_train, tokenizer, f"swarm_{domain}", epochs=EPOCHS
        )
        swarm_models[domain] = model
        
        # Evaluate on SAME test set as solo (fair comparison)
        metrics = evaluate_model(model, test_sets[domain], tokenizer)
        swarm_results[domain] = metrics
        
        print(f"     → Swarm {domain}: top1={metrics['top1_accuracy']:.3f}, "
              f"top5={metrics['top5_accuracy']:.3f} ({metrics['total_samples']} samples)")
    
    # ─── RESULTS ───
    print("\n" + "=" * 70)
    print("  RESULTS: Solo vs Swarm Comparison")
    print("=" * 70)
    
    print(f"\n  {'Domain':<15} {'Solo Top-1':>10} {'Swarm Top-1':>11} {'Δ Top-1':>8} {'Solo Top-5':>10} {'Swarm Top-5':>11} {'Δ Top-5':>8}")
    print(f"  {'─' * 15} {'─' * 10} {'─' * 11} {'─' * 8} {'─' * 10} {'─' * 11} {'─' * 8}")
    
    total_solo_top1 = 0
    total_swarm_top1 = 0
    total_solo_top5 = 0
    total_swarm_top5 = 0
    n_domains = 0
    
    for domain in sorted(solo_results.keys()):
        if domain not in swarm_results:
            continue
        
        s1 = solo_results[domain]["top1_accuracy"]
        w1 = swarm_results[domain]["top1_accuracy"]
        d1 = w1 - s1
        
        s5 = solo_results[domain]["top5_accuracy"]
        w5 = swarm_results[domain]["top5_accuracy"]
        d5 = w5 - s5
        
        marker1 = "📈" if d1 > 0.01 else ("📉" if d1 < -0.01 else "➡️")
        
        print(f"  {domain:<15} {s1:>9.1%} {w1:>10.1%} {d1:>+7.1%} {marker1} {s5:>9.1%} {w5:>10.1%} {d5:>+7.1%}")
        
        total_solo_top1 += s1
        total_swarm_top1 += w1
        total_solo_top5 += s5
        total_swarm_top5 += w5
        n_domains += 1
    
    # Averages
    if n_domains > 0:
        avg_s1 = total_solo_top1 / n_domains
        avg_w1 = total_swarm_top1 / n_domains
        avg_d1 = avg_w1 - avg_s1
        avg_s5 = total_solo_top5 / n_domains
        avg_w5 = total_swarm_top5 / n_domains
        avg_d5 = avg_w5 - avg_s5
        
        print(f"  {'─' * 15} {'─' * 10} {'─' * 11} {'─' * 8} {'─' * 10} {'─' * 11} {'─' * 8}")
        print(f"  {'AVERAGE':<15} {avg_s1:>9.1%} {avg_w1:>10.1%} {avg_d1:>+7.1%}    {avg_s5:>9.1%} {avg_w5:>10.1%} {avg_d5:>+7.1%}")
        
        # Verdict
        print("\n" + "=" * 70)
        relative_improvement = avg_d1 / max(avg_s1, 0.001) * 100
        
        if relative_improvement > 25:
            verdict = "🚀 EXCEPTIONAL — This is a platform. Pattern sharing is transformative."
        elif relative_improvement > 15:
            verdict = "🔥 STRONG — Clear value from pattern sharing. Accelerate."
        elif relative_improvement > 5:
            verdict = "✅ VALIDATED — Pattern sharing works. Proceed with confidence."
        elif relative_improvement > 0:
            verdict = "⚠️ MARGINAL — Small improvement. Experiment with abstraction levels."
        else:
            verdict = "❌ NO IMPROVEMENT — Rethink pattern representation or try ensemble-only."
        
        print(f"\n  Relative improvement: {relative_improvement:+.1f}%")
        print(f"\n  VERDICT: {verdict}")
    
    elapsed = time.time() - start_time
    print(f"\n  Total experiment time: {elapsed/60:.1f} minutes")
    print(f"  Device used: {DEVICE}")
    
    # Save results
    results_path = Path("experiments/results/phase0_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps({
        "solo_results": solo_results,
        "swarm_results": swarm_results,
        "patterns_extracted": {d: len(p) for d, p in all_patterns.items()},
        "config": SPECIALIST_CONFIG,
        "epochs": EPOCHS,
        "elapsed_seconds": elapsed,
        "device": str(DEVICE),
    }, indent=2))
    print(f"\n  Results saved: {results_path}")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
