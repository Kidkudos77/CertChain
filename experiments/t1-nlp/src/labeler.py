"""
T1-NLP Labeler: Derive 3-class labels from raw course equivalency data.

Reads raw JSONL from data/raw/equivalencies.jsonl, applies rules defined in
label_config.yaml, and produces:
  - data/processed/labeled.csv   (labeled dataset for model training)
  - data/processed/exclusions.log (excluded rows with counts and reasons)

No imports from harvester, model, or evaluation code.

Usage:
    python labeler.py [--config label_config.yaml]
"""

import argparse
import csv
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent  # experiments/t1-nlp/

# ---------------------------------------------------------------------------
# Config Loading
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> dict:
    """Load the label derivation config."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Rule Engine
# ---------------------------------------------------------------------------


def evaluate_condition(field_value: str, condition: dict) -> bool:
    """
    Evaluate a single condition against a field value.

    Supported condition types:
      - equals: exact string match
      - regex: re.search match (case-insensitive by default via pattern)
      - is_empty: True/False check
      - contains: substring check (case-insensitive)
    """
    if "equals" in condition:
        return field_value == condition["equals"]

    if "regex" in condition:
        pattern = condition["regex"]
        return bool(re.search(pattern, field_value))

    if "is_empty" in condition:
        expected_empty = condition["is_empty"]
        actual_empty = not field_value.strip()
        return actual_empty == expected_empty

    if "contains" in condition:
        return condition["contains"].lower() in field_value.lower()

    # Unknown condition type — doesn't match
    return False


def apply_rules(record: dict, rules: list[dict]) -> tuple[int | None, str | None]:
    """
    Apply label rules to a record. Returns (label, rule_description) or
    (None, None) if no rule matches.
    """
    for rule in rules:
        label = rule["label"]
        description = rule.get("description", "")
        conditions = rule.get("conditions", {})

        all_match = True
        for field_name, condition in conditions.items():
            field_value = record.get(field_name, "")
            if not evaluate_condition(field_value, condition):
                all_match = False
                break

        if all_match:
            return label, description

    return None, None


# ---------------------------------------------------------------------------
# Main Labeler Logic
# ---------------------------------------------------------------------------


def run_labeler(config_path: Path) -> None:
    """Main labeling pipeline."""
    config = load_config(config_path)
    rules = config["rules"]
    class_names = config["classes"]

    # Paths
    input_path = PROJECT_DIR / "data" / "raw" / "equivalencies.jsonl"
    output_dir = PROJECT_DIR / "data" / "processed"
    output_csv = output_dir / "labeled.csv"
    exclusions_log = output_dir / "exclusions.log"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read raw data
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logging.info(f"Loaded {len(records)} raw records from {input_path}")

    # Apply rules
    labeled_rows = []
    excluded_rows = []

    for i, record in enumerate(records):
        label, rule_desc = apply_rules(record, rules)

        if label is not None:
            labeled_rows.append({
                "sending_institution": record.get("sending_institution", ""),
                "sending_course_code": record.get("sending_course_code", ""),
                "sending_course_name": record.get("sending_course_name", ""),
                "sending_credits": record.get("sending_credits", ""),
                "receiving_institution": record.get("receiving_institution", ""),
                "receiving_course_code": record.get("receiving_course_code", ""),
                "receiving_course_name": record.get("receiving_course_name", ""),
                "credits_transferred": record.get("credits_transferred", ""),
                "note": record.get("note", ""),
                "gen_ed_requirement": record.get("gen_ed_requirement", ""),
                "label": label,
                "label_name": class_names[label],
                "rule_applied": rule_desc,
            })
        else:
            excluded_rows.append({
                "row_index": i,
                "sending_course_code": record.get("sending_course_code", ""),
                "sending_course_name": record.get("sending_course_name", ""),
                "receiving_course_name": record.get("receiving_course_name", ""),
                "credits_transferred": record.get("credits_transferred", ""),
                "receiving_course_code": record.get("receiving_course_code", ""),
                "note": record.get("note", ""),
                "reason": "no matching rule",
            })

    # Write labeled CSV
    if labeled_rows:
        fieldnames = list(labeled_rows[0].keys())
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(labeled_rows)

    # Write exclusions log
    with open(exclusions_log, "w", encoding="utf-8") as f:
        f.write(f"# Exclusions Log — generated {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Total records processed: {len(records)}\n")
        f.write(f"# Records labeled: {len(labeled_rows)}\n")
        f.write(f"# Records excluded: {len(excluded_rows)}\n")
        f.write(f"#\n")
        f.write(f"# Reason summary:\n")

        # Group by reason
        reason_counts: dict[str, int] = {}
        for row in excluded_rows:
            reason = row["reason"]
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            f.write(f"#   {reason}: {count}\n")

        f.write(f"#\n")
        f.write(f"# Detailed exclusions:\n")
        f.write(f"# {'='*70}\n")

        for row in excluded_rows:
            f.write(
                f"row={row['row_index']} | "
                f"send={row['sending_course_code']} ({row['sending_course_name'][:40]}) | "
                f"recv_name={row['receiving_course_name'][:40]} | "
                f"recv_code={row['receiving_course_code'][:20]} | "
                f"credits={row['credits_transferred']} | "
                f"note={row['note'][:30]} | "
                f"reason={row['reason']}\n"
            )

    # Summary
    label_dist = {}
    for row in labeled_rows:
        lbl = row["label_name"]
        label_dist[lbl] = label_dist.get(lbl, 0) + 1

    logging.info("=" * 60)
    logging.info("LABELING COMPLETE")
    logging.info(f"  Total records: {len(records)}")
    logging.info(f"  Labeled: {len(labeled_rows)}")
    logging.info(f"  Excluded: {len(excluded_rows)}")
    logging.info(f"  Label distribution:")
    for name, count in sorted(label_dist.items()):
        pct = 100.0 * count / len(labeled_rows) if labeled_rows else 0
        logging.info(f"    {name}: {count} ({pct:.1f}%)")
    logging.info(f"  Output: {output_csv}")
    logging.info(f"  Exclusions: {exclusions_log}")
    logging.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Label course equivalency data")
    parser.add_argument(
        "--config",
        type=str,
        default=str(SCRIPT_DIR / "label_config.yaml"),
        help="Path to label configuration YAML file",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    run_labeler(config_path)


if __name__ == "__main__":
    main()
