'use strict';
/**
 * CertChain — 1:1 Hash-Pointer vs. MMR(+Sampling) Verification: Comparison (Layer 5)
 * ====================================================================================
 * Compares CertChain's original per-credential verification scheme
 * (verifyCredential: one ledger read keyed by `CRED~<hash>`, no proof
 * object — the ledger key itself IS the hash pointer) against the MMR
 * batch-anchoring layer added on top of it (chaincode/mmr.js,
 * anchorMMRRoot/verifyMMRInclusion in chaincode/certchain.js), both in
 * "check every item" mode and in sampling mode (api/mmr_sampling.js).
 *
 * Run against the actual transcript dataset (dataset/data_loader.py's
 * synthetic FCCS generator, not synthetic placeholder hashes like
 * evaluate_mmr_sampling.js uses) — this builds the exact on-chain
 * credential JSON shape issueMicroCredential() constructs, from real
 * eligible_payloads.json records, so credential sizes and hash inputs
 * are representative of production content, not stand-ins.
 *
 * This is local computation only — it reuses chaincode/mmr.js and
 * api/mmr_sampling.js directly (same code the live endpoints run), and
 * measures proof sizes / local generate+verify time. It does NOT measure
 * real Fabric transaction round-trip latency — there is no live network
 * in this environment. Ledger-read/write COUNTS below are structural
 * (how many state accesses each scheme requires), not timed network
 * calls.
 *
 * Run: node evaluation/evaluate_hashpointer_vs_mmr.js [batchSize]
 * Saves: evaluation/hashpointer_vs_mmr_results.json
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { buildMMR, generateProof, verifyProof } = require('../chaincode/mmr');
const {
    DEFAULT_PV, DEFAULT_BASE_SAMPLE_SIZE, DEFAULT_ROUNDS, DEFAULT_GROWTH_FACTOR,
    computeConfidence, runSamplingRounds,
} = require('../api/mmr_sampling');

const REPO_ROOT = path.join(__dirname, '..');
const PAYLOADS_PATH = path.join(REPO_ROOT, 'dataset', 'output', 'eligible_payloads.json');

// Mirrors chaincode/certchain.js exactly (PROGRAM, ISSUER, W1/W2/W3, THRESHOLD)
// so the credential objects hashed here are byte-for-byte what issueMicroCredential
// would put on the ledger, not an approximation.
const PROGRAM = 'FAMU-FCCS';
const ISSUER = 'famu.edu';
const W1 = 0.40, W2 = 0.40, W3 = 0.20;
const THRESHOLD = 0.70;

function computeScore(gpa, courses, bertConfidence) {
    const score = W1 * (parseFloat(gpa) / 4.0) +
                  W2 * (courses.length / 5.0) +
                  W3 * (parseFloat(bertConfidence || 0));
    return {
        score: Math.round(score * 10000) / 10000,
        breakdown: {
            gpa_component: Math.round(W1 * (parseFloat(gpa) / 4.0) * 10000) / 10000,
            course_component: Math.round(W2 * (courses.length / 5.0) * 10000) / 10000,
            bert_component: Math.round(W3 * (parseFloat(bertConfidence || 0)) * 10000) / 10000,
        },
    };
}

function buildCredential(payload, idx) {
    const scoring = computeScore(payload.gpa, payload.courses_completed, payload.bert_confidence);
    const credentialID = `CERTCHAIN-${payload.student_id}-${idx.toString(16).padStart(8, '0')}`;
    const credential = {
        credentialID,
        studentID: payload.student_id,
        issuerID: ISSUER,
        program: PROGRAM,
        courses_completed: payload.courses_completed,
        prerequisite_verified: 'COP3014C',
        eligibility_score: scoring.score,
        score_breakdown: scoring.breakdown,
        issuedAt: new Date(Date.now() - idx * 1000).toISOString(),
        status: 'ACTIVE',
        revokedAt: null,
        revocationReason: null,
        ipfs_cid: null,
        pq_signature: null,
        pq_public_key: null,
        pq_algorithm: 'CRYSTALS-Dilithium3 (NIST FIPS 204 / ML-DSA-65)',
        jsonld_context: 'https://schema.org/',
        jsonld_type: 'EducationalOccupationalCredential',
    };
    const credHash = crypto.createHash('sha256').update(JSON.stringify(credential)).digest('hex');
    return { credential, credHash };
}

function loadDataset() {
    if (!fs.existsSync(PAYLOADS_PATH)) {
        console.log(`${PAYLOADS_PATH} not found — generating synthetic dataset via dataset/data_loader.py...`);
        execFileSync('python3', ['dataset/data_loader.py', '--mode', 'synthetic', '--n', '1700'], {
            cwd: REPO_ROOT, stdio: 'inherit',
        });
    }
    return JSON.parse(fs.readFileSync(PAYLOADS_PATH, 'utf8'));
}

function bytesOf(obj) {
    return Buffer.byteLength(JSON.stringify(obj), 'utf8');
}

function run(batchSize) {
    const payloads = loadDataset();
    if (payloads.length === 0) {
        throw new Error('eligible_payloads.json is empty — no eligible synthetic students generated.');
    }
    const n = Math.min(batchSize, payloads.length);
    const items = payloads.slice(0, n).map((p, i) => buildCredential(p, i));
    const credHashes = items.map(it => it.credHash);

    // ── Scheme A: 1:1 hash-pointer (current production verifyCredential) ──────
    // One ledger read per credential, keyed directly by its hash. No proof
    // object exists in this scheme — the response IS the full stored record.
    const schemeA = {
        name: '1:1 hash-pointer (verifyCredential)',
        itemsChecked: n,
        ledgerReads: n,
        totalResponseBytes: items.reduce((sum, it) => sum + bytesOf(it.credential), 0),
        avgResponseBytes: Math.round(items.reduce((sum, it) => sum + bytesOf(it.credential), 0) / n),
    };

    // ── Scheme B: MMR, full inclusion-proof verification of every item ────────
    const buildStart = process.hrtime.bigint();
    const mmr = buildMMR(credHashes);
    const buildMs = Number(process.hrtime.bigint() - buildStart) / 1e6;

    const proofGenStart = process.hrtime.bigint();
    const proofs = credHashes.map((h, i) => generateProof(mmr, i));
    const proofGenMs = Number(process.hrtime.bigint() - proofGenStart) / 1e6;

    const verifyStart = process.hrtime.bigint();
    let allValid = true;
    proofs.forEach((proof, i) => {
        if (!verifyProof(credHashes[i], proof)) allValid = false;
    });
    const verifyMs = Number(process.hrtime.bigint() - verifyStart) / 1e6;

    const totalProofBytes = proofs.reduce((sum, p) => sum + bytesOf(p), 0);
    const schemeB = {
        name: 'MMR full inclusion-proof verification',
        itemsChecked: n,
        // 1 write to anchor the root (once per batch) + 1 read to fetch the
        // anchored root for cross-checking (cacheable across all N proofs,
        // not re-fetched per item) — NOT N reads like scheme A.
        ledgerWrites: 1,
        ledgerReads: 1,
        allProofsValid: allValid,
        buildMMRMs: Math.round(buildMs * 100) / 100,
        proofGenMs: Math.round(proofGenMs * 100) / 100,
        proofVerifyMs: Math.round(verifyMs * 100) / 100,
        totalProofBytes,
        avgProofBytes: Math.round(totalProofBytes / n),
    };

    const indexOf = new Map(credHashes.map((h, i) => [h, i]));
    return { n, items, credHashes, mmr, proofs, schemeA, schemeB, indexOf };
}

async function runSampling({ n, credHashes, mmr, proofs, indexOf }) {
    let sampledProofBytes = 0;
    const start = process.hrtime.bigint();
    const result = await runSamplingRounds({
        items: credHashes,
        baseSampleSize: DEFAULT_BASE_SAMPLE_SIZE,
        rounds: DEFAULT_ROUNDS,
        growthFactor: DEFAULT_GROWTH_FACTOR,
        verifyOne: async (item) => {
            const i = indexOf.get(item);
            const proof = proofs[i];
            sampledProofBytes += bytesOf(proof);
            return verifyProof(item, proof);
        },
    });
    const elapsedMs = Number(process.hrtime.bigint() - start) / 1e6;
    const lc = computeConfidence(DEFAULT_PV, DEFAULT_ROUNDS);

    return {
        name: 'MMR + sampling (api/mmr_sampling.js defaults)',
        itemsChecked: result.itemsChecked,
        itemsCheckedFraction: Math.round((result.itemsChecked / n) * 10000) / 10000,
        ledgerWrites: 1,
        ledgerReads: 1,
        totalProofBytes: sampledProofBytes,
        avgProofBytes: Math.round(sampledProofBytes / result.itemsChecked),
        proofVerifyMs: Math.round(elapsedMs * 100) / 100,
        confidenceLevel: Math.round(lc * 10000) / 10000,
        confidenceLevelProvenance: `computeConfidence(DEFAULT_PV=${DEFAULT_PV}, rounds=${DEFAULT_ROUNDS}) — ` +
            'DEFAULT_PV itself is empirically measured, see evaluation/evaluate_mmr_sampling.js',
    };
}

(async () => {
    const batchSize = parseInt(process.argv[2], 10) || 1000;
    console.log(`Loading real synthetic transcript dataset and building ${batchSize} on-chain-shaped credentials...\n`);

    const { n, schemeA, schemeB, credHashes, mmr, proofs, indexOf } = run(batchSize);
    const schemeC = await runSampling({ n, credHashes, mmr, proofs, indexOf });

    console.log('='.repeat(72));
    console.log(`CertChain — 1:1 Hash-Pointer vs. MMR(+Sampling), N=${n} real dataset credentials`);
    console.log('='.repeat(72));
    console.log('\nScheme A —', schemeA.name);
    console.log(`  Ledger reads:          ${schemeA.ledgerReads}`);
    console.log(`  Total response bytes:  ${schemeA.totalResponseBytes.toLocaleString()}`);
    console.log(`  Avg response bytes:    ${schemeA.avgResponseBytes}`);

    console.log('\nScheme B —', schemeB.name);
    console.log(`  Ledger writes (anchor): ${schemeB.ledgerWrites}`);
    console.log(`  Ledger reads (root):    ${schemeB.ledgerReads}`);
    console.log(`  All ${n} proofs valid:    ${schemeB.allProofsValid}`);
    console.log(`  Build MMR time:         ${schemeB.buildMMRMs} ms`);
    console.log(`  Proof gen time:         ${schemeB.proofGenMs} ms`);
    console.log(`  Proof verify time:      ${schemeB.proofVerifyMs} ms`);
    console.log(`  Total proof bytes:      ${schemeB.totalProofBytes.toLocaleString()}`);
    console.log(`  Avg proof bytes:        ${schemeB.avgProofBytes}`);

    console.log('\nScheme C —', schemeC.name);
    console.log(`  Items checked:          ${schemeC.itemsChecked} / ${n} (${(schemeC.itemsCheckedFraction * 100).toFixed(1)}%)`);
    console.log(`  Ledger writes (anchor): ${schemeC.ledgerWrites}`);
    console.log(`  Ledger reads (root):    ${schemeC.ledgerReads}`);
    console.log(`  Total proof bytes:      ${schemeC.totalProofBytes.toLocaleString()}`);
    console.log(`  Proof verify time:      ${schemeC.proofVerifyMs} ms`);
    console.log(`  Confidence level (Lc):  ${schemeC.confidenceLevel}`);

    console.log('\n' + '-'.repeat(72));
    console.log('Reduction vs. Scheme A (bytes transferred, checking the whole batch):');
    console.log(`  B/A: ${((1 - schemeB.totalProofBytes / schemeA.totalResponseBytes) * 100).toFixed(1)}% fewer bytes`);
    console.log(`  C/A: ${((1 - schemeC.totalProofBytes / schemeA.totalResponseBytes) * 100).toFixed(1)}% fewer bytes`);
    console.log('-'.repeat(72));
    console.log('\nNote: Scheme A\'s response includes the FULL credential record (courses,');
    console.log('score breakdown, IPFS CID, PQ signature fields, etc). Scheme B/C proofs only');
    console.log('prove hash membership in the anchored batch root — they do not carry the');
    console.log('credential\'s human-readable fields. In a real deployment, a verifier using');
    console.log('MMR mode would still need one supplementary fetch (e.g. from IPFS, not a');
    console.log('second ledger transaction) to display those fields. This comparison measures');
    console.log('verification cost, not "does the verifier see the same information" — those');
    console.log('are different questions.');

    const outPath = path.join(__dirname, 'hashpointer_vs_mmr_results.json');
    fs.writeFileSync(outPath, JSON.stringify({ batchSize: n, schemeA, schemeB, schemeC }, null, 2));
    console.log(`\nSaved to ${outPath}`);
})();
