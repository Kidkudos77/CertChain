"""
Compute intra-rater reliability between two labeling passes.

Reports:
  - Raw agreement percentage
  - Cohen's kappa (with known prevalence instability caveat)
  - PABAK (Prevalence-Adjusted Bias-Adjusted Kappa)
  - 2×2 marginal table per requirement
  - Disagreement count and breakdown

Pass 1 is the FINAL label set. Pass 2 exists ONLY to measure reliability.
Disagreements are reported as measured noise, never repaired.

Integrity check: refuses to proceed if test_set_pass1.csv was modified
after its recorded completion timestamp in config.yaml.

Usage:
    python compute_kappa.py
"""

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, confusion_matrix
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

REQUIREMENTS = ["R1", "R2", "R3", "R4", "R5"]


def pabak(labels_1, labels_2):
    """
    Prevalence-Adjusted Bias-Adjusted Kappa.
    PABAK = 2 * p_o - 1, where p_o is observed agreement.
    Removes the effect of prevalence and bias on kappa.
    """
    agreement = np.mean(np.array(labels_1) == np.array(labels_2))
    return 2 * agreement - 1


def marginal_table(labels_1, labels_2):
    """Compute 2×2 table: [[both_0, 1_says_1], [1_says_0, both_1]]."""
    cm = confusion_matrix(labels_1, labels_2, labels=[0, 1])
    return cm.tolist()


