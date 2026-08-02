# CertChain
### FAMU FCCS (Cyber Defense Certificate) Blockchain Micro-Credentialing System

[![CI/CD](https://github.com/YOUR_USERNAME/certchain/actions/workflows/certchain.yml/badge.svg)](https://github.com/YOUR_USERNAME/certchain/actions)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green)](https://nodejs.org)
[![Hyperledger Fabric](https://img.shields.io/badge/Hyperledger-Fabric%202.5-orange)](https://hyperledger.org)
[![Post-Quantum](https://img.shields.io/badge/PQ%20Crypto-CRYSTALS--Dilithium3-purple)](https://pq-crystals.org)
[![License](https://img.shields.io/badge/License-MIT-lightgrey)](LICENSE)

---

> **Thesis Statement:** A three-layer framework in which a BERT-based NLP classifier extracts
> structured eligibility features from unstructured student transcripts, a weighted multi-factor
> scoring algorithm evaluates those features against FCCS (Cyber Defense Certificate) program
> requirements, and a Hyperledger
> Fabric smart contract conditionally issues tamper-proof micro-credentials based on that score —
> eliminating the manual review process that current systems require. Deployed on the National
> Research Platform using Kubernetes with GitHub Actions for CI/CD. Post-quantum signatures using
> CRYSTALS-Dilithium3 make issued credentials resilient against future quantum attacks — a gap
> unaddressed in the reviewed micro-credentialing literature.

---

## Table of Contents

- [Overview](#overview)
- [Thesis Contributions](#thesis-contributions)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Evaluation](#evaluation)
- [Sampling-Based Batch Verification](#sampling-based-batch-verification)
- [Kaggle Dataset](#kaggle-dataset)
- [NRP Deployment](#nrp-deployment)
- [Supervisor Customization](#supervisor-customization)
- [Research Gaps Addressed](#research-gaps-addressed)
- [Author](#author)

---

## Overview

CertChain is a graduate thesis project developed at **Florida A&M University** for the
**Cyber Defense Certificate (FCCS)** certificate program. The system automates
the micro-credential issuance process — a process that currently requires manual administrative
review — by combining natural language processing, a weighted eligibility scoring algorithm,
and a permissioned blockchain network.

The system processes raw student transcript text, automatically determines eligibility using
a trained BERT model and a multi-factor scoring function, and conditionally issues a
tamper-proof micro-credential onto a Hyperledger Fabric ledger. All issued credentials are
additionally signed using CRYSTALS-Dilithium3 post-quantum cryptography, making them
cryptographically valid against future quantum computing threats. Credentials can also be
batched into a Merkle Mountain Range and anchored on-chain, so a verifier can audit many
credentials against one compact root instead of one hash lookup at a time — additive to,
not a replacement for, the existing per-credential verification.

---

## Thesis Contributions

| # | Layer | Contribution Type | Description | Evaluation Metric |
|---|-------|------------------|-------------|-------------------|
| 1 | Layer 1 | **Algorithm** | Fine-tuned BERT classifier for FCCS course identification from transcript text | Precision, Recall, F1 vs. regex baseline |
| 2 | Layer 2 | **Algorithm** | Weighted multi-factor eligibility scoring function encoded on-chain | FPR, FNR vs. binary threshold baseline |
| 3 | Layer 3 | **System** | Hyperledger Fabric + IPFS + REST API + Kubernetes deployment on NRP | Latency (ms), Throughput (TPS) |
| 4 | PQ Layer | **Novel Gap** | CRYSTALS-Dilithium3 post-quantum signatures on credential hashes | No reviewed micro-credentialing paper addresses this |
| 5 | Integrity Layer | **Novel Gap** | Merkle Mountain Range batch anchoring — audits many credentials against one compact on-chain root, on top of the existing per-credential hash lookup | Proof size vs. batch size; on-chain inclusion-proof verification |
| 6 | Sampling Layer | **Algorithm** | Round-based sampling audit over the MMR (without-replacement, exponential per-round growth) reusing the existing inclusion-proof check per sampled item | Empirically measured Pv via Monte Carlo (not assumed from source paper); items checked / payload / time vs. full verification |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1 — NLP ALGORITHM                                     │
│                                                              │
│  Input : Raw unstructured transcript text                    │
│  Model : Fine-tuned BERT (bert-base-uncased)                 │
│  Output: FCCS course codes + BERT confidence score           │
│  File  : nlp/bert_classifier.py                              │
│  Metric: Precision / Recall / F1 vs. regex baseline          │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 2 — SCORING ALGORITHM                                 │
│                                                              │
│  Formula: 0.40 × (GPA/4.0)                                   │
│         + 0.40 × (courses_completed/5)                       │
│         + 0.20 × (bert_confidence)                           │
│  Threshold: Score ≥ 0.70 → ELIGIBLE                          │
│  File  : chaincode/certchain.js (_computeScore)              │
│  Metric: False Positive Rate / False Negative Rate           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 3 — SYSTEM                                            │
│                                                              │
│  Blockchain : Hyperledger Fabric 2.5 (permissioned)          │
│  Storage    : IPFS off-chain + SHA-256 hash on-chain         │
│  Identity   : X.509 certificates with role attributes        │
│  API        : REST + JSON-LD (schema.org) responses          │
│  Deploy     : NRP Kubernetes + GitHub Actions CI/CD          │
│  Metric     : Latency / Throughput                           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  POST-QUANTUM LAYER                                          │
│                                                              │
│  Algorithm : CRYSTALS-Dilithium3 (NIST FIPS 204 / ML-DSA)   │
│  Signs     : Credential hash at issuance time                │
│  Purpose   : Quantum-resilient verification                  │
│  File      : quantum/pq_signer.py                            │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  MMR INTEGRITY LAYER (additive — does not replace CRED~hash) │
│                                                              │
│  Structure : Merkle Mountain Range over batched credHashes   │
│  Batching  : per institution / per issuance day or week      │
│  On-chain  : MMRROOT~<batchId>, separate from CRED~<hash>    │
│  Root      : recomputed on-chain from supplied leaves —      │
│              a mismatched caller-claimed root is rejected    │
│  Verifies  : one credential against a whole batch's root,    │
│              via an on-chain-checked inclusion proof          │
│  File      : chaincode/mmr.js                                │
└──────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
certchain/
│
├── .github/
│   └── workflows/
│       └── certchain.yml          # GitHub Actions CI/CD pipeline
│
├── chaincode/
│   ├── certchain.js               # Hyperledger Fabric smart contract
│   │                              # Contains Layer 2 weighted scoring algorithm
│   │                              # Role-based access control, JSON-LD output
│   │                              # Audit log, program analytics, MMR anchoring
│   └── mmr.js                     # Merkle Mountain Range core (build/prove/verify)
│                                  # Required by both certchain.js and api/server.js
│
├── nlp/
│   ├── bert_classifier.py         # BERT model — training and inference (Layer 1)
│   └── transcript_parser.py       # Combines BERT + regex GPA extraction
│
├── quantum/
│   └── pq_signer.py               # CRYSTALS-Dilithium3 post-quantum signatures
│
├── wallet/
│   └── wallet_setup.js            # X.509 identity enrollment and role assignment
│
├── storage/
│   └── ipfs_storage.js            # IPFS off-chain document storage
│
├── api/
│   ├── server.js                  # REST API with JSON-LD credential endpoints
│   └── mmr_sampling.js            # Sampling audit: sampler, confidence formula,
│                                  # round-loop orchestrator (shared with the
│                                  # evaluation harness below)
│
├── dataset/
│   └── data_loader.py             # Synthetic dataset generator + Kaggle drop-in
│
├── evaluation/
│   ├── evaluate_nlp.py            # Layer 1: BERT vs. regex baseline
│   ├── evaluate_scoring.py        # Layer 2: weighted vs. binary threshold
│   ├── evaluate_system.py         # Layer 3: latency and throughput
│   └── evaluate_mmr_sampling.js   # Layer 5: empirically measures Pv via
│                                  # Monte Carlo simulation
│
├── integration/
│   ├── pipeline.py                # End-to-end pipeline (all layers + PQ)
│   └── mmr_anchor.py              # Batch-selects + anchors an MMR root; can
│                                  # round-trip an inclusion proof as a smoke test
│
├── k8s/
│   └── nrp-deployment.yaml        # Kubernetes manifests for NRP deployment
│
├── config/
│   └── connection.json            # Hyperledger Fabric connection profile
│
└── requirements.txt               # Python dependencies
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Linux (Ubuntu 22.04+) | — | Operating system |
| Python | 3.10+ | NLP, dataset, evaluation |
| Node.js | 18+ | Chaincode, API, wallet |
| Docker | 24+ | Hyperledger Fabric containers |
| Go | 1.21+ | Fabric peer tools |
| poppler-utils | any | `pdftoppm` — OCR fallback for scanned transcript PDFs (optional; without it, scanned PDFs with no text layer fail with a clear error instead of silently producing empty text) |
| Git | any | Version control |

---

## Installation

### Step 1 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/certchain.git
cd certchain
```

### Step 2 — Install Python dependencies

```bash
pip3 install -r requirements.txt
```

### Step 3 — Install Node.js dependencies

```bash
cd chaincode  && npm install fabric-contract-api fabric-shim
cd ../api     && npm install express body-parser fabric-network fabric-ca-client \
                       helmet express-rate-limit cors bcryptjs \
                       multer pdf-parse mammoth tesseract.js
cd ../wallet  && npm install fabric-network fabric-ca-client
cd ../storage && npm install ipfs-http-client
cd ..
```

### Step 4 — Download Hyperledger Fabric

```bash
cd ~
curl -sSL https://bit.ly/2ysbOFE | bash -s -- 2.5.0 1.5.7
```

---

## Usage

### 1. Generate the Dataset

```bash
# Synthetic (default — no external data needed)
python3 dataset/data_loader.py --mode synthetic --n 200

# Kaggle dataset (when available — see Kaggle Dataset section)
python3 dataset/data_loader.py --mode kaggle --file dataset/kaggle/your_file.csv
```

### 2. Train the BERT Model

```bash
python3 nlp/bert_classifier.py \
  --train \
  --data dataset/output/sentence_labels.json \
  --model nlp/model
```

### 3. Start the Fabric Network

```bash
cd ~/fabric-samples/test-network
./network.sh up createChannel -c certchainchannel -ca
./network.sh deployCC -ccn certchain -ccp ~/certchain/chaincode/ -ccl javascript
```

### 4. Copy Connection Profile and Enroll Identities

```bash
mkdir -p ~/certchain/config
cp ~/fabric-samples/test-network/organizations/peerOrganizations/org1.example.com/connection-org1.json \
   ~/certchain/config/connection.json

cd ~/certchain
node -e "
const w = require('./wallet/wallet_setup');
(async()=>{
  await w.enrollAdmin();
  await w.registerUser({ userID:'famu-institution', role:'institution' });
  await w.registerUser({ userID:'public-verifier',  role:'verifier'     });
  await w.registerUser({ userID:'FAMU10001',         role:'student'      });
})();
"
```

### 5. Start the API Server

```bash
node api/server.js
# Running on http://localhost:3000
```

### 6. Run the Full Pipeline

```bash
# Single transcript
python3 integration/pipeline.py \
  --transcript path/to/transcript.txt \
  --student FAMU10001

# Batch — all students
python3 integration/pipeline.py \
  --batch dataset/output/transcripts.json \
  --output results.json
```

### 7. Anchor an MMR Batch

Run this on whatever cadence fits the deployment (daily/weekly cron, or after
each institution's issuance run). It selects credentials not yet in a batch,
anchors their MMR root, and can optionally round-trip an inclusion proof:

```bash
export CERTCHAIN_USER=famu-institution
export CERTCHAIN_PASSWORD=...

python3 integration/mmr_anchor.py --since 2026-07-30T00:00:00Z

# or, anchor and immediately verify one credential's inclusion proof
python3 integration/mmr_anchor.py --verify <credHash>
```

### 8. Upload a Transcript File

Instead of running `pipeline.py` against a local text file, an institution can
upload a PDF/DOCX/TXT transcript directly. Text extraction happens in Node
(`api/transcript_extract.js`); scanned PDFs with no text layer fall back to
OCR via `pdftoppm` + `tesseract.js`. Processing runs asynchronously — extraction
plus a Python subprocess (which may load a BERT model) is not fast enough to
hold an HTTP request open for, so the response is an `uploadID` to poll:

```bash
curl -X POST http://localhost:3000/transcripts/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "studentID=FAMU10001" \
  -F "transcript=@transcript.pdf"
# {"uploadID": "...", "status": "processing"}

curl http://localhost:3000/transcripts/status/<uploadID> \
  -H "Authorization: Bearer $TOKEN"
# {"uploadID": "...", "status": "complete", "result": { ... }}
```

`status` on the job record means "finished running," not "credential issued" —
check `result.status` (`ISSUED`, `NOT_ELIGIBLE`, `MANUAL_REVIEW`, `REJECTED`, or
`API_UNAVAILABLE`) for the actual outcome. A malformed file, empty extraction,
or oversized upload always surfaces as an explicit error on the job or an
immediate 4xx — never a silently-dropped upload.

**Course-code mismatch — resolved.** Without a trained BERT model,
`nlp/transcript_parser.py` falls back to a regex parser. It previously
extracted `NSA####`-style codes that `api/server.js`'s course-code allowlist
(`CIS`/`CNT`/`COP`-prefixed) rejected outright, so neither this upload path
nor the pre-existing `pipeline.py --transcript` CLI path could ever reach
`ISSUED` in a fresh environment with no trained model. The fallback parser
now matches the five official Cyber Defense Certificate course codes
(formatting-tolerant: `CIS4385C` / `CIS 4385C` / `CIS-4385C`) or their
distinguishing title keywords (e.g. "Digital Forensics") directly — see
`COURSE_PATTERNS` in `nlp/transcript_parser.py`. The allowlist in
`api/server.js` was not changed; it was already correct.

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET`  | `/health` | None | Health check |
| `POST` | `/issue` | institution | Issue credential from NLP payload |
| `POST` | `/transcripts/upload` | institution | Upload PDF/DOCX/TXT transcript — extracts text, runs it through the full pipeline asynchronously |
| `GET`  | `/transcripts/status/:uploadID` | institution | Poll an upload's processing status/result |
| `GET`  | `/verify/:hash` | verifier | Verify credential — returns JSON-LD |
| `GET`  | `/student/:id` | student | All credentials for a student |
| `POST` | `/revoke` | institution | Revoke a credential |
| `GET`  | `/analytics?as=...` | institution | Program-level analytics |
| `GET`  | `/mmr/unanchored?since=...` | institution | Credentials not yet in an MMR batch |
| `POST` | `/mmr/anchor` | institution | Anchor a batch's MMR root on-chain |
| `GET`  | `/mmr/root/:batchId` | any | Fetch a batch's anchored root |
| `GET`  | `/mmr/batch/:batchId/members` | any | List a batch's credentials in leaf order |
| `GET`  | `/mmr/proof/:batchId/:credHash` | any | Get an inclusion proof for one credential |
| `POST` | `/mmr/verify` | any | Verify an inclusion proof against the anchored root |
| `GET`  | `/verify-batch?batchId=&sampleSize=&rounds=` | any | Statistical sampling audit of a batch (see below) |

### Example — Verify a Credential

```bash
curl http://localhost:3000/verify/abc123def456...
```

**Response (JSON-LD):**
```json
{
  "@context": "https://schema.org/",
  "@type": "EducationalOccupationalCredential",
  "isValid": true,
  "credentialStatus": "ACTIVE",
  "credentialCategory": "micro-credential",
  "recognizedBy": "famu.edu",
  "educationalProgram": "FAMU-FCCS",
  "competencyRequired": ["CIS4385C", "CIS4360", "CIS4361"],
  "eligibilityScore": 0.84,
  "postQuantumSigned": true,
  "pqAlgorithm": "CRYSTALS-Dilithium3"
}
```

---

## Evaluation

Run all three evaluations after the system is operational. These produce your Chapter 4 thesis results.

```bash
# Layer 1 — BERT vs. regex baseline (Precision / Recall / F1)
python3 evaluation/evaluate_nlp.py \
  --data dataset/output/sentence_labels.json \
  --model nlp/model

# Layer 2 — Weighted scoring vs. binary threshold (FPR / FNR)
python3 evaluation/evaluate_scoring.py \
  --data dataset/output/structured_dataset.csv

# Layer 3 — System performance (Latency / Throughput)
python3 evaluation/evaluate_system.py \
  --api http://localhost:3000 \
  --n 50

# Layer 5 — MMR sampling verification accuracy (Pv, empirically measured)
node evaluation/evaluate_mmr_sampling.js
```

Results are saved to:
- `evaluation/nlp_results.json`
- `evaluation/scoring_results.json`
- `evaluation/system_results.json`
- `evaluation/mmr_sampling_results.json`

---

## Sampling-Based Batch Verification

On top of the MMR batch anchoring above, `GET /verify-batch?batchId=&sampleSize=&rounds=`
audits a batch statistically instead of checking every credential: each round samples
`sampleSize` items **without replacement**, sample size **doubles each round** (exponential
growth, clamped to batch size), and every sampled item is checked with the existing
`verifyMMRInclusion` on-chain proof check — sampling decides *what* to check, it does not
change *how* a single item is verified. This is additive to, not a replacement for, full
per-credential verification (`/verify/:hash`, `/mmr/verify`).

After `r` rounds, confidence is reported as `Lc = 1 - (1 - Pv)^r`. **Pv is not an assumed
constant** — it is measured empirically by `evaluation/evaluate_mmr_sampling.js`, a Monte
Carlo harness that seeds a batch with a known tampered item and measures how often the real
sampling code (not a reimplementation) catches it. Current measured result:

| Parameter | Value |
|-----------|-------|
| Batch size | 1,000 |
| Tampered items seeded | 1 |
| Base sample size / growth / rounds | 5, ×2, 5 |
| Per-round sample sizes | 5, 10, 20, 40, 80 (15.5% of batch total) |
| Monte Carlo trials | 20,000 |
| Empirical 5-round catch rate | **0.1482** |
| Backed-out per-round Pv | **0.0316** |

Read plainly: at this batch size, a single tampered credential has roughly a **15% chance**
of being caught by the default protocol. That's the honest, measured number, not a design
target — raising `sampleSize`/`rounds` trades more per-item checks for higher confidence.
Re-run the harness after changing those defaults; `api/mmr_sampling.js` documents how the
constant is derived and where to update it.

**Sampling vs. full verification** (measured locally, N=1,000 credential batch, defaults above):

| | Full (`/mmr/verify` × N) | Sampling (`/verify-batch`, defaults) |
|---|---|---|
| Items checked | 1,000 | 155 |
| Total proof payload | ~1,344,000 bytes | ~206,700 bytes |
| Local proof gen + verify time | ~117 ms | ~18 ms |
| Reduction | — | ~85% fewer checks, payload, and compute time |

Per-proof size is ~1.3–1.4 KB regardless of which mode is used (proof size scales with
`log(batch size)`, not with how many items are checked) — the savings come entirely from
checking fewer items, not from cheaper individual proofs. These are local computation
figures only; there's no live Fabric network in this environment to measure real
transaction round-trip latency, which would dominate wall-clock time in a deployed system.

---

## Kaggle Dataset

When you find a relevant dataset on Kaggle, integrating it requires three steps:

1. Download the CSV and place it in `dataset/kaggle/`
2. Open `dataset/data_loader.py` and fill in `KAGGLE_COLUMN_MAP` with your CSV's actual column names:

```python
KAGGLE_COLUMN_MAP = {
    'student_id': 'StudentID',    # your column name here
    'name':       'StudentName',  # your column name here
    'gpa':        'GPA',          # your column name here
    'courses':    'Courses',      # your column name here
    ...
}
```

3. Run:

```bash
python3 dataset/data_loader.py --mode kaggle --file dataset/kaggle/your_file.csv
```

All downstream components (BERT retraining, pipeline, evaluations) run without any other changes.

---

## NRP Deployment

Access to the National Research Platform is obtained through your faculty advisor.

Once access is approved:

```bash
# Create namespace
kubectl create namespace certchain

# Deploy all components
kubectl apply -f k8s/nrp-deployment.yaml -n certchain

# Check status
kubectl get pods -n certchain
kubectl get services -n certchain
```

To enable automatic deployment via GitHub Actions, add your NRP kubeconfig as a repository secret:

```
GitHub → Settings → Secrets and Variables → Actions → New repository secret
Name:  NRP_KUBECONFIG
Value: (contents of your kubeconfig file)
```

The BERT training job in `k8s/nrp-deployment.yaml` runs on NRP GPU nodes, reducing training time from 30 minutes (CPU) to under 5 minutes.

---

## Supervisor Customization

All key parameters are centralized in two files:
`chaincode/certchain.js` and `nlp/transcript_parser.py`

| Parameter | Variable Name | Default |
|-----------|--------------|---------|
| Minimum GPA | `MIN_GPA` | `3.0` |
| Minimum courses required | `MIN_COURSES` | `3` |
| Scoring weight — GPA | `W1` | `0.40` |
| Scoring weight — Courses | `W2` | `0.40` |
| Scoring weight — BERT confidence | `W3` | `0.20` |
| Eligibility threshold | `THRESHOLD` | `0.70` |
| BERT confidence gate | `MIN_CONF` in `pipeline.py` | `0.60` |
| Dataset size | `--n` flag | `200` |
| BERT training epochs | `EPOCHS` in `bert_classifier.py` | `4` |

---

## Research Gaps Addressed

| Gap | Source Paper | CertChain Solution |
|-----|-------------|--------------------|
| No automated transcript parsing | Blockchain Micro-Credential SLR | BERT classifier + pipeline |
| Lack of interoperability (41.7%) | Gap Analysis on Blockchain Frameworks | REST API + JSON-LD responses |
| Security concerns (41.7%) | Gap Analysis on Blockchain Frameworks | RBAC + IPFS off-chain + audit log |
| Blockchain and analytics treated separately | Empowering Home Tutors paper | Unified NLP-to-chain pipeline |
| No domain-specific systems | Blockchain Credentialing for Teachers | FCCS-specific implementation at FAMU |
| No post-quantum cryptography in micro-credentialing | Blockchain Forensics SLR (gap) | CRYSTALS-Dilithium3 signature layer |

---

## Author

**Javonte Carter**
Graduate Student, Computer Science
Florida A&M University

Thesis: *CertChain: A Blockchain-Based Micro-Credentialing Framework with NLP-Driven Eligibility Evaluation and Post-Quantum Cryptographic Security for Cybersecurity Certificate Programs*

---

## Acknowledgments

- Hyperledger Foundation — Fabric framework
- Hugging Face — BERT pretrained models
- NIST Post-Quantum Cryptography Standardization Project — CRYSTALS-Dilithium3
- National Research Platform (NRP) / Nautilus HyperCluster — compute infrastructure
- Florida A&M University — FCCS (Cyber Defense Certificate) program

---

*For setup instructions, see the [CertChain Build Guide](CertChain_Build_Guide.docx).*
