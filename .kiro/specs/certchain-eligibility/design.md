# CertChain Eligibility — Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Data Preparation (BLOCKED — awaiting human labels)                 │
│                                                                     │
│  MassTransfer CIS catalog ──► course-requirement pairs              │
│  requirements.yaml ──────────► 5 requirements × N courses           │
│  human labels ───────────────► binary ground truth per pair          │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Four-Stage Cascade (cascade.py)                                    │
│                                                                     │
│  Stage 0: articulation_lookup(course, req) → Tier A or pass         │
│  Stage 1: exact_code_match(course, req) → Tier B or pass            │
│  Stage 2: normalized_title_match(course, req) → Tier B or pass      │
│  Stage 3: bert_semantic_match(course, req) → Tier C + confidence    │
│                                                                     │
│  First match wins. Residual flows to next stage.                    │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Eligibility Gate (gate.py) — pure function, no chaincode           │
│                                                                     │
│  eligible = prerequisite_met                                        │
│             AND all 5 requirements matched                          │
│             AND every matched course has grade >= C                  │
│                                                                     │
│  Per-requirement Tier C acceptance:                                  │
│    accept = 0.40×GPA + 0.40×course_completion + 0.20×conf ≥ 0.70    │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Evaluation Harness (evaluate.py)                                   │
│                                                                     │
│  1. Cascade resolution rates, per-stage latency, call counts        │
│  2. BERT on Stage 3 residual: GroupKFold, P/R/F1, TF-IDF floor     │
│  3. Tier distribution, gate accuracy (0 vs ≥1 Tier C)              │
│  4. Sensitivity: sweep BERT weight × threshold, correlations        │
│     (all gate metrics labeled SIMULATED)                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## File Layout

```
experiments/certchain-eligibility/
├── spec.md
├── requirements.txt
├── src/
│   ├── requirements.yaml          # Frozen certificate requirements (hashed)
│   ├── normalization_rules.yaml   # Stage 2 rules (frozen before seeing data)
│   ├── articulations.csv          # Stage 0 table (empty — production path)
│   ├── config.yaml                # Seeds, parameters, sweep ranges
│   ├── cascade.py                 # Four-stage cascade implementation
│   ├── gate.py                    # Eligibility gate pure function
│   ├── prepare_pairs.py           # Build course-requirement pairs from catalog
│   ├── train_bert.py              # Train binary BERT classifier on labeled pairs
│   ├── evaluate.py                # Full evaluation harness
│   └── simulate_students.py       # Synthetic portfolio generator (Monte Carlo)
├── data/
│   ├── raw/                       # Symlink or copy of MassTransfer CIS catalog
│   ├── processed/                 # Pairs, labels, cascade output
│   └── labels/                    # Human-supplied ground truth (NOT YET)
└── results/
    ├── cascade_stats.json
    ├── classifier_metrics.json    # EMPIRICAL
    ├── gate_sensitivity.json      # SIMULATED
    ├── manifest.json              # Hashes, provenance
    └── README.md                  # Limitations, IRB note
```

---

## Design Decisions

### 1. Gate is Conjunctive

The weighted score does NOT determine overall eligibility. It determines, per
requirement, whether a Tier C (inferred) match is accepted. This prevents a
student from passing by compensating missing requirements with high GPA.

### 2. Prerequisite is Excluded from Denominator

COP 3014C is a precondition for entering the program. It is checked as a
separate boolean (`prerequisite_met`), not counted in `course_completion`.

### 3. Stage 2 Rules Frozen Before Data Inspection

Normalization rules are derived solely from the five requirement titles in
`requirements.yaml`. They are never tuned against MassTransfer course titles.
This prevents data leakage from the evaluation set into the deterministic stage.

### 4. Cascade is Sequential, Not Parallel

Each course-requirement pair enters Stage 0. If unresolved, it passes to
Stage 1, then 2, then 3. A pair resolved at Stage 0 is never seen by Stages
1–3. This means the BERT classifier is only evaluated on the residual that
all deterministic stages failed to resolve — which is the only population it
serves in production.

### 5. Empirical vs. Simulated Boundary

- **Empirical:** Cascade resolution rates, BERT classifier metrics on labeled
  pairs. These come from real data with human labels.
- **Simulated:** Gate accuracy, sensitivity analysis, tier distribution per
  student. These use synthetic portfolios and Monte Carlo. Every output from
  the simulated path is labeled as such.

### 6. Per-Requirement Asymmetry is a Finding

"Database Management Systems" will likely resolve at Stage 2. "Applied Security"
will not. This asymmetry tells an institution exactly which requirements need
human review, and it is reported explicitly.
