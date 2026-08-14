"""
Train BERT binary classifier for Stage 3 course-requirement matching.

BLOCKED: Requires human-labeled ground truth in data/labels/ before execution.

When labels are available, this script will:
1. Load labeled course-requirement pairs (Stage 3 residual only)
2. Train a binary BERT classifier (satisfies requirement: yes/no)
3. Evaluate with GroupKFold on (granting_institution, course_code)
4. Include TF-IDF + LR floor baseline
5. Report per-class P/R/F1, confusion matrix, latency

Input format (per pair):
  sending_course_name | sending_course_code | sending_credits | requirement_name

Output: confidence in [0, 1] that the course satisfies the requirement.

Usage:
    python train_bert.py
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def main():
    labels_dir = PROJECT_DIR / "data" / "labels"
    if not labels_dir.exists() or not any(labels_dir.iterdir()):
        print("=" * 60)
        print("BLOCKED: Human-labeled ground truth not found.")
        print(f"Expected: {labels_dir}/")
        print("")
        print("Cannot train classifier without labeled data.")
        print("Do not synthesize labels.")
        print("=" * 60)
        sys.exit(1)

    # TODO: Implement training pipeline when labels are supplied.
    # See .kiro/specs/certchain-eligibility/tasks.md Phase 2.
    print("Labels found. Training pipeline not yet implemented.")


if __name__ == "__main__":
    main()
