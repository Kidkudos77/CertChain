"""
Prepare course-requirement pairs from MassTransfer CIS catalog.

Generates all (course, requirement) combinations for cascade evaluation.
Does NOT generate labels — those must be human-supplied.

Usage:
    python prepare_pairs.py
"""

import hashlib
import json
import logging
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def main():
    # Load config
    with open(SCRIPT_DIR / "config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Load requirements
    with open(PROJECT_DIR / config["paths"]["requirements"], "r") as f:
        requirements = yaml.safe_load(f)

    # Hash requirements.yaml for manifest
    req_bytes = (PROJECT_DIR / config["paths"]["requirements"]).read_bytes()
    req_hash = hashlib.sha256(req_bytes).hexdigest()
    logger.info(f"requirements.yaml SHA-256: {req_hash}")

    # Load unique courses from catalog
    catalog_path = PROJECT_DIR / config["paths"]["course_catalog"]
    if not catalog_path.exists():
        logger.error(f"Catalog not found: {catalog_path}")
        logger.info("Copy MassTransfer CIS catalog to data/raw/equivalencies.jsonl first.")
        return

    courses = _load_unique_courses(catalog_path)

    # Exclude combined/bundled course entries (contain '/' in the code after dept prefix)
    # e.g. "CIS 228/244/247" is three courses bundled, not a single course.
    # Rule: a code with '/' after the numeric portion indicates a combined entry.
    import re
    combined = [c for c in courses if re.search(r"\d+/", c["sending_course_code"])]
    courses = [c for c in courses if not re.search(r"\d+/", c["sending_course_code"])]
    if combined:
        logger.info(f"Excluded {len(combined)} combined/bundled course entries:")
        for c in combined:
            logger.info(f"  {c['sending_institution']} / {c['sending_course_code']}: {c['sending_course_name']}")

    logger.info(f"Unique courses loaded: {len(courses)} (after dedup and exclusions)")

    # Generate all pairs
    req_ids = [r["id"] for r in requirements["requirements"]]
    # Include prerequisite as a separate check
    req_ids_with_prereq = req_ids + ["prerequisite"]

    pairs = []
    for course in courses:
        for req_id in req_ids_with_prereq:
            pairs.append({
                "sending_institution": course["sending_institution"],
                "sending_course_code": course["sending_course_code"],
                "sending_course_name": course["sending_course_name"],
                "sending_credits": course["sending_credits"],
                "status": course["status"],
                "requirement_id": req_id,
            })

    # Write all pairs (unlabeled, for reference)
    output_path = PROJECT_DIR / "data" / "processed" / "pairs_unlabeled.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    logger.info(f"Generated {len(pairs)} total course-requirement pairs")
    logger.info(f"  ({len(courses)} courses × {len(req_ids_with_prereq)} requirements)")

    # Option B: label ALL courses. No train/test split — method requires no training data.
    # Threshold selection via leave-one-course-out. Entire labeled set is evaluation.
    import random
    labeling_cfg = config.get("labeling", {})
    shuffle_seed = labeling_cfg.get("shuffle_seed_pass1", 42)
    random.seed(shuffle_seed)

    sampled_courses = courses  # ALL courses, no sampling

    # Generate complete blocks: every course × all 6 targets
    test_pairs = []
    for course in sampled_courses:
        for req_id in req_ids_with_prereq:
            test_pairs.append({
                "sending_institution": course["sending_institution"],
                "sending_course_code": course["sending_course_code"],
                "sending_course_name": course["sending_course_name"],
                "sending_credits": course["sending_credits"],
                "status": course["status"],
                "requirement_id": req_id,
            })

    # Shuffle the pair order (not grouped by course during labeling)
    random.shuffle(test_pairs)

    logger.info(f"\nTest set: {len(sampled_courses)} courses × {len(req_ids_with_prereq)} targets = {len(test_pairs)} pairs")
    logger.info(f"  (Complete pool — no sampling, no train/test split)")

    # Write test set template (CSV for labeling)
    import csv
    test_csv_path = PROJECT_DIR / "data" / "labels" / "test_set_template.csv"
    test_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sending_institution", "sending_course_code", "sending_course_name",
                  "sending_credits", "status", "requirement_id", "label"]
    with open(test_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pair in test_pairs:
            writer.writerow({**pair, "label": ""})  # label blank for human to fill

    logger.info(f"Test set template: {test_csv_path}")
    logger.info(f"  {len(test_pairs)} pairs to label (seed={shuffle_seed})")
    logger.info(f"  Structure: {len(sampled_courses)} courses × 6 targets (complete blocks)")

    # Also write directly as test_set_pass1.csv (ready to label)
    pass1_path = PROJECT_DIR / "data" / "labels" / "test_set_pass1.csv"
    import shutil
    shutil.copy2(test_csv_path, pass1_path)
    logger.info(f"  Copied to: {pass1_path} (fill 'label' column, log date when done)")
    logger.info(f"Output: {output_path}")
    logger.info("")
    logger.info("STOP: Labels must be human-supplied before proceeding to evaluation.")
    logger.info("Place labeled pairs in data/labels/test_set_pass1.csv.")

    # Write manifest stub
    manifest = {
        "requirements_yaml_sha256": req_hash,
        "n_unique_courses": len(courses),
        "n_requirements": len(req_ids_with_prereq),
        "n_pairs": len(pairs),
        "labels_supplied": False,
        "status": "BLOCKED — awaiting human labels",
    }
    manifest_path = PROJECT_DIR / "results" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Manifest: {manifest_path}")


def _load_unique_courses(catalog_path: Path) -> list[dict]:
    """Load unique courses from the JSONL catalog (deduplicated by institution+base_code)."""
    import re
    seen = set()
    courses = []
    with open(catalog_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            raw_code = record.get("sending_course_code", "")
            # Strip status suffixes: #(Replaced: ...), #(Disc'd: ...)
            base_code, status = _parse_code_status(raw_code)
            institution = record.get("sending_institution", "")
            key = (institution, base_code)
            if key not in seen:
                seen.add(key)
                name = record.get("sending_course_name", "")
                name = _canonicalize_name(name)
                courses.append({
                    "sending_institution": institution,
                    "sending_course_code": base_code,
                    "sending_course_code_raw": raw_code,
                    "sending_course_name": name,
                    "sending_credits": record.get("sending_credits", ""),
                    "status": status,
                })
    return courses


def _parse_code_status(raw_code: str) -> tuple[str, str]:
    """
    Split a course code into base code and status flag.

    Examples:
      "CIS 110" -> ("CIS 110", "active")
      "CIS 110#(Replaced: 7/1/2024)" -> ("CIS 110", "replaced")
      "CIS 225#(Disc'd: 3/16/2026)" -> ("CIS 225", "discontinued")
    """
    import re
    match = re.search(r"#\(", raw_code)
    if not match:
        return raw_code.strip(), "active"
    base = raw_code[:match.start()].strip()
    suffix = raw_code[match.start():].lower()
    if "replaced" in suffix:
        status = "replaced"
    elif "disc" in suffix:
        status = "discontinued"
    else:
        status = "inactive"
    return base, status


def _canonicalize_name(name: str) -> str:
    """
    Canonicalize course name by removing rendering artifacts.

    Rule: truncate at the first occurrence of known artifact patterns.
    These are HTML table concatenation artifacts from the harvester where
    course notes or subsequent columns were appended to the name field.
    """
    import re
    # Patterns that signal start of concatenation junk
    artifact_patterns = [
        r"This course",
        r"Students may",
        r"Special Requirement",
        r"\d+-[A-Z]",  # e.g. "3-Bridgewater" (credits-institution)
    ]
    for pattern in artifact_patterns:
        match = re.search(pattern, name)
        if match:
            name = name[:match.start()]
    return name.strip()


if __name__ == "__main__":
    main()
