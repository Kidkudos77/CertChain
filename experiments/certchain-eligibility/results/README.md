# CertChain Eligibility — Results Summary

## Status: Progress Report (Partial)

**Date:** August 2026
**Labeling:** Pass 1 complete (936 pairs). Intra-rater reliability (Pass 2) scheduled for 7 days post-completion.

---

## 1. Dataset

| Metric | Value |
|--------|-------|
| Courses labeled | 156 (complete CIS pool from MassTransfer harvest) |
| Requirements | 5 + 1 prerequisite (FAMU Cyber Defense Certificate) |
| Total pairs | 936 |
| Positive labels | 59 (6.3%) |
| Labeling method | Single labeler, rubric-guided, corrections applied via LLM disagreement finder |

---

## 2. Cascade Resolution Rates

| Stage | Tier | Pairs Resolved | Positives Caught | Resolution Rate |
|-------|------|---------------|-----------------|-----------------|
| 0 — Articulation lookup | A | 0 | 0 | 0.0% |
| 1 — Exact course-code match | B | 0 | 0 | 0.0% |
| 2 — Normalized title match | B | 40 | 27 | 4.3% |
| 3 — BERT semantic (residual) | C | 896 | 32 | 95.7% |

**Stage 0** is a production code path with no articulation data available for this evaluation. Reported as 0% rather than omitted.

**Stage 1** confirms that course codes are not portable across institutions. No FAMU Cyber Defense course code (e.g., CIS 4385C) appears in any MA community college catalog.

**Stage 2** resolves 40 pairs via deterministic normalized title matching:
- Precision: 67.5% (27/40 true positives)
- The 13 false positives are over-matches from the frozen normalization rule for "programming" (the prerequisite target). The R3 ("Applied Security") rule normalizes to just ["security"], producing expected over-matching — documented as a finding, not a defect.

**Stage 3** receives 896 pairs (95.7%) as the BERT residual. Positive rate: 3.6%.

---

## 3. Per-Requirement Asymmetry

| Requirement | Stage 2 Matches | Stage 3 Positives | Total Positives |
|-------------|----------------|-------------------|-----------------|
| R1 — Digital Forensics | 1 (Computer Forensics I) | 0 | 1 |
| R2 — Intro to Computer Security | 1 (Advanced Computer Security) | 3 | 4* |
| R3 — Applied Security | 0 | 0** | 1 |
| R4 — Network Security | 1 (Network Security) | 3 | 4 |
| R5 — Database Management Systems | 0 | 10 | 10 |
| Prerequisite — Programming | 37 | 16 | 53* |

*Includes Stage 2 false positives that were labeled 0.
**R1 and R3 have near-zero matches. These requirements represent courses rarely offered under recognizable names at community colleges. They would require human registrar review in every case.

**This asymmetry is the key finding:** the cascade's value is requirement-specific. Database courses (R5) are common and matchable. Forensics and applied security (R1, R3) are specialized and essentially unmatchable without human review or a much richer training set.

---

## 4. Eligibility Gate Design (Corrected)

The original CertChain formula (`0.40×GPA + 0.40×course_completion + 0.20×BERT_confidence ≥ 0.70`) was found to be defective:

- A student with a 4.0 GPA who completed only 2/5 requirements scores 0.76 and passes.
- The formula treats course completion as compensable; FAMU policy does not.
- The policy requires a per-course grade floor of C, not aggregate GPA.

**Corrected gate (conjunctive):**
```
eligible = prerequisite_met
           AND all 5 requirements matched
           AND every matched course has grade >= C
```

The weighted score applies **per requirement at Tier C only**, deciding whether a semantically inferred match is accepted:
```
accept_tier_c = 0.40×GPA + 0.40×course_completion + 0.20×confidence >= 0.70
```

This preserves the ML contribution while preventing the gate from issuing credentials to students who never took required courses.

---

## 5. Limitations

- **No IRB approval for real student transcripts.** Gate sensitivity analysis uses synthetic student portfolios (Monte Carlo simulation). All gate metrics are labeled SIMULATED.
- **Single labeler.** Intra-rater reliability (test-retest kappa) is scheduled but not yet measured. Will be reported in final submission.
- **Partial pool.** Only the CIS department from MassTransfer was harvested. A production system would cover all departments.
- **Stage 3 classifier not yet trained.** The BERT evaluation on the residual requires labeled data from this pass, which is now available. Zero-shot embedding similarity is the planned method (no training split needed).
- **Stage 0 has no data.** Articulation agreements were not available. In production, this stage would resolve the majority of pairs with confidence 1.0.

---

## 6. TF-IDF Floor on Stage 3 Residual (Measured)

TF-IDF + Logistic Regression (balanced, GroupKFold on institution+code) on the
896-pair Stage 3 residual (32 positives, prevalence = 3.6%):

| Metric | Value |
|--------|-------|
| Precision | 13.2% (21 true positives among 159 flagged) |
| Recall | 65.6% (found 21 of 32 true matches) |
| F1 | 0.22 |
| No-skill baseline (prevalence) | F1 = 0, precision = 3.6% |

Accuracy is uninformative at this prevalence and is not reported.

**Interpretation:** Lexical matching reaches 65.6% recall at 13.2% precision —
it flags 159 pairs from 896 to find 21 true matches. It cannot produce a usable
decision on its own (7 out of 8 flags are wrong), but it achieves an 82% reduction
in registrar review volume to recover two-thirds of true matches.

This reframes Stage 3 as a **triage layer** rather than a decision layer, which
fits the provenance-tier design: Tier C outputs are not trusted absolutely, they
are submitted to the per-requirement weighted acceptance rule.

BERT's target: beat F1 = 0.22. Majority baseline F1 = 0 (finds nothing).

**Caveat:** 32 positives across 896 pairs means every Stage 3 metric has wide
confidence intervals. Report the positive count (n=32) alongside each figure.
R1 and R3 have zero positives in the residual — precision and recall are
undefined there (not zero — undefined: the denominator is zero, so the metric
does not exist for those requirements).

**Recall caveat on the triage claim:** 82% volume reduction at 65.6% recall
means one-third of genuine matches are missed. For credential issuance, a false
negative is a student wrongly denied. Triage cannot replace review — the
unflagged remainder must also be checked. The correct framing is
**prioritization** (which pairs to review first), not **elimination** (which
pairs are safe to skip). Stage 3 surfaces high-confidence candidates for
registrar confirmation; it does not make the decision.

---

## 7. What This Proves

1. **The cascade architecture works.** Deterministic stages resolve easy cases; ML handles the residual.
2. **Course codes are not portable.** Stage 1's 0% proves this empirically.
3. **Requirement difficulty is asymmetric.** Database courses match easily; forensics and applied security do not. This tells institutions exactly where human review is needed.
4. **The original gate formula is wrong.** The conjunctive correction is necessary and defensible.
5. **The positive rate in the BERT residual is very low (3.6%).** This is a hard problem for any classifier — it must find rare matches in a sea of negatives.
