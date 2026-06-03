#!/usr/bin/env python3
"""
PHASE 1: Domain-Specialized Model Training

Now that Phase 0 proved pattern sharing works (+64.4% relative improvement),
this phase trains a family of specialized models at multiple scales:

1. Model size comparison: Tiny (500K) vs Standard (1.2M) vs Large (4.5M)
2. Curriculum specialization: Generalist → Specialist via progressive fine-tuning
3. Expertise score calibration: Each model gets a calibrated expertise vector
4. ONNX export: Models ready for cross-platform deployment

Results from Phase 0:
  - Pattern sharing: +5.8% absolute, +64.4% relative improvement
  - Tech domain: 0% → 23.1% top-1 (strongest cross-domain benefit)
  - Financial domain: 31.8% → 36.4% top-1
"""

import sys
import json
import time
import copy
import math
import random
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, ConcatDataset, Subset

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

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

# Model size configurations
MODEL_CONFIGS = {
    "tiny": {
        "d_model": 64,
        "n_heads": 2,
        "n_layers": 2,
        "d_ff": 256,
        "time_encoding_dim": 16,
        "description": "Edge/IoT anomaly detection (~100K params)",
    },
    "standard": {
        "d_model": 128,
        "n_heads": 4,
        "n_layers": 4,
        "d_ff": 512,
        "time_encoding_dim": 32,
        "description": "Small business node (~1.2M params)",
    },
    "large": {
        "d_model": 256,
        "n_heads": 8,
        "n_layers": 4,
        "d_ff": 1024,
        "time_encoding_dim": 64,
        "description": "Enterprise node (~4.5M params)",
    },
}

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

# Curriculum specialization schedule
CURRICULUM_PHASES = [
    {"domain_ratio": 0.7, "general_ratio": 0.3, "epochs": 10, "lr": 3e-4},
    {"domain_ratio": 0.8, "general_ratio": 0.2, "epochs": 10, "lr": 1e-4},
    {"domain_ratio": 0.9, "general_ratio": 0.1, "epochs": 10, "lr": 5e-5},
]

BATCH_SIZE = 32


# ============================================================================
# DATA LOADING (reuse from Phase 0)
# ============================================================================

def load_all_data() -> Tuple[Dict[str, List], List, EventTokenizer]:
    """Load and partition all multi-domain data. Returns domain_data, all_sequences, tokenizer."""
    
    from dvce.services.event_prediction.train_multi_domain import (
        load_commodity_prices,
        load_clinical_trial_events,
        load_weather_events,
        load_cyber_attack_events,
    )
    
    print("\n📥 Loading multi-domain training data...")
    all_sequences = []
    
    # HuggingFace datasets
    try:
        from datasets import load_dataset
        for dataset_id, max_seq in [
            ("easytpp/amazon", 300),
            ("easytpp/stackoverflow", 300),
            ("easytpp/earthquake", 300),
        ]:
            print(f"   {dataset_id}...", end=" ", flush=True)
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
                            {"event_id": f"{dataset_id.split('/')[-1]}_{i}_{j}",
                             "timestamp": float(t),
                             "event_type": f"tpp_type_{etype}",
                             "severity_score": 0.5,
                             "affected_node_ids": []}
                            for j, (t, etype) in enumerate(zip(times, types))
                        ]
                        all_sequences.append(seq)
                        count += 1
                print(f"✓ {count}")
            except Exception as e:
                print(f"✗ {e}")
    except ImportError:
        pass
    
    # Generated domain data
    all_sequences.extend(load_commodity_prices())
    all_sequences.extend(load_clinical_trial_events())
    all_sequences.extend(load_weather_events())
    all_sequences.extend(load_cyber_attack_events())
    
    # Build tokenizer
    tokenizer = EventTokenizer(context_dim=64, max_sequence_length=256)
    for seq in all_sequences:
        tokenizer.tokenize_sequence(seq)
    tokenizer.vocabulary.freeze()
    
    # Partition by domain
    domain_data = defaultdict(list)
    for seq in all_sequences:
        if len(seq) < 5:
            continue
        first_type = seq[0]["event_type"]
        for group_name, prefixes in DOMAIN_GROUPS.items():
            if any(first_type.startswith(p + "_") or first_type.startswith(p) for p in prefixes):
                domain_data[group_name].append(seq)
                break
    
    total = sum(len(s) for s in all_sequences)
    print(f"\n   📊 Total: {len(all_sequences)} sequences, {total:,} events")
    print(f"   📊 Domains: {len(domain_data)} groups")
    for d, seqs in sorted(domain_data.items()):
        print(f"      {d:<15} {len(seqs)} sequences")
    
    return dict(domain_data), all_sequences, tokenizer


