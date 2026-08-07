'use strict';
/**
 * CertChain — chaincode unit test suite
 * ==========================================
 * Formalizes the mock-ledger pattern used ad hoc throughout this project's
 * development into a permanent, committed test suite, so "does the
 * chaincode still behave correctly" doesn't depend on someone re-deriving
 * a test harness from scratch each time. No external test framework
 * (jest/mocha) — plain Node, asserts via a small local helper, exits
 * non-zero on any failure so it's directly CI-usable.
 *
 * MockStub mirrors the real fabric-shim ChaincodeStub API precisely where
 * it matters for correctness, not just where convenient:
 *   - getState/putState/deleteState/getStateByPartialCompositeKey are
 *     async (real Fabric: async).
 *   - createCompositeKey is SYNCHRONOUS (real Fabric: synchronous — it's a
 *     pure string builder). chaincode/certchain.js correctly never awaits
 *     it; an earlier version of this mock made it async, which would have
 *     silently turned every composite key into a Promise object instead
 *     of a string wherever the real code (correctly) doesn't await it —
 *     a mock bug that could mask real chaincode bugs. Fixed before this
 *     became a permanent, trusted test suite.
 *
 * Run: node chaincode/test/certchain.test.js
 */
const CertChain = require('../certchain.js');
const mmr = require('../mmr.js');

class MockStub {
    constructor() { this.state = new Map(); this.txCounter = 0; }
    async getState(key) { const v = this.state.get(key); return v !== undefined ? Buffer.from(v) : Buffer.alloc(0); }
    async putState(key, value) { this.state.set(key, value.toString()); }
    async deleteState(key) { this.state.delete(key); }
    getTxID() { return 'tx' + (this.txCounter++); }
    setEvent() {}
    createCompositeKey(prefix, parts) { return `${prefix} ${parts.join(' ')}`; }
    // Inverse of createCompositeKey above — real fabric-shim uses \x00
    // delimiters and a length-prefixed encoding; this mock's composite keys
    // are plain space-joined strings (see the certchain.test.js NUL-byte
    // fix), so splitting on ' ' is the correct inverse for THIS mock.
    splitCompositeKey(key) {
        const parts = key.split(' ');
        return { objectType: parts[0], attributes: parts.slice(1) };
    }
    async getStateByPartialCompositeKey(prefix, parts) {
        const searchPrefix = `${prefix} ${parts.join(' ')}`;
        const matches = [];
        for (const [key, value] of this.state.entries()) {
            if (key.startsWith(searchPrefix)) matches.push({ key, value: Buffer.from(value) });
        }
        let i = 0;
        return {
            next: async () => (i < matches.length ? { value: matches[i++], done: false } : { done: true }),
            close: async () => {},
        };
    }
    // Real fabric-shim returns keys in lexicographic order — sorted here so
    // range-scanning code (getAllCredentials, getProgramAnalytics, etc.)
    // exercises the same ordering assumption it would against a real ledger.
    async getStateByRange(startKey, endKey) {
        const matches = [...this.state.entries()]
            .filter(([key]) => key >= startKey && key < endKey)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            .map(([key, value]) => ({ key, value: Buffer.from(value) }));
        let i = 0;
        return {
            next: async () => (i < matches.length ? { value: matches[i++], done: false } : { done: true }),
            close: async () => {},
        };
    }
}

function mockCtx(role, id = 'x509::CN=test') {
    const stub = new MockStub();
    return {
        stub,
        clientIdentity: {
            getAttributeValue: (name) => (name === 'role' ? role : null),
            getID: () => id,
        },
    };
}

let failures = 0;
function assert(cond, msg) {
    if (!cond) { failures++; console.log('FAIL: ' + msg); }
    else { console.log('ok:   ' + msg); }
}

const ELIGIBLE_PAYLOAD = {
    gpa: 3.75,
    courses_completed: ['CIS4385C', 'CIS4360', 'CIS4361'],
    prerequisite_completed: true,
    bert_confidence: 0.9,
};

async function issue(contract, ctx, studentID, overrides = {}) {
    const payload = { ...ELIGIBLE_PAYLOAD, ...overrides };
    const raw = await contract.issueMicroCredential(ctx, studentID, JSON.stringify(payload));
    return JSON.parse(raw);
}

