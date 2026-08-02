'use strict';
/**
 * CertChain — MMR Sampling Verification: Empirical Evaluation (Layer 5)
 * ==========================================================================
 * Measures Pv (the per-round formula in api/mmr_sampling.js's
 * computeConfidence: Lc = 1-(1-Pv)^r) empirically via Monte Carlo
 * simulation, instead of assuming a value from the source paper.
 *
 * Method: seed a batch of `batchSize` items with `tamperedCount` known-bad
 * items, run the real r-round sampling protocol (runSamplingRounds from
 * api/mmr_sampling.js — the exact same code the live endpoint uses) many
 * times, and measure the fraction of full r-round runs that flag at least
 * one tampered item. That empirical r-round catch rate is Lc_empirical.
 * Pv is then backed out via Pv = 1 - (1-Lc_empirical)^(1/r), so plugging
 * it back into the paper's formula reproduces Lc_empirical at that r.
 *
 * This is a JS harness (not Python, like the other evaluate_*.py scripts)
 * because it must reuse api/mmr_sampling.js and chaincode/mmr.js directly
 * — reimplementing the sampler in Python would risk it silently drifting
 * from the code actually running in production.
 *
 * The MMR proof-tamper-detection mechanism itself (does a forged/altered
 * proof get rejected?) is already exhaustively verified elsewhere — see
 * chaincode/mmr.js's self-test and the mock-ledger harness used to build
 * the MMR anchoring layer. What this harness measures is a different,
 * purely statistical question: given that detection is 100% reliable
 * *per item checked*, what fraction of items get checked, and how often
 * does random sampling land on the tampered one? So "verification" here
 * is mocked as a ground-truth lookup (is this item in the tampered set?)
 * rather than re-running real proof generation per sample — that isolates
 * the sampling statistics from the (separately proven) cryptography.
 *
 * Run: node evaluation/evaluate_mmr_sampling.js
 * Saves: evaluation/mmr_sampling_results.json
 */
const fs = require('fs');
const path = require('path');
const { runSamplingRounds, computeConfidence, sampleSizeForRound } = require('../api/mmr_sampling');

function makeBatch(batchSize) {
    return Array.from({ length: batchSize }, (_, i) => `CRED-${i}`);
}

function pickTamperedSet(items, tamperedCount) {
    const shuffled = items.slice();
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return new Set(shuffled.slice(0, tamperedCount));
}

async function runTrial({ items, tamperedCount, baseSampleSize, rounds, growthFactor }) {
    const tampered = pickTamperedSet(items, tamperedCount);
    const verifyOne = async (item) => !tampered.has(item); // ground-truth mock, see header
    const result = await runSamplingRounds({ items, baseSampleSize, rounds, growthFactor, verifyOne });
    return { caught: result.itemsFlagged.length > 0, itemsChecked: result.itemsChecked };
}

async function measurePv({ batchSize, tamperedCount, baseSampleSize, rounds, growthFactor, trials }) {
    const items = makeBatch(batchSize);
    let caughtCount = 0;
    let totalItemsChecked = 0;

    for (let t = 0; t < trials; t++) {
        const { caught, itemsChecked } = await runTrial({ items, tamperedCount, baseSampleSize, rounds, growthFactor });
        if (caught) caughtCount++;
        totalItemsChecked += itemsChecked;
    }

    const lcEmpirical = caughtCount / trials;
    // Back out the per-round Pv that reproduces this measured r-round rate
    // in the paper's formula: Lc = 1-(1-Pv)^rounds
    const pvEffective = 1 - Math.pow(1 - lcEmpirical, 1 / rounds);

    // Theoretical single-round catch rate for round 1 only, for context —
    // hypergeometric with tamperedCount=1 simplifies to M/N.
    const round1Size = sampleSizeForRound(baseSampleSize, 1, growthFactor, batchSize);
    const theoreticalRound1Pv = tamperedCount === 1 ? round1Size / batchSize : null;

    const avgItemsChecked = totalItemsChecked / trials;
    const perRoundSizes = Array.from({ length: rounds }, (_, i) =>
        sampleSizeForRound(baseSampleSize, i + 1, growthFactor, batchSize));

    return {
        config: { batchSize, tamperedCount, baseSampleSize, rounds, growthFactor, trials },
        perRoundSampleSizes: perRoundSizes,
        totalSampledPerRun: perRoundSizes.reduce((a, b) => a + b, 0),
        sampledFractionOfBatch: perRoundSizes.reduce((a, b) => a + b, 0) / batchSize,
        avgItemsChecked,
        lcEmpirical,
        pvEffective,
        theoreticalRound1Pv,
        lcFromEffectivePv: computeConfidence(pvEffective, rounds), // sanity check — should equal lcEmpirical
    };
}

(async () => {
    const config = {
        batchSize:      1000,
        tamperedCount:  1,
        baseSampleSize: 5,
        rounds:         5,
        growthFactor:   2,
        trials:         20000,
    };

    console.log(`Running ${config.trials} Monte Carlo trials — batchSize=${config.batchSize}, ` +
                `tamperedCount=${config.tamperedCount}, baseSampleSize=${config.baseSampleSize}, ` +
                `rounds=${config.rounds}, growthFactor=${config.growthFactor}...\n`);

    const result = await measurePv(config);

    console.log('Per-round sample sizes:', result.perRoundSampleSizes);
    console.log(`Total sampled per run: ${result.totalSampledPerRun} / ${config.batchSize} ` +
                `(${(result.sampledFractionOfBatch * 100).toFixed(1)}% of batch)`);
    console.log(`Empirical ${config.rounds}-round catch rate (Lc_empirical): ${result.lcEmpirical.toFixed(4)}`);
    console.log(`Backed-out per-round Pv:                                   ${result.pvEffective.toFixed(4)}`);
    console.log(`Theoretical round-1-only Pv (M1/N, single tampered item):  ${result.theoreticalRound1Pv.toFixed(4)}`);
    console.log(`Sanity check — Lc from Pv formula at rounds=${config.rounds}:              ${result.lcFromEffectivePv.toFixed(4)}`);

    const outPath = path.join(__dirname, 'mmr_sampling_results.json');
    fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
    console.log(`\nSaved to ${outPath}`);
})();
