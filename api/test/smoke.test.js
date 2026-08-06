'use strict';
/**
 * CertChain — API smoke test
 * ===============================
 * Starts the real api/server.js (with a mocked wallet/Fabric contract, same
 * pattern used ad hoc throughout this project's development) and exercises
 * the actual HTTP routes end-to-end: /health, /auth, /issue, /verify/:hash,
 * /mmr/anchor + /mmr/root. No external test framework — plain Node, exits
 * non-zero on any failure, directly CI-usable.
 *
 * Backs up and restores the real api/users.json around the test run (this
 * suite registers real throwaway users through the real /auth routes) so
 * running it on a developer's own clone doesn't leave test users behind —
 * same discipline used manually throughout this project's development,
 * just made automatic and permanent here.
 *
 * Run: node api/test/smoke.test.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const TEST_PORT = process.env.SMOKE_TEST_PORT || '3993';
process.env.PORT = TEST_PORT;
const BASE = `http://localhost:${TEST_PORT}`;

const ROOT = path.join(__dirname, '..', '..');
const USERS_PATH = path.join(ROOT, 'api', 'users.json');
const USERS_BACKUP = USERS_PATH + '.smoke-test-backup';

// ── Mock Fabric contract, backed by an in-memory ledger + the real chaincode ─
const CertChain = require(path.join(ROOT, 'chaincode', 'certchain.js'));
const mmrLib = require(path.join(ROOT, 'chaincode', 'mmr.js'));
const contractInstance = new CertChain();
const mockLedger = new Map();
let txCounter = 0;
const mockStub = {
    getState: async (key) => { const v = mockLedger.get(key); return v !== undefined ? Buffer.from(v) : Buffer.alloc(0); },
    putState: async (key, value) => { mockLedger.set(key, value.toString()); },
    deleteState: async (key) => { mockLedger.delete(key); },
    getTxID: () => 'tx' + (txCounter++),
    setEvent: () => {},
    createCompositeKey: (prefix, parts) => `${prefix} ${parts.join(' ')}`,
    getStateByPartialCompositeKey: async (prefix, parts) => {
        const searchPrefix = `${prefix} ${parts.join(' ')}`;
        const matches = [];
        for (const [key, value] of mockLedger.entries()) {
            if (key.startsWith(searchPrefix)) matches.push({ value: Buffer.from(value) });
        }
        let i = 0;
        return { next: async () => (i < matches.length ? { value: matches[i++], done: false } : { done: true }), close: async () => {} };
    },
};
let currentRole = 'institution';
const mockCtx = {
    stub: mockStub,
    clientIdentity: { getAttributeValue: () => currentRole, getID: () => 'x509::CN=smoke-test' },
};
const mockContract = {
    submitTransaction: async (fn, ...args) => Buffer.from(await contractInstance[fn](mockCtx, ...args)),
    evaluateTransaction: async (fn, ...args) => Buffer.from(await contractInstance[fn](mockCtx, ...args)),
};

const walletPath = require.resolve(path.join(ROOT, 'wallet', 'wallet_setup.js'));
require.cache[walletPath] = {
    id: walletPath, filename: walletPath, loaded: true,
    exports: { getContract: async () => ({ contract: mockContract, gateway: { disconnect: async () => {} } }) },
};

let failures = 0;
function assert(cond, msg) {
    if (!cond) { failures++; console.log('FAIL: ' + msg); }
    else { console.log('ok:   ' + msg); }
}

async function login(auth, userID, password) {
    const r = await fetch(`${BASE}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userID, password }),
    });
    const body = await r.json();
    return body.token;
}

async function run() {
    fs.copyFileSync(USERS_PATH, USERS_BACKUP);
    try {
        const auth = require(path.join(ROOT, 'api', 'auth.js'));
        require(path.join(ROOT, 'api', 'server.js'));
        await new Promise(r => setTimeout(r, 500));

        const suffix = Date.now();
        const pw = 'SmokeTestPassw0rd!';
        const store = JSON.parse(fs.readFileSync(USERS_PATH, 'utf8'));
        store.users.push(
            { userID: `smoke-institution-${suffix}`, name: 'Smoke Institution', email: `inst${suffix}@test.local`, passwordHash: await auth.hashPassword(pw), role: 'institution', status: 'active', createdAt: new Date().toISOString() },
            { userID: `smoke-verifier-${suffix}`, name: 'Smoke Verifier', email: `ver${suffix}@test.local`, passwordHash: await auth.hashPassword(pw), role: 'verifier', status: 'active', createdAt: new Date().toISOString() },
        );
        fs.writeFileSync(USERS_PATH, JSON.stringify(store, null, 2));

        // GET /health
        {
            const r = await fetch(`${BASE}/health`);
            assert(r.status === 200, 'GET /health returns 200');
        }

        const instToken = await login(auth, `smoke-institution-${suffix}`, pw);
        const verifierToken = await login(auth, `smoke-verifier-${suffix}`, pw);
        assert(typeof instToken === 'string' && instToken.length > 0, 'institution login returns a token');
        assert(typeof verifierToken === 'string' && verifierToken.length > 0, 'verifier login returns a token');

        // POST /issue
        currentRole = 'institution';
        const nlpPayload = {
            gpa: 3.8, courses_completed: ['CIS4385C', 'CIS4360', 'CIS4361'],
            prerequisite_completed: true, bert_confidence: 0.92, eligibility_score: 0.85,
            student_name: 'Smoke Test Student',
        };
        let credHash;
        {
            const r = await fetch(`${BASE}/issue`, {
                method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${instToken}` },
                body: JSON.stringify({ studentID: `FAMU-SMOKE-${suffix}`, nlpPayload }),
            });
            const body = await r.json();
            assert(r.status === 201 && body.success === true, `POST /issue succeeds end-to-end (got ${r.status})`);
            credHash = body.credHash;
        }

        // GET /verify/:hash
        currentRole = 'verifier';
        {
            const r = await fetch(`${BASE}/verify/${credHash}`, { headers: { Authorization: `Bearer ${verifierToken}` } });
            const body = await r.json();
            assert(r.status === 200 && body.isValid === true, 'GET /verify/:hash confirms the issued credential is valid');
        }

        // POST /mmr/anchor + GET /mmr/root/:batchId
        currentRole = 'institution';
        const batchId = `smoke-batch-${suffix}`;
        {
            const built = mmrLib.buildMMR([credHash]);
            const r = await fetch(`${BASE}/mmr/anchor`, {
                method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${instToken}` },
                body: JSON.stringify({ batchId, credHashes: [credHash] }),
            });
            const body = await r.json();
            assert(r.status === 201 && body.success === true, `POST /mmr/anchor succeeds (got ${r.status})`);
        }
        {
            const r = await fetch(`${BASE}/mmr/root/${batchId}`, { headers: { Authorization: `Bearer ${instToken}` } });
            const body = await r.json();
            assert(r.status === 200 && body.batchId === batchId, 'GET /mmr/root/:batchId returns the just-anchored root');
        }

        console.log('\n' + (failures === 0 ? 'ALL API SMOKE TESTS PASSED' : `${failures} FAILURE(S)`));
    } finally {
        fs.copyFileSync(USERS_BACKUP, USERS_PATH);
        fs.unlinkSync(USERS_BACKUP);
    }
    process.exit(failures === 0 ? 0 : 1);
}

run().catch(e => {
    console.error('HARNESS ERROR:', e);
    if (fs.existsSync(USERS_BACKUP)) { fs.copyFileSync(USERS_BACKUP, USERS_PATH); fs.unlinkSync(USERS_BACKUP); }
    process.exit(1);
});
