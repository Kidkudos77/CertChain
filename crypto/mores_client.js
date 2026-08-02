'use strict';
/**
 * CertChain — MORES Sidecar Client (Phase 7 scaffolding)
 * ===========================================================
 * Thin HTTP client for crypto/mores_service.py. Every call currently
 * resolves the sidecar's clean { ok:false, error: <stub notice> } / HTTP
 * 501 response — this module's job is the transport wiring, not the
 * cryptography. Swapping the sidecar's stub function bodies for real
 * MORES later requires no changes here.
 *
 * Same pattern as api/mmr_sampling.js calling into chaincode/mmr.js: one
 * client module, reused by anything in the Node side that needs to reach
 * MORES (the API server, and the additive IPFS integration point in
 * storage/ipfs_storage.js).
 */
const http = require('http');

const MORES_HOST = process.env.MORES_HOST || '127.0.0.1';
const MORES_PORT = parseInt(process.env.MORES_PORT || '5100', 10);

function callMores(route, body) {
    return new Promise((resolve, reject) => {
        const payload = Buffer.from(JSON.stringify(body || {}));
        const req = http.request({
            host: MORES_HOST, port: MORES_PORT, path: route, method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Length': payload.length },
            timeout: 10000,
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
        req.write(payload);
        req.end();
    });
}

const kgen = ()        => callMores('/mores/kgen', {});
const enc  = (msk, x)  => callMores('/mores/enc',  { msk, x });
const tgen = (qk, y)   => callMores('/mores/tgen', { qk, y });
const cmp  = (ctx, ty) => callMores('/mores/cmp',  { ctx, ty });

module.exports = { kgen, enc, tgen, cmp, callMores };
