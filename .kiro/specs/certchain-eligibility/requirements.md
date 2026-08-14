# CertChain Eligibility — Requirements

## Goal

Evaluate a four-stage cascade for matching student courses to the FAMU Cyber
Defense Certificate requirements, and measure the reliability of the on-chain
eligibility gate under classifier error.

---

## Functional Requirements

### FR-1: Four-Stage Cascade

| Stage | Name | Logic | Provenance Tier | Confidence |
|-------|------|-------|-----------------|------------|
| 0 | Articulation lookup | Existing agreement maps course→requirement | A (articulated) | 1.0 |
| 1 | Exact course-code match | Code equality across institutions | B (deterministic) | 1.0 |
| 2 | Normalized title + credit-hour check | Deterministic string normalization, no model | B (deterministic) | 1.0 |
| 3 | BERT semantic match | Binary classifier on residual pairs | C (inferred) | model output ∈ [0,1] |

First match wins. A course-requirement pair resolved at a higher stage is never
re-evaluated at a lower stage.

### FR-2: Eligibility Gate (conjunctive)

```
eligible = prerequisite_met
           AND all 5 requirements matched
           AND every matched course has grade >= C
```

The weighted score `0.40×GPA + 0.40×course_completion + 0.20×BERT_confidence ≥ 0.70`
applies **per requirement at Tier C only**, deciding whether a semantically
inferred match is accepted as satisfying that specific requirement. It does NOT
govern overall eligibility.

- `course_completion` = fraction of requirements satisfied at Tier A or B only.
- `BERT_confidence` = `(1/|R|) × Σ_r max_c conf(c, r)` where `conf(c,r)` is the
  classifier confidence that course `c` satisfies requirement `r`.

### FR-3: Inputs

| Input | Source | Status |
|-------|--------|--------|
| Certificate requirement list | `src/requirements.yaml` | Frozen, hashed |
| Course catalog | MassTransfer CIS harvest from T1-NLP | Available (2,129 records) |
| Articulation table | `data/raw/articulations.csv` | Empty (production path, no data) |
| Ground truth labels | Human-labeled course-requirement pairs | **NOT YET SUPPLIED** |
| Student portfolios | Synthetic (Monte Carlo simulation) | Generated from config |

### FR-4: Evaluation Deliverables

1. Cascade resolution rates and per-stage latency and inference-call counts.
2. BERT classifier evaluated on Stage 3 residual only (the only population it serves).
3. Tier distribution across evaluation set; gate accuracy reported separately for
   credentials with zero Tier C matches vs. one or more.
4. Sensitivity analysis of the gate: how often a wrong confidence flips the ≥0.70
   decision, swept across BERT weight [0.10, 0.40] and threshold [0.60, 0.80].
   Pearson and Spearman correlations between `course_completion` and `BERT_confidence`.

### FR-5: Per-Requirement Reporting

All metrics are reported per requirement (R1–R5), not just aggregate. The asymmetry
in match difficulty across requirements is a finding.

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Stage 0 code path is fully implemented, loads from articulation table, reports 0% resolution when table is empty. Stage is visible in output, not silently absent. |
| AC-2 | Stage 1 reports near-zero resolution as evidence that course codes are not portable across institutions. |
| AC-3 | Stage 2 normalization rules are written from the requirement list alone, frozen before inspecting MassTransfer course titles, and never tuned against evaluation data. |
| AC-4 | Ground truth is human-labeled. No synthetic labels. Evaluation halts at data-prep boundary until labels are supplied. |
| AC-5 | Student portfolios are synthetic (Monte Carlo), seeded from config, with documented and swept parameters. Every gate result is labeled "simulated" in output and manifest. |
| AC-6 | Classifier metrics (empirical) and gate metrics (simulated) never appear in the same table without the distinction labeled. |
| AC-7 | requirements.yaml is hashed (SHA-256) and the hash is recorded in the results manifest. The file is never modified. |
| AC-8 | GroupKFold with group key `(granting_institution, course_code)` is used for classifier evaluation. |
| AC-9 | TF-IDF + LR floor baseline is included alongside the BERT classifier. |
| AC-10 | Per-class P/R/F1 with support, confusion matrix, and per-record latency are reported. |
| AC-11 | Results README notes IRB limitation: real student transcripts require IRB review, path stays closed. |

---

## Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | No cross-imports between experiment folders. |
| NFR-2 | Separate Python venv (`experiments/certchain-eligibility/.venv`). |
| NFR-3 | No Fabric, Solidity, or smart contract dependencies. Off-chain harness only. |
| NFR-4 | All random seeds from config. No bare random calls. |
| NFR-5 | No dependency on Dataset1-cs-95012-updated.csv or any K-12 data. |

---

## Limitations (document in results README)

- Real student transcripts require IRB review. Path stays closed for now.
- Stage 0 articulation data does not exist for this evaluation. Reported as 0%.
- Ground truth labels are pending human adjudication. Experiment cannot proceed
  past data preparation until supplied.
