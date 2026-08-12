# T1-NLP Design: Course-Equivalency Classifier

## Architecture Overview

The system is divided into three **strictly independent** stages. Each stage can be
run, tested, and committed separately. The harvester (Stage 1) has **zero import
dependencies** on Stages 2 or 3.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 1: Harvest (standalone)                                      │
│                                                                     │
│  harvester.py ──► data/raw/equivalencies.jsonl                      │
│                   data/raw/checkpoint.json                           │
│                   data/raw/manifest.sha256                           │
└─────────────────────────────────────────────────────────────────────┘
        │  (file on disk — no import)
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 2: Preprocessing & Labeling                                  │
│                                                                     │
│  label_config.yaml ──► labeler.py ──► data/processed/labeled.csv    │
│                                        data/exclusions.log          │
└─────────────────────────────────────────────────────────────────────┘
        │  (file on disk — no import)
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 3: Model Training & Evaluation                               │
│                                                                     │
│  config.yaml ──► train.py ──► results/metrics.json                  │
│                  evaluate.py  results/confusion_matrix.png           │
│                               results/split_sweep.csv               │
│                               results/t_test.json                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Design Decision: Harvester Isolation

The harvester is a **separate, self-contained script** (`experiments/t1-nlp/src/harvester.py`).

- It imports only stdlib + `requests` + `bs4` + `hashlib` + `yaml` + `json` + `time`.
- It does NOT import torch, transformers, sklearn, or anything from Stage 2/3.
- It writes raw data to `experiments/t1-nlp/data/raw/` and nothing else.
- It is designed to be run **once**, manually, by the operator. After that, the raw
  data snapshot is the single source of truth for all downstream work.

This guarantees:
1. The public website is hit exactly once per successful harvest.
2. Downstream code never accidentally triggers network requests.
3. The harvest can be audited and versioned independently.

---

## File Layout

```
experiments/t1-nlp/
├── spec.md
├── requirements.txt
├── src/
│   ├── harvester.py          # Stage 1 — standalone
│   ├── harvest_config.yaml   # Rate limit, checkpoint path, institution list
│   ├── label_config.yaml     # Label derivation rules (AC-3)
│   ├── labeler.py            # Stage 2 — reads raw, writes labeled
│   ├── config.yaml           # Seeds, splits, model hyperparams
│   ├── models/
│   │   ├── bert_dsc_bigru.py # Primary: BERT + DepthSepConv + BiGRU
│   │   ├── cnn.py            # Baseline
│   │   ├── lstm.py           # Baseline
│   │   ├── cnn_bilstm.py    # Baseline
│   │   ├── cnn_bigru.py     # Baseline
│   │   └── bert_head.py     # Baseline: fine-tuned BERT + linear
│   ├── embeddings.py         # Word2Vec / GloVe / BERT embedding loader
│   ├── train.py              # Training loop (reads config.yaml)
│   └── evaluate.py           # Metrics, sweeps, t-test
├── data/
│   ├── raw/                  # Immutable harvest output
│   │   ├── equivalencies.jsonl
│   │   ├── checkpoint.json
│   │   └── manifest.sha256
│   └── processed/
│       ├── labeled.csv
│       └── exclusions.log
└── results/
    ├── metrics.json
    ├── confusion_matrix.png
    ├── split_sweep.csv
    └── t_test.json
```

---

## Component Design

### 1. Harvester (`harvester.py`)

| Aspect | Design |
|--------|--------|
| Input | `harvest_config.yaml` containing: `base_url`, `delay_seconds`, `checkpoint_path`, `output_path`, institution/department enumeration or discovery endpoint |
| Output | `data/raw/equivalencies.jsonl` (append-only), `checkpoint.json`, `manifest.sha256` |
| Rate limiting | Configurable `delay_seconds` (default 2.0) sleep between requests |
| Checkpoint | After each institution/department page, write `{"last_institution": ..., "last_department": ..., "rows_harvested": N}` to `checkpoint.json`. On restart, skip completed pairs. |
| Integrity | Each JSONL record includes `_sha256` (SHA-256 of the row's canonical JSON without the hash field) and `_accessed_utc` (ISO-8601 timestamp). |
| Idempotency | If a record with the same SHA-256 already exists in the output file, it is not appended again. |

### 2. Labeler (`labeler.py`)

| Aspect | Design |
|--------|--------|
| Input | `data/raw/equivalencies.jsonl` + `label_config.yaml` |
| Output | `data/processed/labeled.csv` + `data/exclusions.log` |
| Rules | `label_config.yaml` defines regex/keyword rules mapping (credits_transferred, note) → class. Order matters: first match wins. |
| Exclusions | Rows matching none of the rules are excluded. Each exclusion is logged with row index, raw values, and reason "no matching rule". |

### 3. Models

All models implement a common interface:

```python
class BaseClassifier:
    def __init__(self, config: dict): ...
    def forward(self, batch: dict) -> torch.Tensor: ...
```

**Primary model pipeline:**
1. Tokenize sending + receiving course names with BERT tokenizer.
2. Extract BERT embeddings (frozen or fine-tuned per config).
3. Apply depth-wise separable 1D convolution (kernel sizes [3, 5, 7]).
4. Feed into 2-layer Bi-GRU.
5. Take final hidden states → linear → softmax → 3 classes.

**Embedding ablation:** `embeddings.py` provides a factory that returns the requested
embedding layer (Word2Vec, GloVe 300d, or BERT) given a config key.

### 4. Evaluation (`evaluate.py`)

| Metric | Method |
|--------|--------|
| Per-class P/R/F1 | `sklearn.metrics.classification_report` |
| Macro-F1 verification | Assert harmonic-mean identity (AC-6) |
| Confusion matrix | `sklearn.metrics.confusion_matrix` → seaborn heatmap |
| AUC | One-vs-rest ROC AUC via `sklearn.metrics.roc_auc_score` |
| Latency | Time 100 single-record inferences, report mean ± std |
| Cross-validation | 10-fold stratified on training set |
| Paired t-test | `scipy.stats.ttest_rel` on per-fold F1 scores, primary vs. best baseline |
| Split sweep | Loop split ratio from 0.1 to 0.9 step 0.1, retrain, record all metrics |

### 5. Configuration (`config.yaml`)

```yaml
random_seed: 42
default_split: 0.8
cv_folds: 10
batch_size: 32
epochs: 20
learning_rate: 2e-5
embedding: "bert"        # or "word2vec", "glove"
model: "bert_dsc_bigru"  # or baseline name
```

No bare random calls. Every module reads `random_seed` from config and seeds
`random`, `numpy`, `torch` at entry point.

---

## Key Design Constraints

1. **No cross-threshold imports.** This folder is self-contained.
2. **Harvester is fully independent.** It shares no code with Stage 2 or 3.
3. **Raw data is immutable.** Once written, `data/raw/` is never modified by any script.
4. **Single config for seeds.** `config.yaml` is the sole source; `harvest_config.yaml`
   also has its own seed for any shuffling it might do, but the harvester does not
   need randomness in practice.
5. **All paths relative to `experiments/t1-nlp/`.** Scripts use `pathlib.Path(__file__).parent` to resolve.