# ============================================================================
# PHASE 1.1: MODEL SIZE EXPERIMENTS
# ============================================================================

def train_model_at_scale(
    model_size: str,
    sequences: List[List[Dict]],
    tokenizer: EventTokenizer,
    domain_name: str,
    epochs: int = 20,
) -> Tuple[EventTransformerTorch, Dict]:
    """Train a model at a specific scale (tiny/standard/large)."""
    
    cfg = MODEL_CONFIGS[model_size]
    
    config = TorchModelConfig(
        vocab_size=tokenizer.vocabulary.size,
        context_dim=64,
        d_model=cfg["d_model"],
        n_heads=cfg["n_heads"],
        n_layers=cfg["n_layers"],
        d_ff=cfg["d_ff"],
        dropout=0.1,
        max_seq_len=256,
        time_encoding_dim=cfg["time_encoding_dim"],
        learning_rate=3e-4,
        weight_decay=0.01,
    )
    
    model = EventTransformerTorch(config)
    total_params = sum(p.numel() for p in model.parameters())
    
    # Split data
    indices = np.random.permutation(len(sequences))
    split = int(len(indices) * 0.8)
    train_seqs = [sequences[i] for i in indices[:split]]
    val_seqs = [sequences[i] for i in indices[split:]]
    
    train_dataset = EventSequenceTorchDataset(train_seqs, tokenizer, max_len=256)
    val_dataset = EventSequenceTorchDataset(val_seqs, tokenizer, max_len=256)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)
    
    checkpoint_dir = Path(f"experiments/checkpoints/phase1/{model_size}_{domain_name}")
    trainer = TorchEventTrainer(model=model, config=config, device=DEVICE, checkpoint_dir=checkpoint_dir)
    
    results = trainer.train(train_loader, val_loader, epochs=epochs, log_every=100)
    
    return model, {
        "model_size": model_size,
        "domain": domain_name,
        "params": total_params,
        "best_val_loss": results["best_val_loss"],
        "epochs": epochs,
    }


# ============================================================================
# PHASE 1.2: CURRICULUM SPECIALIZATION
# ============================================================================

def curriculum_specialize(
    domain_sequences: List[List[Dict]],
    general_sequences: List[List[Dict]],
    tokenizer: EventTokenizer,
    domain_name: str,
) -> Tuple[EventTransformerTorch, Dict]:
    """Progressive specialization: train on increasing domain ratio."""
    
    config = TorchModelConfig(
        vocab_size=tokenizer.vocabulary.size,
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
    )
    
    model = EventTransformerTorch(config)
    model.to(DEVICE)
    
    # Split domain data: 80% train, 20% test
    d_indices = np.random.permutation(len(domain_sequences))
    d_split = int(len(d_indices) * 0.8)
    domain_train = [domain_sequences[i] for i in d_indices[:d_split]]
    domain_test = [domain_sequences[i] for i in d_indices[d_split:]]
    
    # General data (sample a subset for mixing)
    general_sample = random.sample(general_sequences, min(len(general_sequences), 500))
    
    history = []
    
    for phase_idx, phase in enumerate(CURRICULUM_PHASES):
        # Mix domain and general data according to curriculum ratio
        n_domain = int(len(domain_train) * phase["domain_ratio"] / (phase["domain_ratio"] + phase["general_ratio"]))
        n_general = int(len(domain_train) * phase["general_ratio"] / (phase["domain_ratio"] + phase["general_ratio"]))
        
        domain_sample = random.sample(domain_train, min(n_domain, len(domain_train)))
        general_mix = random.sample(general_sample, min(n_general, len(general_sample)))
        
        mixed_train = domain_sample + general_mix
        random.shuffle(mixed_train)
        
        train_dataset = EventSequenceTorchDataset(mixed_train, tokenizer, max_len=256)
        val_dataset = EventSequenceTorchDataset(domain_test, tokenizer, max_len=256)
        
        train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
        val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)
        
        # Update learning rate for this phase
        config_phase = copy.copy(config)
        config_phase.learning_rate = phase["lr"]
        
        checkpoint_dir = Path(f"experiments/checkpoints/phase1/curriculum_{domain_name}_phase{phase_idx}")
        trainer = TorchEventTrainer(model=model, config=config_phase, device=DEVICE, checkpoint_dir=checkpoint_dir)
        
        results = trainer.train(train_loader, val_loader, epochs=phase["epochs"], log_every=100)
        
        history.append({
            "phase": phase_idx,
            "domain_ratio": phase["domain_ratio"],
            "lr": phase["lr"],
            "best_val_loss": results["best_val_loss"],
            "train_size": len(mixed_train),
        })
        
        print(f"      Phase {phase_idx+1}/3: ratio={phase['domain_ratio']:.0%} domain, "
              f"lr={phase['lr']:.0e}, val_loss={results['best_val_loss']:.4f}")
    
    return model, {"domain": domain_name, "curriculum_history": history}


