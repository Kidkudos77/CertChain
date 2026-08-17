"""
Eligibility Gate — Pure Function (off-chain harness).

Computes the eligibility decision the on-chain gate would return.
No Fabric or Solidity dependencies.

Gate logic (conjunctive):
    eligible = prerequisite_met
               AND all 5 requirements matched
               AND every matched course has grade >= C

Per-requirement Tier C acceptance:
    accept = 0.40×GPA + 0.40×course_completion + 0.20×conf >= 0.70

    where:
      - course_completion = fraction of requirements satisfied at Tier A or B
      - conf = classifier confidence for this specific course-requirement pair
      - GPA, weights, threshold are configurable

BERT_confidence (aggregated per student):
    (1/|R|) * sum_r max_c conf(c, r)
"""

from dataclasses import dataclass
from typing import Optional


GRADE_ORDER = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
               "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0,
               "D-": 0.7, "F": 0.0}

MINIMUM_GRADE_VALUE = GRADE_ORDER["C"]  # 2.0


@dataclass
class GateInput:
    """Input to the eligibility gate for one student."""
    student_id: str
    gpa: float
    prerequisite_met: bool
    # Per-requirement: list of (requirement_id, tier, confidence, grade)
    requirement_matches: list[dict]
    # dict keys: requirement_id, tier ("A","B","C"), confidence (float), grade (str)


@dataclass
class GateResult:
    """Output of the eligibility gate."""
    student_id: str
    eligible: bool
    reasons: list[str]
    tier_distribution: dict  # {"A": n, "B": n, "C": n, "unmet": n}
    course_completion: float  # fraction at Tier A or B
    bert_confidence: float    # aggregated BERT confidence
    per_requirement: dict     # {req_id: {tier, accepted, reason}}
    simulated: bool = True    # Always True in this harness


def compute_eligibility(
    gate_input: GateInput,
    config: dict,
    requirement_ids: list[str] = None,
) -> GateResult:
    """
    Compute the eligibility decision.

    Args:
        gate_input: Student data with matched requirements.
        config: Gate configuration (weights, threshold).
        requirement_ids: List of requirement IDs (default R1-R5).
    """
    if requirement_ids is None:
        requirement_ids = ["R1", "R2", "R3", "R4", "R5"]

    gate_cfg = config.get("gate", {})
    gpa_weight = gate_cfg.get("default_gpa_weight", 0.40)
    completion_weight = gate_cfg.get("default_completion_weight", 0.40)
    bert_weight = gate_cfg.get("default_bert_weight", 0.20)
    threshold = gate_cfg.get("default_threshold", 0.70)

    reasons = []
    per_req = {}
    tier_dist = {"A": 0, "B": 0, "C": 0, "unmet": 0}

    # Check prerequisite
    if not gate_input.prerequisite_met:
        reasons.append("Prerequisite not met")

    # Build lookup: req_id -> best match (highest tier, then highest confidence)
    best_matches = {}
    for match in gate_input.requirement_matches:
        req_id = match["requirement_id"]
        if req_id not in best_matches:
            best_matches[req_id] = match
        else:
            # Prefer higher tier (A > B > C), then higher confidence
            existing = best_matches[req_id]
            tier_rank = {"A": 3, "B": 2, "C": 1}
            if tier_rank.get(match["tier"], 0) > tier_rank.get(existing["tier"], 0):
                best_matches[req_id] = match
            elif match["tier"] == existing["tier"] and match.get("confidence", 0) > existing.get("confidence", 0):
                best_matches[req_id] = match

    # Count Tier A and B satisfactions for course_completion
    tier_ab_count = sum(
        1 for m in best_matches.values()
        if m["tier"] in ("A", "B") and _grade_passes(m.get("grade", ""))
    )
    course_completion = tier_ab_count / len(requirement_ids)

    # Compute BERT_confidence: (1/|R|) * sum_r max_c conf(c, r)
    # For each requirement, take the max confidence across all Tier C matches
    tier_c_confs = {}
    for match in gate_input.requirement_matches:
        if match["tier"] == "C":
            req_id = match["requirement_id"]
            conf = match.get("confidence", 0.0)
            tier_c_confs[req_id] = max(tier_c_confs.get(req_id, 0.0), conf)
    bert_confidence = sum(tier_c_confs.get(r, 0.0) for r in requirement_ids) / len(requirement_ids)

    # Evaluate each requirement
    all_met = True
    for req_id in requirement_ids:
        match = best_matches.get(req_id)

        if match is None:
            per_req[req_id] = {"tier": None, "accepted": False, "reason": "No match found"}
            tier_dist["unmet"] += 1
            all_met = False
            reasons.append(f"{req_id}: no course matched")
            continue

        tier = match["tier"]
        grade = match.get("grade", "")
        confidence = match.get("confidence", 1.0)

        # Grade check
        if not _grade_passes(grade):
            per_req[req_id] = {"tier": tier, "accepted": False,
                               "reason": f"Grade {grade} below C"}
            tier_dist[tier] += 1
            all_met = False
            reasons.append(f"{req_id}: grade {grade} below minimum C")
            continue

        # Tier A and B: automatic acceptance
        if tier in ("A", "B"):
            per_req[req_id] = {"tier": tier, "accepted": True, "reason": "Tier A/B direct"}
            tier_dist[tier] += 1
            continue

        # Tier C: weighted score decides acceptance
        score = (gpa_weight * _normalize_gpa(gate_input.gpa) +
                 completion_weight * course_completion +
                 bert_weight * confidence)
        accepted = score >= threshold

        per_req[req_id] = {
            "tier": "C",
            "accepted": accepted,
            "reason": f"Score {score:.3f} {'≥' if accepted else '<'} {threshold}",
            "score": score,
            "confidence": confidence,
        }
        tier_dist["C"] += 1

        if not accepted:
            all_met = False
            reasons.append(f"{req_id}: Tier C score {score:.3f} < {threshold}")

    # Final decision
    eligible = (
        gate_input.prerequisite_met
        and all_met
        and len(reasons) == 0
    )

    if not reasons:
        reasons.append("All requirements met")

    return GateResult(
        student_id=gate_input.student_id,
        eligible=eligible,
        reasons=reasons,
        tier_distribution=tier_dist,
        course_completion=course_completion,
        bert_confidence=bert_confidence,
        per_requirement=per_req,
        simulated=True,
    )


def _grade_passes(grade: str) -> bool:
    """Check if a grade meets the minimum C requirement."""
    if not grade:
        return False
    return GRADE_ORDER.get(grade.strip(), 0.0) >= MINIMUM_GRADE_VALUE


def _normalize_gpa(gpa: float) -> float:
    """Normalize GPA to [0, 1] scale (assumes 4.0 max)."""
    return min(max(gpa / 4.0, 0.0), 1.0)
