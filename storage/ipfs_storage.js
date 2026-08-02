'use strict';
/** CertChain — IPFS Off-Chain Storage
 *  Full document → IPFS. Only SHA-256 hash → ledger.
 *  Integrity verified by re-hashing on retrieval.
 */
const { create } = require('ipfs-http-client');
const crypto     = require('crypto');
const fs         = require('fs');
const mores      = require('../crypto/mores_client');

const ipfs = create({ host:'localhost', port:5001, protocol:'http' });

async function storeDocument(obj) {
    const content = JSON.stringify(obj);
    const sha256  = crypto.createHash('sha256').update(content).digest('hex');
    const result  = await ipfs.add(content, { pin:true });
    return { cid:result.path, sha256Hash:sha256 };
}

// ── MORES integration point (Phase 7 scaffolding — cryptographic core
// paused) ─────────────────────────────────────────────────────────────────
// Additive, not a replacement: storeDocument() above is untouched and is
// still what every existing caller uses. This shows exactly where a GPA/
// score field would get MORES-encrypted — before the document is
// stringified and hashed, same insertion point as the FERPA-field hashing
// already happening in storeDocument(). Right now Enc() is a stub
// (crypto/mores_service.py) that always 501s, so calling this with an
// institutionMsk will always throw until the cryptographic core lands —
// that's intentional; it proves the hook is wired to the real stub, not a
// fake success path. Once MORES is implemented, this becomes the function
// callers switch to — a one-function change, not a re-architecture.
async function storeDocumentWithMORES(obj, { institutionMsk } = {}) {
    if (!institutionMsk || typeof obj.gpa !== 'number') {
        return storeDocument(obj); // MORES not engaged — identical to today's behavior
    }
    const { body } = await mores.enc(institutionMsk, obj.gpa);
    if (!body.ok) {
        throw new Error(`MORES encryption unavailable: ${body.error}`);
    }
    const encrypted = { ...obj, gpa_mores_ciphertext: body.result };
    delete encrypted.gpa; // plaintext GPA no longer travels into IPFS once this is real
    return storeDocument(encrypted);
}

async function retrieveDocument(cid, expectedHash) {
    const chunks = [];
    for await (const chunk of ipfs.cat(cid)) chunks.push(chunk);
    const content  = Buffer.concat(chunks).toString();
    const computed = crypto.createHash('sha256').update(content).digest('hex');
    if (computed !== expectedHash) return { verified:false, document:null };
    return { verified:true, document:JSON.parse(content) };
}

async function storeFile(filePath) {
    const buf    = fs.readFileSync(filePath);
    const sha256 = crypto.createHash('sha256').update(buf).digest('hex');
    const result = await ipfs.add(buf, { pin:true });
    return { cid:result.path, sha256Hash:sha256 };
}

module.exports = { storeDocument, retrieveDocument, storeFile, storeDocumentWithMORES };
