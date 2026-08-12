"""
T1-NLP Evaluation Harness

Runs all models, computes metrics, performs cross-validation, paired t-test,
confusion matrices, and split sweep. Outputs results to experiments/t1-nlp/results/.

Metrics: per-class P/R/F1, macro-F1 (verified), confusion matrix, AUC,
inference latency, 10-fold CV, paired t-test, split sweep 10-90%.

Usage:
    python evaluate.py [--config config.yaml]
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
from torch.utils.data import DataLoader
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score,
    precision_recall_fscore_support, accuracy_score
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from scipy.stats import ttest_rel
import yaml

# Plotting (non-interactive backend)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Local imports
from train import (
    seed_everything, CourseEquivalencyDataset,
    train_epoch, evaluate as eval_model, get_model
)
from embeddings import get_embedding_layer, build_vocab

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics Helpers
# ---------------------------------------------------------------------------

def compute_metrics(true_labels: list, predictions: list, class_names: list) -> dict:
    """Compute per-class and aggregate metrics."""
    precision, recall, f1, support = precision_recall_fscore_support(
        true_labels, predictions, average=None, labels=[0, 1, 2]
    )
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        true_labels, predictions, average="macro"
    )

    # AC-6: Verify macro-F1 identity
    expected_f1 = 2 * macro_p * macro_r / (macro_p + macro_r) if (macro_p + macro_r) > 0 else 0
    assert abs(macro_f1 - expected_f1) < 1e-6, (
        f"Macro-F1 verification failed: {macro_f1} != {expected_f1}"
    )

    acc = accuracy_score(true_labels, predictions)
    cm = confusion_matrix(true_labels, predictions, labels=[0, 1, 2])

    # AUC (one-vs-rest, requires probabilities — use one-hot as proxy)
    try:
        from sklearn.preprocessing import label_binarize
        y_true_bin = label_binarize(true_labels, classes=[0, 1, 2])
        y_pred_bin = label_binarize(predictions, classes=[0, 1, 2])
        auc = roc_auc_score(y_true_bin, y_pred_bin, average="macro", multi_class="ovr")
    except Exception:
        auc = None

    metrics = {
        "accuracy": acc,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f1,
        "macro_f1_verified": True,
        "auc_macro": auc,
        "per_class": {},
        "confusion_matrix": cm.tolist(),
    }

    for i, name in enumerate(class_names):
        metrics["per_class"][name] = {
            "precision": precision[i],
            "recall": recall[i],
            "f1": f1[i],
            "support": int(support[i]) if support is not None else 0,
        }

    return metrics


def plot_confusion_matrix(cm: list, class_names: list, output_path: Path, title: str = ""):
    """Save confusion matrix as heatmap."""
    plt.figure(figsize=(8, 6))
    sns.heatmap(
        np.array(cm), annot=True, fmt="d", cmap="Blues",
        xticklabels=class_names, yticklabels=class_names
    )
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.title(title or "Confusion Matrix")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Cross-Validation
# ---------------------------------------------------------------------------

def run_cross_validation(config: dict, model_name: str, embedding_name: str,
                         texts: list, labels: list, n_folds: int = 10) -> list[float]:
    """
    Run stratified k-fold CV and return per-fold macro-F1 scores.
    """
    seed = config["random_seed"]
    seed_everything(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    uses_bert = model_name in ("bert_dsc_bigru", "bert_head") or embedding_name == "bert"
    training_cfg = config.get("training", {})
    max_len = training_cfg.get("max_seq_length", 128)
    batch_size = training_cfg.get("batch_size", 32)
    epochs = min(training_cfg.get("epochs", 20), 10)  # Cap epochs for CV speed

    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    fold_scores = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(texts, labels)):
        logger.info(f"  Fold {fold + 1}/{n_folds}")
        seed_everything(seed + fold)

        train_texts = [texts[i] for i in train_idx]
        train_labels = [labels[i] for i in train_idx]
        val_texts = [texts[i] for i in val_idx]
        val_labels = [labels[i] for i in val_idx]

        if uses_bert:
            from transformers import BertTokenizer
            tokenizer = BertTokenizer.from_pretrained(
                config.get("bert_model_name", "bert-base-uncased")
            )
            train_ds = CourseEquivalencyDataset(train_texts, train_labels,
                                                tokenizer=tokenizer, max_len=max_len)
            val_ds = CourseEquivalencyDataset(val_texts, val_labels,
                                              tokenizer=tokenizer, max_len=max_len)
        else:
            vocab = build_vocab(train_texts)
            embedding_layer = get_embedding_layer(config, vocab)
            config["embed_dim"] = embedding_layer.embedding_dim
            train_ds = CourseEquivalencyDataset(train_texts, train_labels,
                                                vocab=vocab, max_len=max_len)
            val_ds = CourseEquivalencyDataset(val_texts, val_labels,
                                              vocab=vocab, max_len=max_len)

        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

        # Build model
        model = get_model(model_name, config).to(device)
        if not uses_bert:
            model.embedding = embedding_layer.to(device)

        # Class weights
        class_counts = np.bincount(train_labels, minlength=3)
        class_weights = 1.0 / (class_counts + 1)
        class_weights = class_weights / class_weights.sum() * 3
        criterion = nn.CrossEntropyLoss(
            weight=torch.tensor(class_weights, dtype=torch.float32).to(device)
        )

        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=training_cfg.get("learning_rate", 2e-5),
            weight_decay=training_cfg.get("weight_decay", 0.01),
        )

        # Train
        for ep in range(1, epochs + 1):
            train_epoch(model, train_loader, optimizer, criterion, device, uses_bert)

        # Evaluate
        _, _, preds, true = eval_model(model, val_loader, criterion, device, uses_bert)
        _, _, fold_f1, _ = precision_recall_fscore_support(true, preds, average="macro")
        fold_scores.append(fold_f1)
        logger.info(f"    Fold {fold + 1} F1: {fold_f1:.4f}")

    return fold_scores


# ---------------------------------------------------------------------------
# Split Sweep
# ---------------------------------------------------------------------------

def run_split_sweep(config: dict, model_name: str, embedding_name: str,
                    texts: list, labels: list) -> list[dict]:
    """Sweep train/test split from 10% to 90% in 10% steps."""
    seed = config["random_seed"]
    sweep_results = []
    sweep_cfg = config.get("split_sweep", {"start": 0.1, "stop": 0.9, "step": 0.1})

    ratios = np.arange(
        sweep_cfg["start"], sweep_cfg["stop"] + 0.01, sweep_cfg["step"]
    )

    for ratio in ratios:
        ratio = round(ratio, 2)
        logger.info(f"  Split sweep: train_ratio={ratio}")

        cfg_copy = {**config, "default_split": ratio}
        from train import train_model
        results = train_model(cfg_copy, model_name=model_name, embedding_name=embedding_name)

        metrics = compute_metrics(
            results["true_labels"], results["predictions"],
            ["not_transferable", "partial_or_elective", "direct_equivalent"]
        )

        sweep_results.append({
            "train_ratio": ratio,
            "accuracy": metrics["accuracy"],
            "macro_f1": metrics["macro_f1"],
            "macro_precision": metrics["macro_precision"],
            "macro_recall": metrics["macro_recall"],
        })

    return sweep_results


# ---------------------------------------------------------------------------
# Main Evaluation Pipeline
# ---------------------------------------------------------------------------

def run_evaluation(config: dict):
    """Full evaluation pipeline."""
    seed = config["random_seed"]
    seed_everything(seed)

    results_dir = PROJECT_DIR / config["paths"]["results_dir"]
    results_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    data_path = PROJECT_DIR / config["paths"]["labeled_data"]
    df = pd.read_csv(data_path)
    texts = (df["sending_course_name"] + " [SEP] " + df["receiving_course_name"]).tolist()
    labels = df["label"].tolist()

    class_names = ["not_transferable", "partial_or_elective", "direct_equivalent"]

    # Models to evaluate
    primary_model = "bert_dsc_bigru"
    baselines = ["cnn", "lstm", "cnn_bilstm", "cnn_bigru", "bert_head"]
    all_models = [primary_model] + baselines

    # Default embedding for non-BERT baselines
    default_embed = config.get("embedding", "bert")
    all_results = {}

    # Train and evaluate each model
    for model_name in all_models:
        embed = "bert" if model_name in ("bert_dsc_bigru", "bert_head") else default_embed
        if embed == "bert" and model_name not in ("bert_dsc_bigru", "bert_head"):
            embed = "glove"  # Non-BERT models use static embeddings

        logger.info(f"\n{'='*60}")
        logger.info(f"Training: {model_name} (embedding={embed})")
        logger.info(f"{'='*60}")

        from train import train_model
        results = train_model(config.copy(), model_name=model_name, embedding_name=embed)
        metrics = compute_metrics(results["true_labels"], results["predictions"], class_names)
        metrics["inference_latency_mean_ms"] = results["inference_latency_mean_ms"]
        metrics["inference_latency_std_ms"] = results["inference_latency_std_ms"]
        metrics["model"] = model_name
        metrics["embedding"] = embed

        all_results[model_name] = metrics

        # Confusion matrix plot
        plot_confusion_matrix(
            metrics["confusion_matrix"], class_names,
            results_dir / f"cm_{model_name}.png",
            title=f"Confusion Matrix: {model_name}"
        )

    # Cross-validation on primary model
    logger.info(f"\n{'='*60}")
    logger.info("10-Fold Cross-Validation: primary model")
    logger.info(f"{'='*60}")
    primary_cv_scores = run_cross_validation(
        config.copy(), primary_model, "bert",
        texts, labels, n_folds=config.get("cv_folds", 10)
    )

    # CV on strongest baseline (highest macro-F1)
    best_baseline_name = max(
        baselines, key=lambda m: all_results[m]["macro_f1"]
    )
    logger.info(f"\n10-Fold CV: strongest baseline ({best_baseline_name})")
    baseline_embed = all_results[best_baseline_name]["embedding"]
    baseline_cv_scores = run_cross_validation(
        config.copy(), best_baseline_name, baseline_embed,
        texts, labels, n_folds=config.get("cv_folds", 10)
    )

    # Paired t-test
    t_stat, p_value = ttest_rel(primary_cv_scores, baseline_cv_scores)
    sig_level = config.get("evaluation", {}).get("significance_level", 0.05)
    t_test_result = {
        "primary_model": primary_model,
        "baseline_model": best_baseline_name,
        "primary_cv_scores": primary_cv_scores,
        "baseline_cv_scores": baseline_cv_scores,
        "primary_mean_f1": np.mean(primary_cv_scores),
        "baseline_mean_f1": np.mean(baseline_cv_scores),
        "t_statistic": t_stat,
        "p_value": p_value,
        "significant": p_value < sig_level,
        "significance_level": sig_level,
    }

    # Split sweep on primary model
    logger.info(f"\n{'='*60}")
    logger.info("Split Sweep (10-90%): primary model")
    logger.info(f"{'='*60}")
    sweep_results = run_split_sweep(config.copy(), primary_model, "bert", texts, labels)

    # Save all results
    # Main metrics
    metrics_output = {
        "models": {name: {k: v for k, v in m.items()
                          if not isinstance(v, np.ndarray)}
                   for name, m in all_results.items()},
    }
    with open(results_dir / "metrics.json", "w") as f:
        json.dump(metrics_output, f, indent=2, default=str)

    # T-test
    with open(results_dir / "t_test.json", "w") as f:
        json.dump(t_test_result, f, indent=2, default=str)

    # Split sweep
    sweep_df = pd.DataFrame(sweep_results)
    sweep_df.to_csv(results_dir / "split_sweep.csv", index=False)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("EVALUATION COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Primary model ({primary_model}) macro-F1: "
                f"{all_results[primary_model]['macro_f1']:.4f}")
    logger.info(f"Strongest baseline ({best_baseline_name}) macro-F1: "
                f"{all_results[best_baseline_name]['macro_f1']:.4f}")
    logger.info(f"Paired t-test p-value: {p_value:.6f} "
                f"({'significant' if p_value < sig_level else 'not significant'})")
    logger.info(f"Results saved to: {results_dir}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate T1-NLP models")
    parser.add_argument("--config", type=str, default=str(SCRIPT_DIR / "config.yaml"))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    run_evaluation(config)


if __name__ == "__main__":
    main()
