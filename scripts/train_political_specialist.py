"""Train Political Specialist — Combines all political/market training data and trains on CUDA.

Run on TerrorNode:
    C:\Python311\python.exe train_political_specialist.py

Training data sources:
    - political_market_sequences.json (180 sequences, 3155 events)
    - tweet_training_sequences.json (1558 sequences from Trump tweets)
    - historical_political_sequences.json (16-year history)

Output:
    E:\dvce-data\models\political_specialist\best_model.pt
    E:\dvce-data\models\political_specialist\final_model.pt
    E:\dvce-data\models\political_specialist\vocab.json
"""

import json
import sys
import os
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Paths
TRAINING_DIR = Path("E:/dvce-data/training")
OUTPUT_DIR = Path("E:/dvce-data/models/political_specialist")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Add dvce-server to path for imports
sys.path.insert(0, "C:/Users/jwebb/dvce-server")
sys.path.insert(0, "C:/Users/jwebb/dvce-server/src")


def load_all_political_sequences():
    """Load and combine all political training data."""
    all_sequences = []

    # 1. Political market sequences (180)
    path = TRAINING_DIR / "political_market_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        all_sequences.extend(seqs)
        logger.info(f"  political_market_sequences: {len(seqs)} sequences")

    # 2. Tweet training sequences (1558)
    path = TRAINING_DIR / "tweet_training_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        all_sequences.extend(seqs)
        logger.info(f"  tweet_training_sequences: {len(seqs)} sequences")

    # 3. Historical political sequences
    path = TRAINING_DIR / "historical_political_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        all_sequences.extend(seqs)
        logger.info(f"  historical_political_sequences: {len(seqs)} sequences")

    # 4. Political market cycles
    path = TRAINING_DIR / "political_market_cycles.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        if isinstance(seqs, list) and seqs and isinstance(seqs[0], list):
            all_sequences.extend(seqs)
            logger.info(f"  political_market_cycles: {len(seqs)} sequences")

    return all_sequences


def build_vocab(sequences):
    """Build vocabulary from all event types in sequences."""
    event_types = set()
    for seq in sequences:
        for event in seq:
            if isinstance(event, dict):
                et = event.get("event_type", event.get("type", "unknown"))
            else:
                et = str(event)
            event_types.add(et)

    # Sort for deterministic vocab
    vocab = {"<PAD>": 0, "<UNK>": 1, "<BOS>": 2, "<EOS>": 3}
    for i, et in enumerate(sorted(event_types), start=4):
        vocab[et] = i

    return vocab


def main():
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader

    logger.info("=" * 60)
    logger.info("POLITICAL SPECIALIST TRAINING — TerrorNode CUDA")
    logger.info("=" * 60)
    logger.info(f"PyTorch: {torch.__version__}")
    logger.info(f"CUDA: {torch.cuda.is_available()} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'})")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Load data
    logger.info("Loading training data...")
    sequences = load_all_political_sequences()
    logger.info(f"Total: {len(sequences)} sequences")

    if not sequences:
        logger.error("No training data found!")
        return

    # Build vocab
    vocab = build_vocab(sequences)
    logger.info(f"Vocabulary: {len(vocab)} event types")

    # Save vocab
    (OUTPUT_DIR / "vocab.json").write_text(json.dumps(vocab, indent=2))

    # Convert sequences to token IDs
    def seq_to_ids(seq):
        ids = [vocab.get("<BOS>", 2)]
        for event in seq:
            if isinstance(event, dict):
                et = event.get("event_type", event.get("type", "unknown"))
            else:
                et = str(event)
            ids.append(vocab.get(et, vocab["<UNK>"]))
        ids.append(vocab.get("<EOS>", 3))
        return ids

    tokenized = [seq_to_ids(s) for s in sequences]
    # Filter out too-short sequences
    tokenized = [t for t in tokenized if len(t) >= 4]
    logger.info(f"Tokenized: {len(tokenized)} sequences (filtered short)")

    # Model config — same architecture as other specialists
    d_model = 128
    n_layers = 4
    n_heads = 4
    vocab_size = len(vocab)
    max_len = max(len(t) for t in tokenized)

    logger.info(f"Model: d={d_model}, L={n_layers}, H={n_heads}, vocab={vocab_size}, max_len={max_len}")

    # Simple Transformer model (matching existing specialist architecture)
    class EventTransformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(vocab_size, d_model, padding_idx=0)
            self.pos_embedding = nn.Embedding(max_len + 1, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 4,
                dropout=0.1, batch_first=True
            )
            self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self.fc_out = nn.Linear(d_model, vocab_size)
            self.d_model = d_model

        def forward(self, x):
            B, T = x.shape
            pos = torch.arange(T, device=x.device).unsqueeze(0).expand(B, T)
            emb = self.embedding(x) + self.pos_embedding(pos)
            # Causal mask
            mask = nn.Transformer.generate_square_subsequent_mask(T).to(x.device)
            out = self.transformer(emb, mask=mask)
            logits = self.fc_out(out)
            return logits

    # Dataset
    class SeqDataset(Dataset):
        def __init__(self, sequences, max_len):
            self.sequences = sequences
            self.max_len = max_len

        def __len__(self):
            return len(self.sequences)

        def __getitem__(self, idx):
            seq = self.sequences[idx]
            # Pad to max_len
            padded = seq + [0] * (self.max_len - len(seq))
            x = torch.tensor(padded[:-1], dtype=torch.long)
            y = torch.tensor(padded[1:], dtype=torch.long)
            return x, y

    dataset = SeqDataset(tokenized, max_len)
    loader = DataLoader(dataset, batch_size=32, shuffle=True, drop_last=False)

    # Train
    model = EventTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=20)
    criterion = nn.CrossEntropyLoss(ignore_index=0)

    total_params = sum(p.numel() for p in model.parameters())
    logger.info(f"Parameters: {total_params:,} ({total_params/1e6:.1f}M)")
    logger.info(f"Training: 20 epochs, batch_size=32, lr=1e-3")
    logger.info("")

    best_loss = float("inf")
    start_time = time.time()

    for epoch in range(20):
        model.train()
        total_loss = 0
        batches = 0

        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits.view(-1, vocab_size), y.view(-1))

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            batches += 1

        scheduler.step()
        avg_loss = total_loss / batches
        elapsed = time.time() - start_time

        logger.info(f"  Epoch {epoch+1:2d}/20: loss={avg_loss:.4f} (lr={scheduler.get_last_lr()[0]:.6f}, {elapsed:.0f}s)")

        # Save best
        if avg_loss < best_loss:
            best_loss = avg_loss
            torch.save(model.state_dict(), OUTPUT_DIR / "best_model.pt")

    # Save final
    torch.save(model.state_dict(), OUTPUT_DIR / "final_model.pt")

    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"TRAINING COMPLETE")
    logger.info(f"  Duration: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    logger.info(f"  Final loss: {avg_loss:.4f}")
    logger.info(f"  Best loss: {best_loss:.4f}")
    logger.info(f"  Parameters: {total_params:,}")
    logger.info(f"  Vocab size: {vocab_size}")
    logger.info(f"  Sequences: {len(tokenized)}")
    logger.info(f"  Output: {OUTPUT_DIR}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