# ============================================================================
# PHASE 1.3: EXPERTISE SCORE CALIBRATION
# ============================================================================

def compute_expertise_scores(
    model: EventTransformerTorch,
    domain_test_sets: Dict[str, List[List[Dict]]],
    tokenizer: EventTokenizer,
) -> Dict[str, float]:
    """Compute calibrated expertise score per domain."""
    
    model.eval()
    model.to(DEVICE)
    
    scores = {}
    
    for domain, test_seqs in domain_test_sets.items():
        if not test_seqs:
            scores[domain] = 0.0
            continue
        
        correct_top1 = 0
        correct_top5 = 0
        total = 0
        confidence_sum = 0.0
        calibration_errors = []
        
        for seq in test_seqs[:50]:  # Cap at 50 for speed
            if len(seq) < 5:
                continue
            
            context = seq[:-1]
            actual = seq[-1]
            
            try:
                item = EventSequenceTorchDataset([context], tokenizer, max_len=256)[0]
                batch = collate_fn([item])
                batch = {k: v.to(DEVICE) for k, v in batch.items()}
                
                predictions = model.predict_next(
                    batch["token_ids"], batch["inter_event_times"],
                    batch["severities"], batch["context_vectors"],
                    batch["attention_mask"], top_k=5,
                )
                
                actual_id = tokenizer.vocabulary.encode(actual["event_type"])
                pred_ids = [p["event_type_id"] for p in predictions]
                top_conf = predictions[0]["probability"] if predictions else 0.0
                
                is_correct = (pred_ids[0] == actual_id) if pred_ids else False
                
                if pred_ids and pred_ids[0] == actual_id:
                    correct_top1 += 1
                if actual_id in pred_ids:
                    correct_top5 += 1
                
                # Calibration: difference between confidence and actual accuracy
                calibration_errors.append(abs(top_conf - (1.0 if is_correct else 0.0)))
                confidence_sum += top_conf
                total += 1
                
            except Exception:
                continue
        
        if total == 0:
            scores[domain] = 0.0
            continue
        
        accuracy = correct_top5 / total  # Use top-5 for expertise (more robust)
        avg_calibration_error = np.mean(calibration_errors) if calibration_errors else 0.5
        
        # Expertise = accuracy × (1 - calibration_error)
        # Well-calibrated + accurate = high expertise
        expertise = accuracy * (1.0 - min(avg_calibration_error, 0.9))
        scores[domain] = round(expertise, 4)
    
    return scores


# ============================================================================
# PHASE 1.4: ONNX EXPORT
# ============================================================================

