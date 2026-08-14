"""
Compute intra-rater reliability (Cohen's kappa) between two labeling passes.

Expects:
  data/labels/test_set_pass1.csv — 600 pairs, full first pass
  data/labels/test_set_pass2.csv — 240 pairs, retest subsample (≥7 days later)

Reports kappa overall and per requirement (R1–R5).

Usage:
    python compute_kappa.py
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

REQUIREMENTS = ["R1", "R2", "R3", "R4", "R5"]


def main():
    labels_dir = PROJECT_DIR / "data" / "labels"
    pass1_path = labels_dir / "test_set_pass1.csv"
    pass2_path = labels_dir / "test_set_pass2.csv"

    if not pass1_path.exists():
        logger.error(f"Pass 1 labels not found: {pass1_path}")
        sys.exit(1)
    if not pass2_path.exists():
        logger.error(f"Pass 2 labels not found: {pass2_path}")
        sys.exit(1)

    # Load both passes
    pass1 = pd.read_csv(pass1_path)
    pass2 = pd.read_csv(pass2_path)

    logger.info(f"Pass 1: {len(pass1)} labeled pairs")
    logger.info(f"Pass 2: {len(pass2)} labeled pairs (retest subsample)")

    # Merge on the pair key to find overlap
    key_cols = ["sending_institution", "sending_course_code", "requirement_id"]
    merged = pass1.merge(pass2, on=key_cols, suffixes=("_pass1", "_pass2"))

    logger.info(f"Overlapping pairs: {len(merged)}")

    if len(merged) == 0:
        logger.error("No overlapping pairs found between Pass 1 and Pass 2.")
        logger.error("Ensure both files use the same key columns.")
        sys.exit(1)

    # Overall kappa
    labels_1 = merged["label_pass1"].values
    labels_2 = merged["label_pass2"].values
    overall_kappa = cohen_kappa_score(labels_1, labels_2)

    logger.info(f"\n{'='*60}")
    logger.info(f"INTRA-RATER RELIABILITY (Cohen's Kappa)")
    logger.info(f"{'='*60}")
    logger.info(f"  Overall kappa: {overall_kappa:.4f}")
    logger.info(f"  Agreement:     {(labels_1 == labels_2).mean():.4f}")
    logger.info(f"  N pairs:       {len(merged)}")

    # Interpretation
    if overall_kappa >= 0.81:
        interp = "almost perfect"
    elif overall_kappa >= 0.61:
        interp = "substantial"
    elif overall_kappa >= 0.41:
        interp = "moderate"
    elif overall_kappa >= 0.21:
        interp = "fair"
    else:
        interp = "slight/poor"
    logger.info(f"  Interpretation: {interp}")

    if overall_kappa < 0.61:
        logger.warning("  ⚠ Kappa < 0.61: rubric may need revision before proceeding.")

    # Per-requirement kappa
    logger.info(f"\n  Per-requirement kappa:")
    per_req_kappa = {}
    for req_id in REQUIREMENTS:
        subset = merged[merged["requirement_id"] == req_id]
        if len(subset) < 5:
            logger.info(f"    {req_id}: insufficient pairs ({len(subset)})")
            per_req_kappa[req_id] = None
            continue
        k = cohen_kappa_score(subset["label_pass1"], subset["label_pass2"])
        n = len(subset)
        agree = (subset["label_pass1"] == subset["label_pass2"]).mean()
        per_req_kappa[req_id] = float(k)
        logger.info(f"    {req_id}: kappa={k:.4f}, agreement={agree:.4f}, n={n}")

    # Disagreement analysis
    disagreements = merged[merged["label_pass1"] != merged["label_pass2"]]
    logger.info(f"\n  Disagreements: {len(disagreements)}/{len(merged)} "
                f"({len(disagreements)/len(merged)*100:.1f}%)")
    if len(disagreements) > 0:
        logger.info(f"  Disagreement by requirement:")
        for req_id in REQUIREMENTS:
            n_dis = len(disagreements[disagreements["requirement_id"] == req_id])
            n_total = len(merged[merged["requirement_id"] == req_id])
            if n_total > 0:
                logger.info(f"    {req_id}: {n_dis}/{n_total} ({n_dis/n_total*100:.1f}%)")

    # Save results
    results = {
        "intra_rater_reliability": {
            "method": "test-retest, single labeler, ≥7 day gap",
            "overall_kappa": float(overall_kappa),
            "overall_agreement": float((labels_1 == labels_2).mean()),
            "n_overlap_pairs": int(len(merged)),
            "n_pass1_total": int(len(pass1)),
            "n_pass2_subsample": int(len(pass2)),
            "interpretation": interp,
            "per_requirement_kappa": per_req_kappa,
            "n_disagreements": int(len(disagreements)),
        },
    }

    results_dir = PROJECT_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "intra_rater_kappa.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
