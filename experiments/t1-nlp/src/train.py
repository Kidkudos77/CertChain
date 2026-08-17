"""
T1-NLP Training Script

Reads config.yaml, loads labeled data, trains the specified model, and saves
checkpoints. Seeds everything from config. Supports both BERT-based and
embedding-based models.

Usage:
    python train.py [--config config.yaml] [--model bert_dsc_bigru] [--embedding bert]
"""

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from sklearn.model_selection import train_test_split
import yaml

# Local imports
from models import get_model
from embeddings import (
    get_embedding_layer, build_vocab, tokenize_for_embedding
)

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_everything(seed: int):
    """Seed all random number generators for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class CourseEquivalencyDataset(Dataset):
    """Dataset for course equivalency classification."""

    def __init__(self, texts: list[str], labels: list[int],
                 tokenizer=None, max_len: int = 128,
                 vocab: dict | None = None):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len
        self.vocab = vocab

        # Pre-tokenize if using BERT
        if tokenizer is not None:
            self.encodings = tokenizer(
                texts, truncation=True, padding="max_length",
                max_length=max_len, return_tensors="pt"
            )
        elif vocab is not None:
            self.token_ids = tokenize_for_embedding(texts, vocab, max_len)
        else:
            raise ValueError("Must provide either tokenizer or vocab")

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        label = self.labels[idx]

        if self.tokenizer is not None:
            return {
                "input_ids": self.encodings["input_ids"][idx],
                "attention_mask": self.encodings["attention_mask"][idx],
                "label": torch.tensor(label, dtype=torch.long),
            }
        else:
            return {
                "token_ids": self.token_ids[idx],
                "label": torch.tensor(label, dtype=torch.long),
            }


# ---------------------------------------------------------------------------
# Training Loop
# ---------------------------------------------------------------------------

def train_epoch(model, dataloader, optimizer, criterion, device, uses_bert: bool):
    """Train for one epoch."""
    model.train()
    total_loss = 0
    correct = 0
    total = 0

    for batch in dataloader:
        optimizer.zero_grad()

        if uses_bert:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            logits = model(input_ids=input_ids, attention_mask=attention_mask)
        else:
            token_ids = batch["token_ids"].to(device)
            embeddings = model.embedding(token_ids)  # (batch, seq, dim)
            logits = model(embeddings)

        labels = batch["label"].to(device)
        loss = criterion(logits, labels)

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item() * labels.size(0)
        preds = logits.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return total_loss / total, correct / total


def evaluate(model, dataloader, criterion, device, uses_bert: bool):
    """Evaluate model on a dataset."""
    model.eval()
    total_loss = 0
    correct = 0
    total = 0
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for batch in dataloader:
            if uses_bert:
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                logits = model(input_ids=input_ids, attention_mask=attention_mask)
            else:
                token_ids = batch["token_ids"].to(device)
                embeddings = model.embedding(token_ids)
                logits = model(embeddings)

            labels = batch["label"].to(device)
            loss = criterion(logits, labels)

            total_loss += loss.item() * labels.size(0)
            preds = logits.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    return total_loss / total, correct / total, all_preds, all_labels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def train_model(config: dict, model_name: str | None = None,
                embedding_name: str | None = None) -> dict:
    """
    Full training pipeline. Returns metrics dict.
    """
    seed = config["random_seed"]
    seed_everything(seed)

    # Override model/embedding if specified
    if model_name:
        config["model"] = model_name
    if embedding_name:
        config["embedding"] = embedding_name

    model_key = config["model"]
    embed_key = config["embedding"]
    uses_bert = model_key in ("bert_dsc_bigru", "bert_head") or embed_key == "bert"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Device: {device}")
    logger.info(f"Model: {model_key}, Embedding: {embed_key}")

    # Load data
    data_path = PROJECT_DIR / config["paths"]["labeled_data"]
    df = pd.read_csv(data_path)

    # Build input text: concatenate sending + receiving course names
    texts = (df["sending_course_name"] + " [SEP] " + df["receiving_course_name"]).tolist()
    labels = df["label"].tolist()

    # Train/test split
    split_ratio = config["default_split"]
    train_texts, test_texts, train_labels, test_labels = train_test_split(
        texts, labels, test_size=1 - split_ratio,
        random_state=seed, stratify=labels
    )

    logger.info(f"Train: {len(train_texts)}, Test: {len(test_texts)}")

    # Prepare data
    training_cfg = config.get("training", {})
    max_len = training_cfg.get("max_seq_length", 128)
    batch_size = training_cfg.get("batch_size", 32)

    if uses_bert:
        from transformers import BertTokenizer
        bert_name = config.get("bert_model_name", "bert-base-uncased")
        tokenizer = BertTokenizer.from_pretrained(bert_name)

        train_dataset = CourseEquivalencyDataset(
            train_texts, train_labels, tokenizer=tokenizer, max_len=max_len
        )
        test_dataset = CourseEquivalencyDataset(
            test_texts, test_labels, tokenizer=tokenizer, max_len=max_len
        )
    else:
        # Build vocab from training data
        vocab = build_vocab(train_texts)
        embedding_layer = get_embedding_layer(config, vocab)
        config["embed_dim"] = embedding_layer.embedding_dim

        train_dataset = CourseEquivalencyDataset(
            train_texts, train_labels, vocab=vocab, max_len=max_len
        )
        test_dataset = CourseEquivalencyDataset(
            test_texts, test_labels, vocab=vocab, max_len=max_len
        )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

    # Create model
    model = get_model(model_key, config).to(device)

    # Attach embedding layer for non-BERT models
    if not uses_bert:
        model.embedding = embedding_layer.to(device)

    # Optimizer & loss
    lr = training_cfg.get("learning_rate", 2e-5)
    weight_decay = training_cfg.get("weight_decay", 0.01)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    # Class weights for imbalanced data
    class_counts = np.bincount(train_labels, minlength=3)
    class_weights = 1.0 / (class_counts + 1)
    class_weights = class_weights / class_weights.sum() * 3  # normalize
    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(class_weights, dtype=torch.float32).to(device)
    )

    # Training loop
    epochs = training_cfg.get("epochs", 20)
    patience = training_cfg.get("patience", 5)
    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, epochs + 1):
        train_loss, train_acc = train_epoch(
            model, train_loader, optimizer, criterion, device, uses_bert
        )
        val_loss, val_acc, _, _ = evaluate(
            model, test_loader, criterion, device, uses_bert
        )

        logger.info(
            f"Epoch {epoch}/{epochs} — "
            f"Train Loss: {train_loss:.4f}, Acc: {train_acc:.4f} | "
            f"Val Loss: {val_loss:.4f}, Acc: {val_acc:.4f}"
        )

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            # Save best model
            ckpt_dir = PROJECT_DIR / config["paths"].get("model_checkpoints", "results/checkpoints")
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), ckpt_dir / f"{model_key}_{embed_key}_best.pt")
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info(f"Early stopping at epoch {epoch}")
                break

    # Final evaluation
    _, test_acc, preds, true_labels = evaluate(
        model, test_loader, criterion, device, uses_bert
    )

    # Inference latency
    latency_samples = config.get("evaluation", {}).get("latency_samples", 100)
    model.eval()
    single_batch = next(iter(test_loader))
    times = []
    with torch.no_grad():
        for _ in range(latency_samples):
            start = time.perf_counter()
            if uses_bert:
                model(
                    input_ids=single_batch["input_ids"][:1].to(device),
                    attention_mask=single_batch["attention_mask"][:1].to(device),
                )
            else:
                tid = single_batch["token_ids"][:1].to(device)
                emb = model.embedding(tid)
                model(emb)
            times.append(time.perf_counter() - start)

    results = {
        "model": model_key,
        "embedding": embed_key,
        "test_accuracy": test_acc,
        "predictions": preds,
        "true_labels": true_labels,
        "inference_latency_mean_ms": np.mean(times) * 1000,
        "inference_latency_std_ms": np.std(times) * 1000,
        "best_val_loss": best_val_loss,
        "epochs_trained": epoch,
    }

    return results


def main():
    parser = argparse.ArgumentParser(description="Train T1-NLP models")
    parser.add_argument("--config", type=str, default=str(SCRIPT_DIR / "config.yaml"))
    parser.add_argument("--model", type=str, default=None, help="Override model name")
    parser.add_argument("--embedding", type=str, default=None, help="Override embedding")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    results = train_model(config, model_name=args.model, embedding_name=args.embedding)

    # Save results (without numpy arrays)
    results_dir = PROJECT_DIR / config["paths"]["results_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)

    save_results = {k: v for k, v in results.items()
                    if k not in ("predictions", "true_labels")}
    with open(results_dir / f"train_{results['model']}_{results['embedding']}.json", "w") as f:
        json.dump(save_results, f, indent=2)

    logger.info(f"Test accuracy: {results['test_accuracy']:.4f}")
    logger.info(f"Latency: {results['inference_latency_mean_ms']:.2f} ± "
                f"{results['inference_latency_std_ms']:.2f} ms/record")


if __name__ == "__main__":
    main()
