"""
Synthetic Student Portfolio Generator (Monte Carlo).

Generates simulated student portfolios by sampling courses from the
MassTransfer CIS catalog. Used ONLY for gate sensitivity analysis.

ALL outputs from this generator are labeled SIMULATED.

Parameters (from config.yaml):
  - n_students: number of synthetic students
  - courses_per_student: swept across [3, 5, 7, 10]
  - gpa_distribution: mean, std, min, max
  - requirement_coverage_rate: swept across [0.4, 0.6, 0.8, 1.0]
  - random_seed: from config

Usage:
    python simulate_students.py
"""

import json
import logging
import random
from pathlib import Path

import numpy as np
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

GRADES = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F"]
GRADE_WEIGHTS = [0.10, 0.08, 0.12, 0.15, 0.10, 0.12, 0.15, 0.08, 0.04, 0.04, 0.02]


def main():
    with open(SCRIPT_DIR / "config.yaml", "r") as f:
        config = yaml.safe_load(f)

    seed = config["random_seed"]
    random.seed(seed)
    np.random.seed(seed)

    sim_cfg = config["simulation"]
    n_students = sim_cfg["n_students"]

    # Load course catalog
    catalog_path = PROJECT_DIR / config["paths"]["course_catalog"]
    if not catalog_path.exists():
        logger.error(f"Catalog not found: {catalog_path}")
        return

    courses = _load_courses(catalog_path)
    logger.info(f"Loaded {len(courses)} unique courses for sampling")

    # Sweep parameters
    courses_sweep = sim_cfg["courses_per_student"]["sweep"]
    coverage_sweep = sim_cfg["requirement_coverage_rate"]["sweep"]
    gpa_mean = sim_cfg["gpa_distribution"]["mean"]
    gpa_std = sim_cfg["gpa_distribution"]["std"]
    gpa_min = sim_cfg["gpa_distribution"]["min"]
    gpa_max = sim_cfg["gpa_distribution"]["max"]

    output_dir = PROJECT_DIR / "data" / "processed" / "simulated_portfolios"
    output_dir.mkdir(parents=True, exist_ok=True)

    for n_courses in courses_sweep:
        for coverage_rate in coverage_sweep:
            portfolios = []
            for i in range(n_students):
                gpa = np.clip(np.random.normal(gpa_mean, gpa_std), gpa_min, gpa_max)
                # Sample courses
                sampled = random.choices(courses, k=n_courses)
                # Assign grades
                course_records = []
                for c in sampled:
                    grade = random.choices(GRADES, weights=GRADE_WEIGHTS, k=1)[0]
                    course_records.append({**c, "grade": grade})

                portfolios.append({
                    "student_id": f"SIM_{n_courses}c_{coverage_rate}r_{i:04d}",
                    "gpa": round(float(gpa), 2),
                    "courses": course_records,
                    "prerequisite_met": random.random() < 0.85,
                    "simulated": True,
                    "parameters": {
                        "courses_per_student": n_courses,
                        "coverage_rate": coverage_rate,
                    },
                })

            # Write
            filename = f"students_c{n_courses}_r{int(coverage_rate*100)}.jsonl"
            output_path = output_dir / filename
            with open(output_path, "w", encoding="utf-8") as f:
                for p in portfolios:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")

            logger.info(f"Generated {n_students} students: courses={n_courses}, "
                        f"coverage={coverage_rate} → {output_path.name}")

    logger.info(f"\nAll portfolios labeled SIMULATED.")
    logger.info(f"Output: {output_dir}/")


def _load_courses(catalog_path: Path) -> list[dict]:
    """Load unique courses from catalog."""
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
