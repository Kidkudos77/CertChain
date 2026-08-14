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
    logger.info(f"Unique courses loaded: {len(courses)}")

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
                "requirement_id": req_id,
                # label: NOT SET — awaiting human adjudication
            })

    # Write pairs (without labels)
    output_path = PROJECT_DIR / "data" / "processed" / "pairs_unlabeled.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    logger.info(f"Generated {len(pairs)} course-requirement pairs")
    logger.info(f"  ({len(courses)} courses × {len(req_ids_with_prereq)} requirements)")
    logger.info(f"Output: {output_path}")
    logger.info("")
    logger.info("STOP: Labels must be human-supplied before proceeding to evaluation.")
    logger.info("Place labeled pairs in data/labels/ as CSV or JSONL with a 'label' column (0/1).")

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
    """Load unique courses from the JSONL catalog (deduplicated by institution+code)."""
    seen = set()
    courses = []
    with open(catalog_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            key = (record.get("sending_institution", ""),
                   record.get("sending_course_code", ""))
            if key not in seen:
                seen.add(key)
                courses.append({
                    "sending_institution": record.get("sending_institution", ""),
                    "sending_course_code": record.get("sending_course_code", ""),
                    "sending_course_name": record.get("sending_course_name", ""),
                    "sending_credits": record.get("sending_credits", ""),
                })
    return courses


if __name__ == "__main__":
    main()
