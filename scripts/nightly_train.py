"""
TerrorNode Nightly Training Script

Runs as a Windows Scheduled Task at 02:00 every night.
1. Loads foreign patterns received in last 24h
2. Combines with training data from E:\dvce-data\training\
3. Fine-tunes the tech specialist model for 5 epochs using CUDA
4. Saves updated checkpoint
5. Logs results

Setup on MSI (PowerShell as admin):
    $action = New-ScheduledTaskAction -Execute "python" -Argument "E:\dvce-data\scripts\nightly_train.py"
    $trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "DVCE-NightlyTrain" -Action $action -Trigger $trigger -Settings $settings -Description "Nightly swarm model retraining"
"""

import json
import logging
import sys
import time
from pathlib import Path

# ─── CONFIGURATION ───

DATA_DIR = Path("E:/dvce-data")
TRAINING_DATA = DATA_DIR / "training" / "all_sequences_latest.json"
PATTERN_CACHE = Path.home() / ".dvce" / "swarm" / "foreign_patterns.json"
MODEL_DIR = DATA_DIR / "models" / "production"
OUTPUT_DIR = DATA_DIR / "models" / "nightly"
LOG_FILE = DATA_DIR / "training" / "nightly_train.log"

EPOCHS = 5
BATCH_SIZE = 16
LEARNING_RATE = 1e-4
DEVICE = "cuda"  # TerrorNode has GTX 1050 Ti

# ─── LOGGING ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def load_foreign_patterns(max_age_hours: int = 24) -> list:
    """Load foreign patterns received in the last N hours."""
    if not PATTERN_CACHE.exists():
        return []

    try:
        data = json.loads(PATTERN_CACHE.read_text())
        now = time.time()
        cutoff = now - (max_age_hours * 3600)
        recent = [p for p in data if p.get("timestamp", 0) > cutoff]
        logger.info(f"Foreign patterns: {len(recent)} recent / {len(data)} total")
        return recent
    except Exception as e:
        logger.error(f"Failed to load patterns: {e}")
        return []


def load_training_sequences() -> list:
    """Load the base training sequences."""
    if not TRAINING_DATA.exists():
        logger.error(f"Training data not found: {TRAINING_DATA}")
        return []

    try:
        data = json.loads(TRAINING_DATA.read_text())
        logger.info(f"Training sequences: {len(data)}")
        return data
    except Exception as e:
        logger.error(f"Failed to load training data: {e}")
        return []


def augment_with_patterns(sequences: list, patterns: list) -> list:
    """Augment training sequences with foreign patterns.
    
    Each pattern is a sequence of event types — convert to a synthetic
    training sequence and add to the dataset.
    """
    synthetic = []
    for p in patterns:
        seq = p.get("sequence", [])
        if len(seq) < 3:
            continue

        # Convert pattern to training sequence format
        synthetic_seq = []
        for i, event_type in enumerate(seq):
            synthetic_seq.append({
                "event_type": event_type,
                "severity_score": p.get("confidence", 0.5),
                "timestamp": float(i * 3600),  # 1-hour intervals
                "affected_node_ids": [],
            })
        synthetic.append(synthetic_seq)

    # Weight: repeat synthetic patterns by observation count
    weighted = []
    for p, syn in zip(patterns, synthetic):
        count = min(p.get("observation_count", 1), 5)  # Cap at 5x
        weighted.extend([syn] * count)

    logger.info(f"Augmented: {len(sequences)} base + {len(weighted)} synthetic = {len(sequences) + len(weighted)} total")
    return sequences + weighted


