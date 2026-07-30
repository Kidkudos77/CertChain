'use strict';
/**
 * CertChain — Merkle Mountain Range (MMR) core
 * ===============================================
 * Credentials are batched (per institution, per issuance day/week — the
 * caller's choice, see anchorMMRRoot in certchain.js) into an append-only
 * Merkle Mountain Range. Only the resulting root gets written to the
 * ledger. This gives a verifier a second, additive way to audit a
 * credential: instead of (or in addition to) a single O(1) hash lookup
 * via verifyCredential(), they can request an inclusion proof and check
 * one credential against a compact root that covers an entire batch.
 *
 * Domain-separated hashing (RFC 6962-style) stops a leaf hash from being
 * replayed as an internal node hash or vice versa:
 *   leaf hash   = sha256(0x00 || input)
 *   parent hash = sha256(0x01 || left || right)
 *
 * This file has no dependencies beyond Node's built-in `crypto`, so it is
 * required directly — unmodified — by both:
 *   - chaincode/certchain.js  (packaged with the chaincode, runs on-chain)
 *   - api/server.js           (off-chain batch building + proof serving)
 * One implementation, no risk of the two sides drifting apart.
 */
const crypto = require('crypto');

function sha256Hex(buf) {
    return crypto.createHash('sha256').update(buf).digest('hex');
}

function leafHash(input) {
    return sha256Hex(Buffer.concat([Buffer.from([0x00]), Buffer.from(String(input), 'utf8')]));
}

function parentHash(leftHex, rightHex) {
    return sha256Hex(Buffer.concat([
        Buffer.from([0x01]),
        Buffer.from(leftHex, 'hex'),
        Buffer.from(rightHex, 'hex'),
    ]));
}

// Fold the peak list (left = largest subtree first) into one root hash.
// Must be applied identically at build time and verify time.
function bagPeaks(peaks) {
    if (!peaks || peaks.length === 0) return null;
    let bagged = peaks[peaks.length - 1];
    for (let i = peaks.length - 2; i >= 0; i--) {
        bagged = parentHash(peaks[i], bagged);
    }
    return bagged;
}

/**
 * Build an MMR from an ordered list of leaf inputs (e.g. credHash strings).
 * Uses the standard append algorithm: push a new leaf as a peak, then
 * merge same-height peaks (mirrors binary-counter carrying) until no two
 * adjacent peaks share a height. Returns enough bookkeeping to generate an
 * inclusion proof for any leaf by its append-order index.
 */
function buildMMR(leafInputs) {
    if (!Array.isArray(leafInputs) || leafInputs.length === 0) {
        throw new Error('buildMMR requires a non-empty array of leaf inputs.');
    }

    const nodeHash       = new Map();  // position -> hash hex
    const nodeHeight      = new Map(); // position -> height (0 = leaf)
    const parentOf        = new Map(); // child position -> parent position
    const siblingOf        = new Map();// child position -> { pos, side } (side = sibling's side relative to child)
    const leafPositions    = [];
    let peakStack           = [];      // stack of {pos, height}
    let position             = 0;

    for (const input of leafInputs) {
        const h = leafHash(input);
        nodeHash.set(position, h);
        nodeHeight.set(position, 0);
        leafPositions.push(position);
        peakStack.push({ pos: position, height: 0 });
        position++;

        while (peakStack.length >= 2 &&
               peakStack[peakStack.length - 1].height === peakStack[peakStack.length - 2].height) {
            const right = peakStack.pop();
            const left  = peakStack.pop();
            const ph    = parentHash(nodeHash.get(left.pos), nodeHash.get(right.pos));
            const newHeight = left.height + 1;
            nodeHash.set(position, ph);
            nodeHeight.set(position, newHeight);
            parentOf.set(left.pos, position);
            parentOf.set(right.pos, position);
            siblingOf.set(left.pos,  { pos: right.pos, side: 'right' });
            siblingOf.set(right.pos, { pos: left.pos,  side: 'left'  });
            peakStack.push({ pos: position, height: newHeight });
            position++;
        }
    }

    const peaks = peakStack.map(p => nodeHash.get(p.pos));
    const root  = bagPeaks(peaks);

    return { nodeHash, nodeHeight, parentOf, siblingOf, leafPositions, peakStack, peaks, root };
}

