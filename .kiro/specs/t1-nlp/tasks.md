# T1-NLP Tasks

## Phase 1: Data Harvesting (standalone — run once, commit, then move on)

- [ ] 1.1 Write `harvest_config.yaml` with base URL, delay (2s), checkpoint path, and institution/department discovery strategy.
- [ ] 1.2 Implement `harvester.py`: enumerate institutions/departments, fetch pages, parse HTML tables, write JSONL with SHA-256 and timestamp.
- [ ] 1.3 Implement checkpoint logic: write `checkpoint.json` after each page, skip completed pairs on restart.
- [ ] 1.4 Implement rate limiting: sleep `delay_seconds` between HTTP requests, log each request URL and response status.
- [ ] 1.5 Run harvester manually (operator action). Verify `data/raw/equivalencies.jsonl` is non-empty and `manifest.sha256` is consistent.
- [ ] 1.6 Commit `data/raw/` snapshot. Harvester is now done; the website is never hit again.

## Phase 2: Preprocessing & Labeling

- [ ] 2.1 Write `label_config.yaml` defining the 3-class derivation rules from credits_transferred and note columns.
- [ ] 2.2 Implement `labeler.py`: read raw JSONL, apply config rules, output `labeled.csv` and `exclusions.log`.
- [ ] 2.3 Verify exclusions log contains counts and reasons for every dropped row.
- [ ] 2.4 Write `config.yaml` with random seed, split ratio, CV folds, model hyperparams.

## Phase 3: Model Training & Evaluation

- [ ] 3.1 Implement `embeddings.py` factory (Word2Vec, GloVe, BERT).
- [ ] 3.2 Implement primary model `models/bert_dsc_bigru.py`.
- [ ] 3.3 Implement baselines: `cnn.py`, `lstm.py`, `cnn_bilstm.py`, `cnn_bigru.py`, `bert_head.py`.
- [ ] 3.4 Implement `train.py`: read config, seed everything, train loop, save checkpoints.
- [ ] 3.5 Implement `evaluate.py`: per-class metrics, macro-F1 assertion, confusion matrix, AUC, latency, 10-fold CV, paired t-test, split sweep.
- [ ] 3.6 Run full training + evaluation pipeline. Verify `results/` is populated.
- [ ] 3.7 Commit results. T1 is complete.

---

## Execution Notes

- Phase 1 is **blocking**: tasks 1.5 and 1.6 require operator action (running the
  harvester and inspecting output). Do not proceed to Phase 2 until raw data is
  committed.
- Phases 2 and 3 can be developed concurrently against a small synthetic sample
  if desired, but final evaluation requires the real harvested data.
- Each phase produces a commit. The merge to `main` happens only after all three
  phases pass.
