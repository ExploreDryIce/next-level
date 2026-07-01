"""Train Unified Model - Combines ALL domain events into one cross-domain predictor.

This creates a single model that understands patterns across all domains,
enabling cross-domain cascade prediction (weather -> logistics -> financial).

Run on TerrorNode:
    C:/Python311/python.exe train_unified_model.py

Training data sources:
    - E:/dvce-data/training/all_sequences_latest.json (all domains combined)
    - E:/dvce-data/training/political_market_sequences.json
    - E:/dvce-data/training/tweet_training_sequences.json
    - E:/dvce-data/training/historical_political_sequences.json

Output:
    E:/dvce-data/models/unified_v4/best_model.pt
    E:/dvce-data/models/unified_v4/final_model.pt
    E:/dvce-data/models/unified_v4/vocab.json
"""

import json
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TRAINING_DIR = Path("E:/dvce-data/training")
OUTPUT_DIR = Path("E:/dvce-data/models/unified_v4")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, "C:/Users/jwebb/dvce-server")
sys.path.insert(0, "C:/Users/jwebb/dvce-server/src")


def load_all_sequences():
    """Load ALL training sequences across every domain."""
    all_sequences = []

    # Main combined sequences (weather, financial, geo, cyber, grid)
    path = TRAINING_DIR / "all_sequences_latest.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        if isinstance(seqs, list):
            all_sequences.extend(seqs)
            logger.info(f"  all_sequences_latest: {len(seqs)} sequences")

    # Political/market
    path = TRAINING_DIR / "political_market_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        if isinstance(seqs, list):
            all_sequences.extend(seqs)
            logger.info(f"  political_market_sequences: {len(seqs)} sequences")

    # Tweet sequences
    path = TRAINING_DIR / "tweet_training_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        if isinstance(seqs, list):
            all_sequences.extend(seqs)
            logger.info(f"  tweet_training_sequences: {len(seqs)} sequences")

    # Historical political
    path = TRAINING_DIR / "historical_political_sequences.json"
    if path.exists():
        data = json.loads(path.read_text())
        seqs = data.get("sequences", data) if isinstance(data, dict) else data
        if isinstance(seqs, list):
            all_sequences.extend(seqs)
            logger.info(f"  historical_political_sequences: {len(seqs)} sequences")

    return all_sequences


def build_vocab(sequences):
    """Build unified vocabulary from all event types."""
    event_types = set()
    for seq in sequences:
        for event in seq:
            if isinstance(event, dict):
                et = event.get("event_type", event.get("type", "unknown"))
            else:
                et = str(event)
            event_types.add(et)

    vocab = {"<PAD>": 0, "<UNK>": 1, "<BOS>": 2, "<EOS>": 3}
    for i, et in enumerate(sorted(event_types), start=4):
        vocab[et] = i
    return vocab


def main():
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader

    logger.info("=" * 60)
    logger.info("UNIFIED MODEL TRAINING — ALL DOMAINS — TerrorNode CUDA")
    logger.info("=" * 60)
    logger.info(f"PyTorch: {torch.__version__}")
    logger.info(f"CUDA: {torch.cuda.is_available()} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'})")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Load data
    logger.info("Loading ALL training data...")
    sequences = load_all_sequences()
    logger.info(f"Total: {len(sequences)} sequences across all domains")

    if not sequences:
        logger.error("No training data found!")
        return

    # Build vocab
    vocab = build_vocab(sequences)
    logger.info(f"Unified vocabulary: {len(vocab)} event types")
    (OUTPUT_DIR / "vocab.json").write_text(json.dumps(vocab, indent=2))

    # Tokenize
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
    tokenized = [t for t in tokenized if len(t) >= 4]
    logger.info(f"Tokenized: {len(tokenized)} sequences (filtered short)")

    # Larger model for unified (handles more event types)
    d_model = 256
    n_layers = 8
    n_heads = 8
    vocab_size = len(vocab)
    max_len = min(max(len(t) for t in tokenized), 512)  # Cap at 512

    # Truncate long sequences
    tokenized = [t[:max_len] for t in tokenized]

    logger.info(f"Model: d={d_model}, L={n_layers}, H={n_heads}, vocab={vocab_size}, max_len={max_len}")

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
            mask = nn.Transformer.generate_square_subsequent_mask(T).to(x.device)
            out = self.transformer(emb, mask=mask)
            logits = self.fc_out(out)
            return logits

    class SeqDataset(Dataset):
        def __init__(self, sequences, max_len):
            self.sequences = sequences
            self.max_len = max_len

        def __len__(self):
            return len(self.sequences)

        def __getitem__(self, idx):
            seq = self.sequences[idx]
            padded = seq + [0] * (self.max_len - len(seq))
            x = torch.tensor(padded[:-1], dtype=torch.long)
            y = torch.tensor(padded[1:], dtype=torch.long)
            return x, y

    dataset = SeqDataset(tokenized, max_len)
    loader = DataLoader(dataset, batch_size=16, shuffle=True, drop_last=False)

    model = EventTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=25)
    criterion = nn.CrossEntropyLoss(ignore_index=0)

    total_params = sum(p.numel() for p in model.parameters())
    logger.info(f"Parameters: {total_params:,} ({total_params/1e6:.1f}M)")
    logger.info(f"Training: 25 epochs, batch_size=16, lr=5e-4")
    logger.info("")

    best_loss = float("inf")
    start_time = time.time()

    for epoch in range(25):
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

        logger.info(f"  Epoch {epoch+1:2d}/25: loss={avg_loss:.4f} (lr={scheduler.get_last_lr()[0]:.6f}, {elapsed:.0f}s)")

        if avg_loss < best_loss:
            best_loss = avg_loss
            torch.save(model.state_dict(), OUTPUT_DIR / "best_model.pt")

    torch.save(model.state_dict(), OUTPUT_DIR / "final_model.pt")

    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"UNIFIED TRAINING COMPLETE")
    logger.info(f"  Duration: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    logger.info(f"  Final loss: {avg_loss:.4f}")
    logger.info(f"  Best loss: {best_loss:.4f}")
    logger.info(f"  Parameters: {total_params:,}")
    logger.info(f"  Vocab size: {vocab_size}")
    logger.info(f"  Sequences: {len(tokenized)} (all domains)")
    logger.info(f"  Output: {OUTPUT_DIR}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
