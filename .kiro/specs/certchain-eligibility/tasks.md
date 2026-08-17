# CertChain Eligibility — Tasks

## Phase 1: Scaffold and Data Preparation

- [x] 1.1 Create folder structure and requirements.txt
- [x] 1.2 Write requirements.yaml (frozen, hashed)
- [x] 1.3 Write spec documents
- [x] 1.4 Write Stage 2 normalization rules from requirement list only (freeze)
- [x] 1.5 Write empty articulation table, config.yaml, scaffold src/ scripts
- [ ] 1.6 Copy MassTransfer CIS catalog into data/raw/ (from t1-nlp harvest)
- [ ] 1.7 Implement prepare_pairs.py: generate all (course, requirement) pairs
- [ ] 1.8 **STOP — await human-labeled ground truth**

## Phase 1B: Labeling (single-labeler with intra-rater reliability)

- [ ] 1B.1 Generate 600 test pairs (shuffled, seeded from config)
- [ ] 1B.2 **Pass 1:** Label all 600 pairs. Log date of each labeling session.
- [ ] 1B.3 **Wait ≥ 7 days.**
- [ ] 1B.4 **Pass 2:** Relabel a random 40% subsample (240 pairs) with a different shuffle seed, without access to Pass 1 answers. Log date.
- [ ] 1B.5 Compute Cohen's kappa, PABAK, raw agreement, and 2×2 marginals (overall and per requirement) between Pass 1 and Pass 2 on the 240-pair overlap.
- [ ] 1B.6 **Pass 1 is the final label set for all 600 pairs. Full stop.** Pass 2 exists only to measure reliability. Disagreements are reported as measured noise, never repaired.
- [ ] 1B.7 (Optional) Obtain partial second-labeler kappa on a 100-pair subsample.

Expected files:
  - `data/labels/test_set_pass1.csv` — 600 pairs, full first pass (THIS IS THE FINAL LABEL SET)
  - `data/labels/test_set_pass2.csv` — 240 pairs, retest subsample (measurement only)
  - `data/labels/test_set.csv` — copy of Pass 1 (symlink or identical content)

Failure path:
  - If kappa + PABAK + raw agreement together indicate rubric failure (not just
    prevalence-driven kappa deflation), BOTH passes are void.
  - All 600 pairs must be relabeled under the revised rubric from scratch.
  - Labels from two rubric versions must NEVER be mixed.

Integrity:
  - Pass 1 file must not be opened or modified during Pass 2 labeling.
  - compute_kappa.py refuses to write Pass 2 if Pass 1 was modified after its
    recorded completion timestamp.

## Phase 2: Cascade and Classifier (BLOCKED on labels)

- [ ] 2.1 Load human labels from data/labels/test_set.csv
- [ ] 2.2 Compute intra-rater kappa (overall + per requirement R1–R5)
- [ ] 2.3 Run cascade on all labeled pairs: record Stage 0/1/2 resolutions
- [ ] 2.4 Extract Stage 3 residual (unresolved pairs)
- [ ] 2.5 Train BERT binary classifier on residual pairs with labels
- [ ] 2.6 Evaluate: GroupKFold, TF-IDF+LR floor, per-class P/R/F1, confusion matrix, latency
- [ ] 2.7 Report per-requirement metrics (R1–R5 individually)

## Phase 3: Gate Simulation (BLOCKED on Phase 2)

- [ ] 3.1 Implement simulate_students.py: synthetic portfolio generator
- [ ] 3.2 Run cascade on synthetic students, compute gate decisions
- [ ] 3.3 Sensitivity sweep: BERT weight [0.10, 0.40] × threshold [0.60, 0.80]
- [ ] 3.4 Report tier distributions, gate accuracy (0 vs ≥1 Tier C)
- [ ] 3.5 Report Pearson/Spearman correlations: course_completion vs BERT_confidence
- [ ] 3.6 Label all gate outputs as SIMULATED in manifest

## Phase 4: Results and Commit

- [ ] 4.1 Write results README with IRB limitation note
- [ ] 4.2 Write manifest.json with requirements.yaml hash, provenance
- [ ] 4.3 Commit

---

## Execution Notes

- Phase 1 tasks 1.6–1.7 can proceed without labels (just pair generation).
- Phase 1 task 1.8 is a hard stop. No classifier training without human labels.
- Phase 1B is the labeling protocol. It is performed by the operator (single labeler).
  Intra-rater reliability (test-retest with ≥7 day gap) replaces inter-rater reliability.
  This is a standard, citable technique for single-labeler designs.
- Phase 2 requires labeled data from Phase 1B.
- Phase 3 requires Phase 2 outputs (measured classifier error distribution).
- Synthetic student generation is seeded, documented, and swept — but all gate
  results are SIMULATED, never empirical.

## Labeling Protocol Notes

- 600 judgments × ~12s = ~2 hours. Split across sittings. Log dates.
- Retest subsample: 240 pairs × ~12s = ~45 minutes.
- The 7-day gap prevents recall from round one. Document the actual gap in days.
- Pass 1 is the final label set. Full stop. No adjudication from retest.
- Pass 2 measures reliability only. Disagreements are reported as noise, not repaired.
- Report: raw agreement, Cohen's kappa, PABAK, 2×2 marginals, positive rate per req.
- Kappa is unstable at low prevalence (~5% positive rate). A rubric is NOT failed
  on kappa < 0.61 alone. Interpret kappa, PABAK, and raw agreement together.
  High agreement + low kappa + high prevalence index = prevalence deflation, not
  rubric failure.
- FAILURE PATH: If all three metrics (kappa, PABAK, raw agreement) indicate poor
  consistency, BOTH passes are void. All 600 pairs must be relabeled under a
  revised rubric from scratch. Labels from two rubric versions are NEVER mixed.
- compute_kappa.py refuses to write Pass 2 results if Pass 1 was modified after
  its recorded completion timestamp.
- Rubric reviewed by thesis advisor (Dr. Chi). Document the review date, or note
  that it was circulated and the deadline passed.
- Do NOT use an LLM as a second labeler. An LLM may be used as a disagreement
  finder: surface pairs where it disagrees with your labels, re-examine those
  against the rubric yourself, you decide. Declare this in the README.
- Final labels are wholly human-adjudicated.