/**
 * Generate an inclusion proof for leafIndex (0-based, in append order)
 * against an MMR returned by buildMMR().
 */
function generateProof(mmr, leafIndex) {
    if (leafIndex < 0 || leafIndex >= mmr.leafPositions.length) {
        throw new Error(`leafIndex ${leafIndex} out of range.`);
    }
    const leafPos = mmr.leafPositions[leafIndex];
    const path = [];
    let cur = leafPos;
    while (mmr.parentOf.has(cur)) {
        const sib = mmr.siblingOf.get(cur);
        path.push({ hash: mmr.nodeHash.get(sib.pos), side: sib.side });
        cur = mmr.parentOf.get(cur);
    }
    const peakIndex = mmr.peakStack.findIndex(p => p.pos === cur);
    return {
        leafIndex,
        leafInputHash: mmr.nodeHash.get(leafPos),
        path,
        peaks: mmr.peaks.slice(),
        peakIndex,
        root: mmr.root,
    };
}

/**
 * Verify that `input` (e.g. a credHash string) is included in the MMR
 * described by `proof`, and that the proof bags to `proof.root`.
 *
 * This function only checks internal consistency of the proof — it does
 * NOT know what the real anchored root is. Callers (chaincode or client)
 * MUST separately compare `proof.root` against the root actually stored
 * on-chain under MMRROOT~<batchId>; otherwise a proof that is internally
 * consistent but anchored to nothing would pass.
 */
function verifyProof(input, proof) {
    if (!proof || !Array.isArray(proof.path) || !Array.isArray(proof.peaks)) return false;
    let h = leafHash(input);
    if (proof.leafInputHash && proof.leafInputHash !== h) return false;
    for (const step of proof.path) {
        if (!step || typeof step.hash !== 'string') return false;
        h = step.side === 'left' ? parentHash(step.hash, h) : parentHash(h, step.hash);
    }
    if (typeof proof.peakIndex !== 'number' || proof.peakIndex < 0 || proof.peakIndex >= proof.peaks.length) {
        return false;
    }
    if (proof.peaks[proof.peakIndex] !== h) return false;
    const recomputedRoot = bagPeaks(proof.peaks);
    return recomputedRoot === proof.root;
}

module.exports = { leafHash, parentHash, bagPeaks, buildMMR, generateProof, verifyProof };

// ── Self-test ─────────────────────────────────────────────────────────────────
// Run directly (`node chaincode/mmr.js`) to sanity-check the algorithm:
// every leaf in a batch must produce a valid proof, and tampering with a
// proof (wrong leaf, flipped sibling hash, wrong root) must fail.
if (require.main === module) {
    const leaves = ['CREDHASH-0','CREDHASH-1','CREDHASH-2','CREDHASH-3','CREDHASH-4'];
    const mmr    = buildMMR(leaves);
    console.log(`Built MMR — ${leaves.length} leaves, ${mmr.peaks.length} peak(s), root ${mmr.root}`);

    let allOk = true;
    leaves.forEach((leaf, i) => {
        const proof = generateProof(mmr, i);
        const ok    = verifyProof(leaf, proof);
        console.log(`  leaf[${i}] proof valid: ${ok}`);
        allOk = allOk && ok;
    });

    const forgedProof = generateProof(mmr, 0);
    const tamperedLeaf = verifyProof('NOT-A-REAL-CREDENTIAL', forgedProof);
    const tamperedPath  = generateProof(mmr, 0);
    tamperedPath.path[0].hash = leafHash('junk');
    const tamperedPathOk = verifyProof(leaves[0], tamperedPath);
    const tamperedRoot  = generateProof(mmr, 0);
    tamperedRoot.root = leafHash('wrong-root');
    const tamperedRootOk = verifyProof(leaves[0], tamperedRoot);

    console.log(`  forged leaf correctly rejected: ${tamperedLeaf === false}`);
    console.log(`  tampered path correctly rejected: ${tamperedPathOk === false}`);
    console.log(`  tampered root correctly rejected: ${tamperedRootOk === false}`);

    const pass = allOk && tamperedLeaf === false && tamperedPathOk === false && tamperedRootOk === false;
    console.log(pass ? '\nSELF-TEST PASSED' : '\nSELF-TEST FAILED');
    process.exit(pass ? 0 : 1);
}
