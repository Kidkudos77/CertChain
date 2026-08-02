'use strict';
/**
 * CertChain — MORES Sidecar Client (Phase 7 — cryptographic core implemented)
 * ================================================================================
 * Thin HTTP client for crypto/mores_service.py. KGen/Enc/TGen resolve
 * synchronously (no pairings involved, fast). Cmp is async: cmp() kicks off
 * the sidecar's background job and returns a jobId immediately; cmpStatus()
 * polls it; cmpWait() is a convenience wrapper that polls on an interval
 * until the job finishes — same uploadID+polling shape api/server.js
 * already uses for transcript uploads. Do not call cmp() and assume the
 * result is ready synchronously: a real comparison is minutes, not
 * milliseconds, in pure-Python py_ecc (see mores_core.py's docstring).
 *
 * Same pattern as api/mmr_sampling.js calling into chaincode/mmr.js: one
 * client module, reused by anything in the Node side that needs to reach
 * MORES (the API server, and the additive IPFS integration point in
 * storage/ipfs_storage.js).
 */
const http = require('http');

const MORES_HOST = process.env.MORES_HOST || '127.0.0.1';
const MORES_PORT = parseInt(process.env.MORES_PORT || '5100', 10);

function request(method, route, body, timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
        const payload = body !== undefined ? Buffer.from(JSON.stringify(body || {})) : null;
        const headers = payload
            ? { 'Content-Type': 'application/json', 'Content-Length': payload.length }
            : {};
        const req = http.request({
            host: MORES_HOST, port: MORES_PORT, path: route, method, headers, timeout: timeoutMs,
        }, (res) => {
            let data = '';
            res.on('data', chunk => { data += chunk; });
            res.on('end', () => {
                try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
                catch (e) { reject(new Error('MORES sidecar returned malformed JSON.')); }
            });
        });
        req.on('error', (e) => reject(new Error(`MORES sidecar unreachable at ${MORES_HOST}:${MORES_PORT} (is crypto/mores_service.py running?): ${e.message}`)));
        req.on('timeout', () => { req.destroy(); reject(new Error('MORES sidecar request timed out.')); });
        if (payload) req.write(payload);
        req.end();
    });
}

const callMores = (route, body) => request('POST', route, body); // kept for /ore/status's existing diagnostic use

const health = ()             => request('POST', '/mores/health', {});
const kgen = ()               => request('POST', '/mores/kgen', {});
const enc  = (msk, x, n, lam) => request('POST', '/mores/enc',  { msk, x, n, lam });
const tgen = (qk, y, n, lam)  => request('POST', '/mores/tgen', { qk, y, n, lam });
const cmp  = (ctx, ty)        => request('POST', '/mores/cmp',  { ctx, ty });
const cmpStatus = (jobId)     => request('GET',  `/mores/cmp/status/${encodeURIComponent(jobId)}`);

// Polls cmpStatus until the job is done/errored or timeoutMs elapses.
// Real comparisons take tens of seconds to several minutes depending on
// bit-width (see mores_core.py) — callers doing this synchronously in an
// HTTP request handler should use the async job pattern instead
// (return jobId to the client, let the client poll GET /mores/cmp/status).
async function cmpWait(ctx, ty, { pollIntervalMs = 2000, timeoutMs = 300000 } = {}) {
    const start = await cmp(ctx, ty);
    if (!start.body || !start.body.ok) return start;
    const jobId = start.body.result.jobId;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const poll = await cmpStatus(jobId);
        const status = poll.body && poll.body.result && poll.body.result.status;
        if (status === 'done' || status === 'error') return poll;
        await new Promise(r => setTimeout(r, pollIntervalMs));
    }
    throw new Error(`MORES Cmp job ${jobId} did not finish within ${timeoutMs}ms.`);
}

module.exports = { health, kgen, enc, tgen, cmp, cmpStatus, cmpWait, callMores };