def export_to_onnx(
    model: EventTransformerTorch,
    tokenizer: EventTokenizer,
    output_path: Path,
    model_name: str,
):
    """Export model to ONNX format for cross-platform deployment."""
    
    model.eval()
    model.to("cpu")
    
    # Create dummy inputs matching the model's expected shapes
    batch_size = 1
    seq_len = 32
    vocab_size = tokenizer.vocabulary.size
    context_dim = 64
    
    dummy_token_ids = torch.randint(0, vocab_size, (batch_size, seq_len))
    dummy_times = torch.rand(batch_size, seq_len)
    dummy_severities = torch.rand(batch_size, seq_len)
    dummy_context = torch.rand(batch_size, seq_len, context_dim)
    dummy_mask = torch.ones(batch_size, seq_len)
    
    output_file = output_path / f"{model_name}.onnx"
    output_path.mkdir(parents=True, exist_ok=True)
    
    try:
        torch.onnx.export(
            model,
            (dummy_token_ids, dummy_times, dummy_severities, dummy_context, dummy_mask),
            str(output_file),
            input_names=["token_ids", "inter_event_times", "severities", "context_vectors", "attention_mask"],
            output_names=["type_logits", "time_pred", "severity_pred"],
            dynamic_axes={
                "token_ids": {0: "batch", 1: "seq_len"},
                "inter_event_times": {0: "batch", 1: "seq_len"},
                "severities": {0: "batch", 1: "seq_len"},
                "context_vectors": {0: "batch", 1: "seq_len"},
                "attention_mask": {0: "batch", 1: "seq_len"},
                "type_logits": {0: "batch", 1: "seq_len"},
                "time_pred": {0: "batch", 1: "seq_len"},
                "severity_pred": {0: "batch", 1: "seq_len"},
            },
            opset_version=17,
        )
        file_size = output_file.stat().st_size / (1024 * 1024)
        print(f"      ✓ Exported: {output_file} ({file_size:.1f} MB)")
        return True
    except Exception as e:
        print(f"      ✗ ONNX export failed: {e}")
        return False


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "=" * 70)
    print("  PHASE 1: DOMAIN-SPECIALIZED MODEL TRAINING")
    print("  Model sizing • Curriculum specialization • Expertise calibration")
    print("=" * 70)
    print(f"\n  Device: {DEVICE}")
    print(f"  Phase 0 result: +64.4% relative improvement ✓")
    
    start_time = time.time()
    
    # ─── Load data ───
    domain_data, all_sequences, tokenizer = load_all_data()
    
    # ─── 1.1: Model Size Comparison ───
    print("\n" + "─" * 70)
    print("  1.1 MODEL SIZE EXPERIMENTS")
    print("  Training tiny/standard/large on same data to compare")
    print("─" * 70)
    
    # Use financial domain (best data from Phase 0) for size comparison
    test_domain = "financial"
    if test_domain not in domain_data or len(domain_data[test_domain]) < 20:
        test_domain = max(domain_data.keys(), key=lambda k: len(domain_data[k]))
    
    size_results = {}
    size_models = {}
    
    for size_name in ["tiny", "standard", "large"]:
        cfg = MODEL_CONFIGS[size_name]
        print(f"\n  🏋️ Training {size_name} model ({cfg['description']})")
        
        model, result = train_model_at_scale(
            size_name, domain_data[test_domain], tokenizer, test_domain, epochs=20
        )
        size_results[size_name] = result
        size_models[size_name] = model
        
        print(f"     → {size_name}: {result['params']:,} params, val_loss={result['best_val_loss']:.4f}")
    
    print("\n  📊 Size Comparison Results:")
    print(f"  {'Size':<12} {'Params':>10} {'Val Loss':>10}")
    print(f"  {'─'*12} {'─'*10} {'─'*10}")
    for size_name, result in size_results.items():
        print(f"  {size_name:<12} {result['params']:>10,} {result['best_val_loss']:>10.4f}")
    
    # ─── 1.2: Curriculum Specialization ───
    print("\n" + "─" * 70)
    print("  1.2 CURRICULUM SPECIALIZATION")
    print("  Progressive fine-tuning: generalist → specialist")
    print("─" * 70)
    
    specialist_models = {}
    specialist_histories = {}
    
    for domain in sorted(domain_data.keys()):
        if len(domain_data[domain]) < 15:
            print(f"\n  ⚠️  Skipping {domain} (too few: {len(domain_data[domain])})")
            continue
        
        print(f"\n  🎓 Curriculum specialization: {domain} ({len(domain_data[domain])} sequences)")
        
        # General data = everything NOT in this domain
        general_seqs = []
        for other_domain, seqs in domain_data.items():
            if other_domain != domain:
                general_seqs.extend(seqs)
        
        model, history = curriculum_specialize(
            domain_data[domain], general_seqs, tokenizer, domain
        )
        specialist_models[domain] = model
        specialist_histories[domain] = history
    
    # ─── 1.3: Expertise Score Calibration ───
    print("\n" + "─" * 70)
    print("  1.3 EXPERTISE SCORE CALIBRATION")
    print("  Computing expertise vectors for routing")
    print("─" * 70)
    
    # Build test sets per domain
    domain_test_sets = {}
    for domain, seqs in domain_data.items():
        n_test = max(5, int(len(seqs) * 0.2))
        domain_test_sets[domain] = seqs[-n_test:]
    
    expertise_matrix = {}
    
    for domain, model in specialist_models.items():
        print(f"\n  📐 Calibrating {domain} specialist...")
        scores = compute_expertise_scores(model, domain_test_sets, tokenizer)
        expertise_matrix[domain] = scores
        
        # Show top 3 expertises
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_scores[:3]
        print(f"     Top expertise: {', '.join(f'{d}={s:.2f}' for d, s in top3)}")
    
    # Print full expertise matrix
    print("\n  📊 Expertise Matrix (specialist × domain):")
    domains_list = sorted(domain_data.keys())
    header = f"  {'Specialist':<15}" + "".join(f"{d[:8]:>9}" for d in domains_list)
    print(header)
    print(f"  {'─'*15}" + "─" * 9 * len(domains_list))
    
    for specialist in sorted(expertise_matrix.keys()):
        row = f"  {specialist:<15}"
        for domain in domains_list:
            score = expertise_matrix[specialist].get(domain, 0.0)
            marker = "█" if score > 0.5 else "▓" if score > 0.2 else "░" if score > 0 else " "
            row += f" {marker}{score:.2f}  "
        print(row)
    
    # ─── 1.4: ONNX Export ───
    print("\n" + "─" * 70)
    print("  1.4 ONNX EXPORT")
    print("  Exporting models for cross-platform deployment")
    print("─" * 70)
    
    export_path = Path("experiments/models/onnx")
    export_results = {}
    
    # Export the best model at each size
    for size_name, model in size_models.items():
        print(f"\n  📦 Exporting {size_name} model...")
        success = export_to_onnx(model, tokenizer, export_path, f"{test_domain}_{size_name}")
        export_results[size_name] = success
    
    # Export specialist models
    for domain, model in specialist_models.items():
        print(f"\n  📦 Exporting {domain} specialist...")
        success = export_to_onnx(model, tokenizer, export_path, f"specialist_{domain}")
        export_results[f"specialist_{domain}"] = success
    
    # ─── FINAL RESULTS ───
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 70)
    print("  PHASE 1 COMPLETE")
    print("=" * 70)
    
    print(f"\n  ⏱️  Total time: {elapsed/60:.1f} minutes")
    print(f"\n  📊 Model Size Results (on {test_domain} domain):")
    for size_name, result in size_results.items():
        print(f"     {size_name:<10} {result['params']:>8,} params  val_loss={result['best_val_loss']:.4f}")
    
    print(f"\n  🎓 Specialists Trained: {len(specialist_models)}")
    for domain in sorted(specialist_models.keys()):
        hist = specialist_histories[domain]["curriculum_history"]
        final_loss = hist[-1]["best_val_loss"]
        print(f"     {domain:<15} final_val_loss={final_loss:.4f}")
    
    print(f"\n  📐 Expertise Scores Calibrated: {len(expertise_matrix)} models × {len(domains_list)} domains")
    
    exported = sum(1 for v in export_results.values() if v)
    print(f"\n  📦 ONNX Exports: {exported}/{len(export_results)} successful")
    
    # Save all results
    results_path = Path("experiments/results/phase1_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    
    results_data = {
        "size_comparison": size_results,
        "specialist_histories": specialist_histories,
        "expertise_matrix": expertise_matrix,
        "export_results": export_results,
        "elapsed_seconds": elapsed,
        "device": str(DEVICE),
        "model_configs": MODEL_CONFIGS,
    }
    results_path.write_text(json.dumps(results_data, indent=2, default=str))
    print(f"\n  💾 Results saved: {results_path}")
    
    # Save expertise scores as standalone file (used by swarm routing)
    expertise_path = Path("experiments/models/expertise_scores.json")
    expertise_path.parent.mkdir(parents=True, exist_ok=True)
    expertise_path.write_text(json.dumps(expertise_matrix, indent=2))
    print(f"  💾 Expertise scores: {expertise_path}")
    
    # Save tokenizer vocab
    vocab_path = Path("experiments/models/vocab.json")
    tokenizer.vocabulary.save(vocab_path)
    print(f"  💾 Vocabulary: {vocab_path}")
    
    print("\n" + "=" * 70)
    print("  ✅ Phase 1 Complete — Ready for Phase 2 (Pattern Extraction Pipeline)")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
