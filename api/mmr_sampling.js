'use strict';
/**
 * CertChain — MMR Sampling Verification
 * =========================================
 * On top of the existing MMR batch anchoring (chaincode/mmr.js,
 * anchorMMRRoot/verifyMMRInclusion), this adds a second, additive
 * verification mode: instead of checking every credential in a batch,
 * check a randomly-selected subset across several rounds and report a
 * statistical confidence that the batch is intact.
 *
 * Protocol (from "A secured accreditation and equivalency certification
 * using Merkle mountain range..."):
 *   - Round r samples M_r items from the batch WITHOUT replacement.
 *   - Sample size grows across rounds (exponential here: M_r = M0 * 2^(r-1),
 *     clamped to the batch size — doubling is the simplest exponential
 *     growth and needs no extra tuning parameter beyond M0).
 *   - Each sampled item is checked with the EXISTING single-item proof
 *     verification (verifyMMRInclusion) — sampling does not introduce a
 *     new trust mechanism, it just decides which items to check.
 *   - After r rounds: confidenceLevel = 1 - (1 - Pv)^r.
 *
 * Pv is not an assumed constant. It is measured empirically by
 * evaluation/evaluate_mmr_sampling.js (Monte Carlo simulation using this
 * exact module, with a single known-tampered item seeded into a batch)
 * and the resulting value is recorded below in DEFAULT_PV, with its
 * provenance. See that file for how to reproduce or update the number.
 */
const crypto = require('crypto');

// ── Empirically measured verification accuracy ─────────────────────────────
// Measured by evaluation/evaluate_mmr_sampling.js (batchSize=1000,
// tamperedCount=1, baseSampleSize=5, rounds=5, growthFactor=2, trials=20000):
//   round sample sizes: 5, 10, 20, 40, 80 (15.5% of the batch total)
//   empirical 5-round catch rate (Lc_empirical): 0.1482
// Pv is backed out via Pv = 1 - (1-Lc_empirical)^(1/rounds) so that
// plugging Pv back into Lc = 1-(1-Pv)^rounds reproduces the measured
// 5-round figure exactly at rounds=5. See evaluation/mmr_sampling_results.json
// for the full run this was taken from.
//
// This value is calibrated for that (baseSampleSize, rounds, growthFactor,
// batchSize) shape. Requests using very different parameters still use
// this same Pv — it is an approximation outside the calibration point, not
// a per-request recomputation. Re-run the harness and update this constant
// if the defaults below change.
//
// Read honestly: at this batch size, a single tampered item in a batch of
// 1000 has only a ~15% chance of being caught by the default 5-round/
// 15.5%-coverage protocol. That is a real result, not a design goal —
// raising baseSampleSize/rounds trades more per-check cost for higher
// confidence; see the harness for how to explore that tradeoff.
const DEFAULT_PV = 0.0316;
const DEFAULT_PV_PROVENANCE =
    'Empirically measured via evaluation/evaluate_mmr_sampling.js ' +
    '(batchSize=1000, tamperedCount=1, baseSampleSize=5, rounds=5, growthFactor=2, trials=20000); ' +
    'Lc_empirical=0.1482 at rounds=5, backed out to per-round Pv';

const DEFAULT_BASE_SAMPLE_SIZE = 5;
const DEFAULT_ROUNDS           = 5;
const DEFAULT_GROWTH_FACTOR    = 2;

// ── Sampler ──────────────────────────────────────────────────────────────────
// Sample size for a given round, exponential growth, clamped to batch size.
function sampleSizeForRound(baseSampleSize, round, growthFactor, batchSize) {
    const raw = Math.round(baseSampleSize * Math.pow(growthFactor, round - 1));
    return Math.max(1, Math.min(raw, batchSize));
}

// Uniform random index in [0, max) via a CSPRNG — sampling which items get
// audited is a security-relevant choice (a predictable sampler could be
// gamed by an adversary who knows which items will never be checked), so
// this deliberately does not use Math.random().
function secureRandomIndex(max) {
    return crypto.randomInt(0, max);
}

// Fisher-Yates partial shuffle — picks `m` items without replacement from
// `items`, without mutating the caller's array.
function sampleWithoutReplacement(items, m) {
    const pool = items.slice();
    const n    = pool.length;
    const take = Math.max(0, Math.min(m, n));
    for (let i = 0; i < take; i++) {
        const j = i + secureRandomIndex(n - i);
        [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    return pool.slice(0, take);
}

// ── Confidence ──────────────────────────────────────────────────────────────
function computeConfidence(pv, rounds) {
    return 1 - Math.pow(1 - pv, rounds);
}

// ── Round loop ──────────────────────────────────────────────────────────────
// `verifyOne(item)` is injected so this exact orchestration logic is
// reusable both by the live /verify-batch endpoint (verifyOne calls the
// real chaincode) and by the offline Pv-measurement harness (verifyOne
// checks against a known ground truth) — one implementation, no risk of
// the two diverging.
async function runSamplingRounds({ items, baseSampleSize, rounds, growthFactor = DEFAULT_GROWTH_FACTOR, verifyOne }) {
    if (!Array.isArray(items) || items.length === 0) {
        throw new Error('runSamplingRounds requires a non-empty items array.');
    }
    const batchSize    = items.length;
    const perRound      = [];
    const itemsFlagged  = [];
    let itemsChecked    = 0;

    for (let round = 1; round <= rounds; round++) {
        const m      = sampleSizeForRound(baseSampleSize, round, growthFactor, batchSize);
        const sample = sampleWithoutReplacement(items, m);
        let flaggedCount = 0;

        for (const item of sample) {
            itemsChecked++;
            const ok = await verifyOne(item);
            if (!ok) {
                flaggedCount++;
                itemsFlagged.push({ round, item });
            }
        }
        perRound.push({ round, sampleSize: sample.length, flaggedCount });
    }

    return { roundsRun: rounds, itemsChecked, itemsFlagged, perRound };
}

module.exports = {
    DEFAULT_PV,
    DEFAULT_PV_PROVENANCE,
    DEFAULT_BASE_SAMPLE_SIZE,
    DEFAULT_ROUNDS,
    DEFAULT_GROWTH_FACTOR,
    sampleSizeForRound,
    sampleWithoutReplacement,
    computeConfidence,
    runSamplingRounds,
};
