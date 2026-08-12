# T1-NLP Requirements: Course-Equivalency Classifier

## Goal

Build a 3-class course-equivalency classifier and a full evaluation harness using
data harvested from the MassTransfer Course Equivalency Database.

---

## Functional Requirements

### FR-1: Data Harvesting

| ID | Requirement |
|----|-------------|
| FR-1.1 | Harvest the MassTransfer Course Equivalency Database at `https://www.mass.edu/masstransfer/equivalencies/PublicList.asp` by iterating over sending-institution and department parameters. |
| FR-1.2 | Each harvested row contains: sending institution, sending course code, sending course name, sending credits, receiving institution, receiving course code, receiving course name, credits transferred, and note. |
| FR-1.3 | Derive a 3-class label from the credits-transferred and note columns: **direct equivalent**, **partial / elective credit**, **not transferable**. |
| FR-1.4 | Label-derivation rules live in a single YAML config file (`experiments/t1-nlp/src/label_config.yaml`), not scattered in code. |

### FR-2: Model Architecture

| ID | Requirement |
|----|-------------|
| FR-2.1 | Primary model: BERT embeddings → depth-wise separable convolution → Bi-GRU → softmax. |
| FR-2.2 | Baselines: (a) CNN, (b) LSTM, (c) CNN+BiLSTM, (d) CNN+BiGRU, (e) plain fine-tuned BERT head. |
| FR-2.3 | Embedding ablation across Word2Vec, GloVe, and BERT for each applicable architecture. |

### FR-3: Evaluation

| ID | Requirement |
|----|-------------|
| FR-3.1 | Default split: 80/20 train/test. |
| FR-3.2 | 10-fold cross-validation on the training portion. |
| FR-3.3 | Paired t-test of primary model F1 against the strongest baseline. |
| FR-3.4 | Report per-class precision, recall, F1, plus confusion matrix, accuracy, AUC, and inference latency per record. |
| FR-3.5 | Sweep the train/test split from 10% to 90% in 10% steps, recording all metrics at each point. |
| FR-3.6 | F1 is reported as **macro-averaged** and verified: macro-F1 == harmonic mean of macro-precision and macro-recall. |

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Harvester is rate-limited with an explicit configurable delay (`delay_seconds` in config) and resumes from a checkpoint file so partial runs are not lost. |
| AC-2 | Raw captures are written once (append-only), never overwritten. Each record includes a SHA-256 hash of its content and a UTC access timestamp. |
| AC-3 | Label-derivation rules are defined entirely in `label_config.yaml`. No classification logic lives in Python code outside of reading that config. |
| AC-4 | Every excluded row during label derivation is logged to `data/exclusions.log` with a count and a human-readable reason. |
| AC-5 | All random seeds come from a single config entry (`random_seed`). No bare `random()` or unseeded calls anywhere. |
| AC-6 | F1 is stated as macro-averaged and the evaluation harness asserts `macro_f1 == 2 * macro_precision * macro_recall / (macro_precision + macro_recall)` within floating-point tolerance. |
| AC-7 | Harvester is a standalone task with no import dependencies on model or evaluation code. It can be run and completed independently before any downstream work begins. |
| AC-8 | All outputs (raw data, processed data, model checkpoints, evaluation results) are written under `experiments/t1-nlp/data/` or `experiments/t1-nlp/results/`. Nothing is written outside the threshold folder. |

---

## Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | No cross-imports between threshold experiment folders. If T2 needs an artifact from T1 it must be copied, not imported. |
| NFR-2 | Separate Python virtual environment for this threshold (`experiments/t1-nlp/.venv`). |
| NFR-3 | Reproducibility: given the same seed and data snapshot, training produces bit-identical metrics. |
| NFR-4 | The harvester must be safe to re-run without duplicating data (idempotent via checkpoint). |

---

## Data Source

- URL: `https://www.mass.edu/masstransfer/equivalencies/PublicList.asp`
- Access method: HTTP POST with form parameters for sending institution and department.
- Expected volume: tens of thousands of rows across all institution/department combinations.

---

## Out of Scope

- Deploying a production inference service.
- Real-time model serving or API integration.
- Anything related to thresholds T2–T5.
