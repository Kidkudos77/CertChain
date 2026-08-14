"""
CertChain Eligibility — Evaluation Harness (STUB)

BLOCKED: Requires human-labeled ground truth in data/labels/ before execution.

When labels are available, this script will:
1. Run the cascade on all labeled pairs
2. Report cascade resolution rates, per-stage latency, call counts
3. Evaluate BERT classifier on Stage 3 residual only (GroupKFold, TF-IDF floor)
4. Report per-requirement metrics (R1-R5)
5. Report tier distributions, gate accuracy (0 vs >=1 Tier C)
6. Run sensitivity analysis (SIMULATED)

Usage:
    python evaluate.py
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def main():
    # Check for labels
    labels_dir = PROJECT_DIR / "data" / "labels"
    if not labels_dir.exists() or not any(labels_dir.iterdir()):
        print("=" * 60)
        print("BLOCKED: Human-labeled ground truth not found.")
        print(f"Expected: {labels_dir}/")
        print("")
        print("Place labeled course-requirement pairs in data/labels/")
        print("as CSV or JSONL with columns:")
        print("  sending_institution, sending_course_code, sending_course_name,")
        print("  sending_credits, requirement_id, label (0 or 1)")
        print("")
        print("Do not synthesize labels. Do not proceed without human adjudication.")
        print("=" * 60)
        sys.exit(1)

    # TODO: Implement evaluation pipeline when labels are supplied.
    # See .kiro/specs/certchain-eligibility/tasks.md Phase 2.
    print("Labels found. Evaluation pipeline not yet implemented.")
    print("Proceed with Phase 2 tasks.")


if __name__ == "__main__":
    main()