def main():
    # Load config
    with open(SCRIPT_DIR / "config.yaml", "r") as f:
        config = yaml.safe_load(f)

    labels_dir = PROJECT_DIR / "data" / "labels"
    pass1_path = labels_dir / "test_set_pass1.csv"
    pass2_path = labels_dir / "test_set_pass2.csv"

    # --- Integrity check ---
    if not pass1_path.exists():
        logger.error(f"Pass 1 labels not found: {pass1_path}")
        sys.exit(1)

    labeling_cfg = config.get("labeling", {})
    pass1_dates = labeling_cfg.get("pass1_dates", [])
    if pass1_dates:
        # Check that pass1 file was not modified after the last recorded pass1 date
        pass1_mtime = os.path.getmtime(pass1_path)
        from datetime import datetime
        last_pass1_date = max(pass1_dates)
        # Add 24h buffer (end of day)
        cutoff = datetime.strptime(last_pass1_date, "%Y-%m-%d").timestamp() + 86400 * 2
        if pass1_mtime > cutoff:
            logger.error("=" * 60)
            logger.error("INTEGRITY VIOLATION")
            logger.error(f"test_set_pass1.csv was modified after its recorded")
            logger.error(f"completion date ({last_pass1_date}).")
            logger.error(f"File mtime: {datetime.fromtimestamp(pass1_mtime).isoformat()}")
            logger.error("")
            logger.error("Pass 1 must not be opened or modified during Pass 2.")
            logger.error("If Pass 1 labels were changed, both passes are void")
            logger.error("and all 600 pairs must be relabeled from scratch.")
            logger.error("=" * 60)
            sys.exit(2)

    if not pass2_path.exists():
        logger.error(f"Pass 2 labels not found: {pass2_path}")
        logger.error("Complete Pass 2 (≥7 days after Pass 1) before running this script.")
        sys.exit(1)

    # --- Load data ---
    pass1 = pd.read_csv(pass1_path)
    pass2 = pd.read_csv(pass2_path)

    logger.info(f"Pass 1: {len(pass1)} labeled pairs")
    logger.info(f"Pass 2: {len(pass2)} labeled pairs (retest subsample)")

    # --- Verify gap ---
    pass2_dates = labeling_cfg.get("pass2_dates", [])
    if pass1_dates and pass2_dates:
        from datetime import datetime
        last_p1 = datetime.strptime(max(pass1_dates), "%Y-%m-%d")
        first_p2 = datetime.strptime(min(pass2_dates), "%Y-%m-%d")
        gap_days = (first_p2 - last_p1).days
        logger.info(f"Gap between passes: {gap_days} days")
        if gap_days < 7:
            logger.warning(f"  ⚠ Gap is {gap_days} days, minimum recommended is 7.")

    # --- Merge on pair key ---
    key_cols = ["sending_institution", "sending_course_code", "requirement_id"]
    merged = pass1.merge(pass2, on=key_cols, suffixes=("_pass1", "_pass2"))

    logger.info(f"Overlapping pairs: {len(merged)}")
    if len(merged) == 0:
        logger.error("No overlapping pairs found.")
        sys.exit(1)

    labels_1 = merged["label_pass1"].values
    labels_2 = merged["label_pass2"].values

    # --- Overall metrics ---
    raw_agree = float(np.mean(labels_1 == labels_2))
    kappa = float(cohen_kappa_score(labels_1, labels_2))
    pabak_val = float(pabak(labels_1, labels_2))
    overall_marginals = marginal_table(labels_1, labels_2)

    # Prevalence index: |p(yes) - p(no)| / n
    p_yes = np.mean(labels_1)
    prevalence_index = abs(2 * p_yes - 1)

    logger.info(f"\n{'='*60}")
    logger.info(f"INTRA-RATER RELIABILITY")
    logger.info(f"{'='*60}")
    logger.info(f"  Method:          test-retest, single labeler, ≥7 day gap")
    logger.info(f"  N overlap:       {len(merged)}")
    logger.info(f"  Positive rate:   {p_yes:.3f} (prevalence index: {prevalence_index:.3f})")
    logger.info(f"  Raw agreement:   {raw_agree:.4f} ({raw_agree*100:.1f}%)")
    logger.info(f"  Cohen's kappa:   {kappa:.4f}")
    logger.info(f"  PABAK:           {pabak_val:.4f}")
    logger.info(f"  2×2 marginals:   {overall_marginals}")
    logger.info(f"")

    # Interpretation — using all three metrics together
    if raw_agree >= 0.90 and kappa < 0.61 and prevalence_index > 0.80:
        interp = ("high agreement, low kappa due to prevalence skew — "
                  "rubric is consistent, kappa is deflated by marginal imbalance")
    elif kappa >= 0.81:
        interp = "almost perfect agreement"
    elif kappa >= 0.61:
        interp = "substantial agreement"
    elif kappa >= 0.41:
        interp = "moderate agreement"
    elif raw_agree >= 0.85:
        interp = "high raw agreement despite low kappa (likely prevalence effect)"
    else:
        interp = "poor agreement — rubric revision required"
    logger.info(f"  Interpretation:  {interp}")

    if "rubric revision required" in interp:
        logger.warning("")
        logger.warning("  ⚠ FAILURE PATH: Both passes are void.")
        logger.warning("  All 600 pairs must be relabeled under a revised rubric.")
        logger.warning("  Labels from two rubric versions must NEVER be mixed.")

    # --- Per-requirement metrics ---
    logger.info(f"\n  Per-requirement breakdown:")
    per_req = {}
    for req_id in REQUIREMENTS:
        subset = merged[merged["requirement_id"] == req_id]
        if len(subset) < 3:
            logger.info(f"    {req_id}: insufficient pairs ({len(subset)})")
            per_req[req_id] = {"n": int(len(subset)), "note": "insufficient"}
            continue

        l1 = subset["label_pass1"].values
        l2 = subset["label_pass2"].values
        n = len(subset)
        agree = float(np.mean(l1 == l2))
        p_pos = float(np.mean(l1))
        prev_idx = abs(2 * p_pos - 1)

        # Kappa can fail if one column is constant
        try:
            k = float(cohen_kappa_score(l1, l2))
        except Exception:
            k = None

        pk = float(pabak(l1, l2))
        marg = marginal_table(l1, l2)

        per_req[req_id] = {
            "n": n,
            "positive_rate": p_pos,
            "prevalence_index": prev_idx,
            "raw_agreement": agree,
            "kappa": k,
            "pabak": pk,
            "marginal_table": marg,
        }
        logger.info(f"    {req_id}: n={n}, pos_rate={p_pos:.2f}, "
                    f"agree={agree:.3f}, kappa={k:.3f if k else 'N/A'}, "
                    f"PABAK={pk:.3f}")

    # --- Disagreement analysis ---
    disagreements = merged[merged["label_pass1"] != merged["label_pass2"]]
    logger.info(f"\n  Total disagreements: {len(disagreements)}/{len(merged)} "
                f"({len(disagreements)/len(merged)*100:.1f}%)")
    logger.info(f"  NOTE: Disagreements are measured noise. Pass 1 labels are final.")
    logger.info(f"        These are NOT repaired.")

    # --- Save results ---
    results = {
        "intra_rater_reliability": {
            "method": "test-retest, single labeler, ≥7 day gap",
            "pass1_is_final": True,
            "pass2_is_measurement_only": True,
            "disagreements_repaired": False,
            "overall": {
                "n_overlap_pairs": int(len(merged)),
                "positive_rate": float(p_yes),
                "prevalence_index": float(prevalence_index),
                "raw_agreement": raw_agree,
                "cohens_kappa": kappa,
                "pabak": pabak_val,
                "marginal_table_2x2": overall_marginals,
                "interpretation": interp,
            },
            "per_requirement": per_req,
            "n_disagreements": int(len(disagreements)),
            "n_pass1_total": int(len(pass1)),
            "n_pass2_subsample": int(len(pass2)),
        },
    }

    # Add dates if available
    if pass1_dates:
        results["intra_rater_reliability"]["pass1_dates"] = pass1_dates
    if pass2_dates:
        results["intra_rater_reliability"]["pass2_dates"] = pass2_dates
        if pass1_dates:
            results["intra_rater_reliability"]["gap_days"] = gap_days

    results_dir = PROJECT_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "intra_rater_kappa.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
