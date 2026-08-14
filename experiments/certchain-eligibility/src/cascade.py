"""
Four-Stage Cascade for Course-Requirement Matching.

Stage 0: Articulation lookup (Tier A, confidence 1.0)
Stage 1: Exact course-code match (Tier B, confidence 1.0)
Stage 2: Normalized title match + credit-hour check (Tier B, confidence 1.0)
Stage 3: BERT semantic match (Tier C, confidence ∈ [0,1])

First match wins. Residual flows to next stage.

Usage:
    from cascade import Cascade
    cascade = Cascade(config)
    result = cascade.resolve(course, requirement_id)
"""

import csv
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class CascadeResult:
    """Result of cascade resolution for a single course-requirement pair."""
    course_code: str
    course_name: str
    course_credits: float
    requirement_id: str
    resolved: bool
    stage: Optional[int]  # 0, 1, 2, 3, or None if unresolved
    tier: Optional[str]   # "A", "B", "C", or None
    confidence: float     # 1.0 for tiers A/B, model output for C
    latency_ms: float


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


class Cascade:
    """Four-stage cascade resolver."""

    def __init__(self, config: dict):
        self.config = config

        # Load requirements
        req_path = PROJECT_DIR / config["paths"]["requirements"]
        with open(req_path, "r", encoding="utf-8") as f:
            self.requirements = yaml.safe_load(f)

        # Load normalization rules
        norm_path = PROJECT_DIR / config["paths"]["normalization_rules"]
        with open(norm_path, "r", encoding="utf-8") as f:
            self.norm_rules = yaml.safe_load(f)

        # Load articulation table
        art_path = PROJECT_DIR / config["paths"]["articulations"]
        self.articulations = self._load_articulations(art_path)

        # BERT model (lazy-loaded for Stage 3)
        self._bert_model = None
        self._bert_tokenizer = None

        # Stats
        self.stage_counts = {0: 0, 1: 0, 2: 0, 3: 0, "unresolved": 0}
        self.stage_latencies = {0: [], 1: [], 2: [], 3: []}

    def _load_articulations(self, path: Path) -> dict:
        """Load articulation table into a lookup dict."""
        table = {}
        if not path.exists():
            return table
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(
                (row for row in f if not row.startswith("#")),
            )
            for row in reader:
                key = (row.get("sending_institution", ""), row.get("sending_course_code", ""))
                table[key] = row.get("requirement_id", "")
        return table

    def resolve(self, course: dict, requirement_id: str) -> CascadeResult:
        """
        Resolve a single course-requirement pair through the cascade.

        Args:
            course: dict with keys: sending_institution, sending_course_code,
                    sending_course_name, sending_credits
            requirement_id: one of R1-R5 or "prerequisite"
        """
        code = course.get("sending_course_code", "")
        name = course.get("sending_course_name", "")
        credits = float(course.get("sending_credits", 0) or 0)
        institution = course.get("sending_institution", "")

        base_result = {
            "course_code": code,
            "course_name": name,
            "course_credits": credits,
            "requirement_id": requirement_id,
        }

        # Stage 0: Articulation lookup
        start = time.perf_counter()
        result = self._stage0(institution, code, requirement_id)
        elapsed = (time.perf_counter() - start) * 1000
        self.stage_latencies[0].append(elapsed)
        if result is not None:
            self.stage_counts[0] += 1
            return CascadeResult(**base_result, resolved=True, stage=0,
                                 tier="A", confidence=1.0, latency_ms=elapsed)

        # Stage 1: Exact code match
        start = time.perf_counter()
        result = self._stage1(code, requirement_id)
        elapsed = (time.perf_counter() - start) * 1000
        self.stage_latencies[1].append(elapsed)
        if result is not None:
            self.stage_counts[1] += 1
            return CascadeResult(**base_result, resolved=True, stage=1,
                                 tier="B", confidence=1.0, latency_ms=elapsed)

        # Stage 2: Normalized title match
        start = time.perf_counter()
        result = self._stage2(name, credits, requirement_id)
        elapsed = (time.perf_counter() - start) * 1000
        self.stage_latencies[2].append(elapsed)
        if result is not None:
            self.stage_counts[2] += 1
            return CascadeResult(**base_result, resolved=True, stage=2,
                                 tier="B", confidence=1.0, latency_ms=elapsed)

        # Stage 3: BERT semantic match (stub — requires trained model)
        start = time.perf_counter()
        confidence = self._stage3(name, credits, requirement_id)
        elapsed = (time.perf_counter() - start) * 1000
        self.stage_latencies[3].append(elapsed)
        self.stage_counts[3] += 1
        # Stage 3 always "resolves" with a confidence — the gate decides acceptance
        return CascadeResult(**base_result, resolved=True, stage=3,
                             tier="C", confidence=confidence, latency_ms=elapsed)

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage0(self, institution: str, code: str, req_id: str) -> Optional[str]:
        """Articulation lookup. Returns req_id if found, None otherwise."""
        key = (institution, code)
        mapped = self.articulations.get(key)
        if mapped and mapped == req_id:
            return req_id
        return None

    def _stage1(self, code: str, req_id: str) -> Optional[str]:
        """Exact course-code match against requirement codes."""
        req = self._get_requirement(req_id)
        if req and req.get("code", "") == code:
            return req_id
        return None

    def _stage2(self, title: str, credits: float, req_id: str) -> Optional[str]:
        """Normalized title match + credit-hour check."""
        # Get pre-computed normalized tokens for this requirement
        norm_req_tokens = self.norm_rules.get("normalized_requirements", {}).get(req_id)
        if not norm_req_tokens:
            return None

        # Get credit minimum
        credit_min = self.norm_rules.get("credit_minimums", {}).get(req_id, 0)
        if credits < credit_min:
            return None

        # Normalize candidate title
        norm_candidate = self._normalize_title(title)

        # Match: candidate contains all tokens of the requirement
        if all(token in norm_candidate for token in norm_req_tokens):
            return req_id

        return None

    def _stage3(self, title: str, credits: float, req_id: str) -> float:
        """
        BERT semantic match. Returns confidence ∈ [0,1].
        STUB: returns 0.0 until model is trained on labeled data.
        """
        # TODO: Load trained model and compute confidence
        # This is blocked until human labels are supplied and the model is trained.
        return 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_requirement(self, req_id: str) -> Optional[dict]:
        """Look up a requirement by ID."""
        if req_id == "prerequisite":
            return self.requirements.get("prerequisite")
        for req in self.requirements.get("requirements", []):
            if req["id"] == req_id:
                return req
        return None

    def _normalize_title(self, title: str) -> list[str]:
        """Apply the normalization pipeline to a course title."""
        # 1. Lowercase
        text = title.lower()
        # 2/3. Remove punctuation
        text = re.sub(r'[.,;:()\[\]/\\\"\']', ' ', text)
        # 4. Collapse spaces
        text = re.sub(r'\s+', ' ', text).strip()
        # 5. Tokenize and remove stop words
        stop_words = set(self.norm_rules.get("stop_words", []))
        tokens = [t for t in text.split() if t not in stop_words]
        # 6. Apply synonyms (map to canonical form)
        synonym_map = {}
        for group in self.norm_rules.get("synonyms", []):
            canonical = group[0]
            for variant in group:
                synonym_map[variant] = canonical
        tokens = [synonym_map.get(t, t) for t in tokens]
        # 7. Sort alphabetically
        tokens = sorted(set(tokens))
        return tokens

    def get_stats(self) -> dict:
        """Return cascade resolution statistics."""
        import numpy as np
        total = sum(self.stage_counts.values())
        stats = {
            "total_pairs": total,
            "per_stage": {},
        }
        for stage in [0, 1, 2, 3]:
            count = self.stage_counts[stage]
            latencies = self.stage_latencies[stage]
            stats["per_stage"][f"stage_{stage}"] = {
                "count": count,
                "rate": count / total if total > 0 else 0,
                "latency_mean_ms": float(np.mean(latencies)) if latencies else 0,
                "latency_std_ms": float(np.std(latencies)) if latencies else 0,
            }
        stats["per_stage"]["unresolved"] = {
            "count": self.stage_counts["unresolved"],
            "rate": self.stage_counts["unresolved"] / total if total > 0 else 0,
        }
        return stats