async function testIssuance() {
    console.log('\n--- issueMicroCredential ---');
    const contract = new CertChain();

    {
        const ctx = mockCtx('institution');
        const result = await issue(contract, ctx, 'FAMU10001');
        assert(result.success === true, 'eligible payload is issued');
        assert(typeof result.credHash === 'string' && result.credHash.length === 64, 'returns a sha256 credHash');
    }
    {
        const ctx = mockCtx('institution');
        const result = await issue(contract, ctx, 'FAMU10002', { gpa: 2.0 });
        assert(result.success === false && /GPA/.test(result.reason), 'low GPA rejected with GPA-specific reason');
    }
    {
        const ctx = mockCtx('institution');
        const result = await issue(contract, ctx, 'FAMU10003', { courses_completed: ['CIS4385C'] });
        assert(result.success === false && /FCCS courses/.test(result.reason), 'insufficient course count rejected');
    }
    {
        const ctx = mockCtx('institution');
        const result = await issue(contract, ctx, 'FAMU10004', { prerequisite_completed: false });
        assert(result.success === false && /COP3014C/.test(result.reason), 'missing prerequisite rejected, GPA/course checks not reached first');
    }
    {
        const ctx = mockCtx('student');
        let threw = false;
        try { await issue(contract, ctx, 'FAMU10005'); }
        catch (e) { threw = true; }
        assert(threw, 'student role cannot issue (role gate enforced)');
    }
    return contract;
}

async function testVerification(contract) {
    console.log('\n--- verifyCredential ---');
    const issueCtx = mockCtx('institution');
    const issued = await issue(contract, issueCtx, 'FAMU20001');

    {
        const ctx = mockCtx('verifier');
        ctx.stub.state = issueCtx.stub.state; // share ledger state across ctx objects, same pattern as a real shared world state
        const raw = await contract.verifyCredential(ctx, issued.credHash);
        const result = JSON.parse(raw);
        assert(result.isValid === true, 'freshly issued credential verifies as valid');
    }
    {
        const ctx = mockCtx('verifier');
        ctx.stub.state = issueCtx.stub.state;
        const raw = await contract.verifyCredential(ctx, '0'.repeat(64));
        const result = JSON.parse(raw);
        assert(result.isValid === false && result.message === 'Credential not found on ledger.', 'unknown hash reports not-found, not a crash');
    }
    {
        const ctx = mockCtx('institution');
        ctx.stub.state = issueCtx.stub.state;
        await contract.revokeCredential(ctx, issued.credHash, 'Test revocation');
        const verifyCtx = mockCtx('verifier');
        verifyCtx.stub.state = issueCtx.stub.state;
        const raw = await contract.verifyCredential(verifyCtx, issued.credHash);
        const result = JSON.parse(raw);
        assert(result.isValid === false && result.credentialStatus === 'REVOKED', 'revoked credential fails verification with REVOKED status');
    }
}

async function testGetStudentCredentials(contract) {
    console.log('\n--- getStudentCredentials ---');
    const issueCtx = mockCtx('institution');
    const issued1 = await issue(contract, issueCtx, 'FAMU50001');
    const issued2 = await issue(contract, issueCtx, 'FAMU50001', { gpa: 3.9 });
    await issue(contract, issueCtx, 'FAMU50002'); // different student — must not leak in

    const studentCtx = mockCtx('student', 'x509::CN=FAMU50001');
    studentCtx.stub.state = issueCtx.stub.state;
    const raw = await contract.getStudentCredentials(studentCtx, 'FAMU50001');
    const results = JSON.parse(raw);
    const hashes = results.map(r => r.credentialHash);

    assert(results.length === 2, 'getStudentCredentials returns exactly this student\'s 2 credentials');
    assert(hashes.includes(issued1.credHash) && hashes.includes(issued2.credHash),
        'both of the student\'s credential hashes are present');
    assert(results.every(r => r.isValid === true), 'both returned credentials verify as valid');

    // Backs the employer "Search Candidate" flow (GET /student/:id) — a
    // verifier must be able to call this, not just the student/institution/
    // admin. Regression check for a real role-gate gap found via a live
    // browser-driven test.
    const verifierCtx = mockCtx('verifier');
    verifierCtx.stub.state = issueCtx.stub.state;
    const verifierRaw = await contract.getStudentCredentials(verifierCtx, 'FAMU50001');
    assert(JSON.parse(verifierRaw).length === 2, 'verifier role can call getStudentCredentials (employer candidate search)');
}

