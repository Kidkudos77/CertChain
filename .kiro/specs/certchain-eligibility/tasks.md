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

## Phase 2: Cascade and Classifier (BLOCKED on labels)

- [ ] 2.1 Load human labels into data/labels/
- [ ] 2.2 Run cascade on all pairs: record Stage 0/1/2 resolutions
- [ ] 2.3 Extract Stage 3 residual (unresolved pairs)
- [ ] 2.4 Train BERT binary classifier on residual pairs with labels
- [ ] 2.5 Evaluate: GroupKFold, TF-IDF+LR floor, per-class P/R/F1, confusion matrix, latency
- [ ] 2.6 Report per-requirement metrics (R1–R5 individually)

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
- Phase 2 requires labeled data supplied by the operator.
- Phase 3 requires Phase 2 outputs (measured classifier error distribution).
- Synthetic student generation is seeded, documented, and swept — but all gate
  results are SIMULATED, never empirical.