def train(sequences: list):
    """Fine-tune the model on augmented data."""
    try:
        import torch
        # Add DVCE source to path (copied to MSI)
        dvce_src = Path("E:/dvce-data/src")
        if dvce_src.exists():
            sys.path.insert(0, str(dvce_src))
        
        # Also try loading from the model directory
        from dvce.services.event_prediction.inference import EventPredictor
        
        if not MODEL_DIR.exists() or not (MODEL_DIR / "best_model.pt").exists():
            logger.error(f"No model found at {MODEL_DIR}")
            return False

        # Load existing model
        predictor = EventPredictor(MODEL_DIR, device=DEVICE)
        model = predictor.model
        model.train()

        # Simple fine-tuning loop
        optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
        
        logger.info(f"Starting fine-tuning: {EPOCHS} epochs, device={DEVICE}")
        logger.info(f"Model: {sum(p.numel() for p in model.parameters()):,} params")

        for epoch in range(EPOCHS):
            epoch_loss = 0.0
            batches = 0

            for i in range(0, len(sequences), BATCH_SIZE):
                batch_seqs = sequences[i:i + BATCH_SIZE]
                
                # Tokenize batch
                for seq in batch_seqs:
                    if len(seq) < 3:
                        continue
                    
                    # Convert to model input format
                    token_ids = torch.zeros(1, min(len(seq), 64), dtype=torch.long)
                    inter_times = torch.zeros(1, min(len(seq), 64))
                    severities = torch.zeros(1, min(len(seq), 64))
                    context = torch.zeros(1, min(len(seq), 64), 64)
                    mask = torch.ones(1, min(len(seq), 64))

                    for j, event in enumerate(seq[:64]):
                        etype = event.get("event_type", "unknown")
                        tid = predictor.vocab.get(etype, predictor.vocab.get("<UNK>", 3))
                        token_ids[0, j] = tid
                        severities[0, j] = event.get("severity_score", 0.5)

                    token_ids = token_ids.to(DEVICE)
                    inter_times = inter_times.to(DEVICE)
                    severities = severities.to(DEVICE)
                    context = context.to(DEVICE)
                    mask = mask.to(DEVICE)

                    # Forward pass
                    outputs = model(token_ids, inter_times, severities, context, mask)
                    
                    # Loss: next-token prediction
                    logits = outputs["type_logits"][:, :-1, :]
                    targets = token_ids[:, 1:]
                    
                    loss = torch.nn.functional.cross_entropy(
                        logits.reshape(-1, logits.shape[-1]),
                        targets.reshape(-1),
                        ignore_index=0,
                    )

                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                    epoch_loss += loss.item()
                    batches += 1

            avg_loss = epoch_loss / max(batches, 1)
            logger.info(f"  Epoch {epoch+1}/{EPOCHS}: loss={avg_loss:.4f} ({batches} batches)")

        # Save updated model
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "model_state_dict": model.state_dict(),
            "config": {
                "vocab_size": len(predictor.vocab),
                "d_model": model.config.d_model if hasattr(model, 'config') else 384,
            },
            "nightly_train": {
                "timestamp": time.time(),
                "epochs": EPOCHS,
                "sequences": len(sequences),
                "final_loss": avg_loss,
            },
        }
        torch.save(checkpoint, str(OUTPUT_DIR / "nightly_model.pt"))
        
        # Copy vocab
        vocab_src = MODEL_DIR / "vocab.json"
        if vocab_src.exists():
            (OUTPUT_DIR / "vocab.json").write_text(vocab_src.read_text())

        logger.info(f"✅ Nightly training complete. Model saved to {OUTPUT_DIR}")
        logger.info(f"   Final loss: {avg_loss:.4f}")
        return True

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return False


def main():
    logger.info("=" * 60)
    logger.info("DVCE NIGHTLY TRAINING — TerrorNode")
    logger.info("=" * 60)

    # 1. Load foreign patterns
    patterns = load_foreign_patterns(max_age_hours=24)

    # 2. Load base training data
    sequences = load_training_sequences()
    if not sequences:
        logger.error("No training data available. Aborting.")
        return

    # 3. Augment with patterns
    augmented = augment_with_patterns(sequences, patterns)

    # 4. Train
    success = train(augmented)

    if success:
        logger.info("🎉 Nightly training succeeded")
    else:
        logger.error("❌ Nightly training failed")


if __name__ == "__main__":
    main()