async function testListAndRevoke(contract) {
    console.log('\n--- getAllCredentials + revokeCredential ---');
    const issueCtx = mockCtx('institution');
    const issued1 = await issue(contract, issueCtx, 'FAMU40001');
    const issued2 = await issue(contract, issueCtx, 'FAMU40002', { gpa: 3.5 });

    {
        const listCtx = mockCtx('institution');
        listCtx.stub.state = issueCtx.stub.state;
        const raw = await contract.getAllCredentials(listCtx);
        const result = JSON.parse(raw);
        const hashes = result.credentials.map(c => c.credHash);
        assert(hashes.includes(issued1.credHash) && hashes.includes(issued2.credHash),
            'getAllCredentials lists issued credentials including their credHash');
        assert(result.credentials.every(c => c.status === 'ACTIVE'),
            'freshly issued credentials list as ACTIVE');
    }
    {
        const studentCtx = mockCtx('student');
        studentCtx.stub.state = issueCtx.stub.state;
        let threw = false;
        try { await contract.getAllCredentials(studentCtx); }
        catch (e) { threw = true; }
        assert(threw, 'student role cannot list all credentials (role gate enforced)');
    }
    {
        const revokeCtx = mockCtx('institution');
        revokeCtx.stub.state = issueCtx.stub.state;
        await contract.revokeCredential(revokeCtx, issued1.credHash, 'Duplicate issuance');

        const listCtx = mockCtx('institution');
        listCtx.stub.state = issueCtx.stub.state;
        const raw = await contract.getAllCredentials(listCtx);
        const result = JSON.parse(raw);
        const revoked = result.credentials.find(c => c.credHash === issued1.credHash);
        assert(revoked.status === 'REVOKED' && revoked.revocationReason === 'Duplicate issuance',
            'getAllCredentials reflects revocation status and reason after revokeCredential');
        const stillActive = result.credentials.find(c => c.credHash === issued2.credHash);
        assert(stillActive.status === 'ACTIVE', 'revoking one credential does not affect others');
    }
}

async function testMMR(contract) {
    console.log('\n--- MMR anchoring + inclusion proof ---');
    const ctx = mockCtx('institution');

    const credHashes = [];
    for (let i = 0; i < 5; i++) {
        const result = await issue(contract, ctx, `FAMU3000${i}`, { gpa: 3.5 + i * 0.01 });
        credHashes.push(result.credHash);
    }
    assert(new Set(credHashes).size === 5, 'issued 5 distinct credentials to batch');

    const built = mmr.buildMMR(credHashes);
    const anchorRaw = await contract.anchorMMRRoot(ctx, 'batch-test-1', built.root, JSON.stringify(credHashes), new Date().toISOString());
    const anchorResult = JSON.parse(anchorRaw);
    assert(anchorResult.success === true, 'anchorMMRRoot recomputes and accepts a correctly-derived root');

    {
        let threw = false;
        try { await contract.anchorMMRRoot(ctx, 'batch-test-2', 'not-the-real-root', JSON.stringify(credHashes), new Date().toISOString()); }
        catch (e) { threw = true; }
        assert(threw, 'anchorMMRRoot rejects a root that does not match the recomputed one');
    }

    const proof = mmr.generateProof(built, 2);
    const verifierCtx = mockCtx('verifier');
    verifierCtx.stub.state = ctx.stub.state;
    const inclusionRaw = await contract.verifyMMRInclusion(verifierCtx, credHashes[2], 'batch-test-1', JSON.stringify(proof));
    const inclusionResult = JSON.parse(inclusionRaw);
    assert(inclusionResult.isValid === true, 'real inclusion proof verifies against the anchored root');

    const tamperedProof = mmr.generateProof(built, 2);
    tamperedProof.root = mmr.leafHash('forged-root');
    const tamperedCtx = mockCtx('verifier');
    tamperedCtx.stub.state = ctx.stub.state;
    const tamperedRaw = await contract.verifyMMRInclusion(tamperedCtx, credHashes[2], 'batch-test-1', JSON.stringify(tamperedProof));
    const tamperedResult = JSON.parse(tamperedRaw);
    assert(tamperedResult.isValid === false, 'tampered proof (forged root) is rejected, not silently trusted');
}

(async () => {
    const contract = await testIssuance();
    await testVerification(contract);
    await testGetStudentCredentials(contract);
    await testListAndRevoke(contract);
    await testMMR(contract);

    console.log('\n' + (failures === 0 ? 'ALL CHAINCODE TESTS PASSED' : `${failures} FAILURE(S)`));
    process.exit(failures === 0 ? 0 : 1);
})().catch(e => { console.error('HARNESS ERROR:', e); process.exit(1); });
