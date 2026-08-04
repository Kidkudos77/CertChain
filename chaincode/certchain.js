'use strict';
/**
 * CertChain Chaincode — Hyperledger Fabric Smart Contract
 * =========================================================
 * FAMU FCCS Micro-Credentialing System
 *
 * Layer 2 — Weighted Eligibility Scoring Algorithm
 *   Score = 0.40*(GPA/4.0) + 0.40*(courses/5) + 0.20*(bert_confidence)
 *   Threshold: >= 0.70 → ELIGIBLE
 *
 * Layer 3 — System
 *   - Role-Based Access Control (Admin, Institution, Student, Verifier)
 *   - JSON-LD credential output for interoperability
 *   - Immutable audit log on every transaction
 *
 * ── OFF-CHAIN vs ON-CHAIN DATA MODEL ──────────────────────────────────────────
 *
 *  ON-CHAIN (Hyperledger Fabric ledger):
 *    credentialID, studentID, issuerID, program, courses_completed,
 *    eligibility_score, score_breakdown, issuedAt, status,
 *    ipfs_cid, pq_signature, pq_public_key, pq_algorithm,
 *    revokedAt, revocationReason
 *
 *  OFF-CHAIN (IPFS — referenced by ipfs_cid):
 *    gpa, student_name, bert_confidence, raw_transcript,
 *    full_score_breakdown, issuer_metadata
 *
 *  NEVER ON-CHAIN (FERPA protected):
 *    raw GPA value, student name, transcript text, individual grades
 *    These never touch the ledger. Only the eligibility outcome is recorded.
 *
 * ── VERIFICATION LOGGING (Item 3) ─────────────────────────────────────────────
 *  Every verifyCredential call is logged regardless of outcome.
 *  Hash mismatches emit a VERIFY_MISMATCH event visible to admins.
 *  Admins can query the verification log via getVerificationLog().
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * ── MMR BATCH ANCHORING (additive integrity layer) ────────────────────────────
 *  The CRED~<hash> scheme above is a 1:1 hash pointer per credential — a
 *  verifier checking N credentials makes N independent ledger lookups, with
 *  no way to audit a whole set against one compact commitment. anchorMMRRoot()
 *  adds that without touching CRED~<hash> at all: credentials are batched
 *  (per institution, per issuance day/week) into a Merkle Mountain Range,
 *  and only the batch root is written, under its own MMRROOT~<batchId> key.
 *  The root is recomputed on-chain from the supplied credential hashes and
 *  the transaction is rejected if it disagrees with the caller's claimed
 *  root — endorsing peers derive it themselves rather than trusting it.
 *  See mmr.js for the MMR construction and proof verification.
 * ─────────────────────────────────────────────────────────────────────────────
 */

const { Contract } = require('fabric-contract-api');
const crypto       = require('crypto');
const mmr          = require('./mmr');

const PROGRAM      = 'FAMU-FCCS';
const ISSUER       = 'famu.edu';
// CIS4360 and COP3710 are marked '**' on the official course list — confirmed
// this means "required for all three CIS degree programs" (a department-wide
// catalog note), not a Cybersecurity Certificate-specific rule. Any 3 of
// these 5 satisfies the certificate; all 5 are equally weighted below.
const FCCS_COURSES = ['CIS4385C','CIS4360','CIS4361','CNT4406','COP3710'];
// Prerequisite: COP 3014C (Fundamentals of Programming) must be completed
// BEFORE starting the certificate program of study. It is not one of the
// FCCS_COURSES above and never counts toward MIN_COURSES — it's a hard
// gate, checked separately, the same way MIN_GPA is.
const PREREQUISITE_COURSE = 'COP3014C';
const MIN_GPA      = 3.0;
const MIN_COURSES  = 3;
const W1=0.40, W2=0.40, W3=0.20;
const THRESHOLD    = 0.70;
const ROLES        = {
    ADMIN:       'admin',
    INSTITUTION: 'institution',
    STUDENT:     'student',
    VERIFIER:    'verifier'
};

class CertChain extends Contract {

    // ── Init ──────────────────────────────────────────────────────────────────
    async initLedger(ctx) {
        const genesis = {
            type:      'GENESIS',
            program:   PROGRAM,
            issuer:    ISSUER,
            timestamp: new Date().toISOString(),
            version:   '2.0.0',
            scoring: { w1:W1, w2:W2, w3:W3, threshold:THRESHOLD },
            cryptography: {
                standard:  'CRYSTALS-Dilithium3',
                nist:      'FIPS 204 (ML-DSA)',
                note:      'Dual-signature: ECDSA (Fabric layer) + Dilithium3 (credential layer)'
            },
            dataModel: {
                onChain:  ['credentialID','studentID','issuerID','program','courses_completed',
                           'eligibility_score','issuedAt','status','ipfs_cid','pq_signature'],
                offChain: ['gpa','student_name','bert_confidence','raw_transcript'],
                ferpaProtected: ['gpa','student_name','grades','transcript_text']
            },
            integrityLayers: {
                perCredential: 'CRED~<sha256 hash> — O(1) ledger lookup per credential',
                batchAnchor:   'MMRROOT~<batchId> — Merkle Mountain Range root over a ' +
                               'batch of credentials; supports compact multi-credential ' +
                               'inclusion proofs via verifyMMRInclusion()'
            }
        };
        await ctx.stub.putState('GENESIS', Buffer.from(JSON.stringify(genesis)));
        return JSON.stringify(genesis);
    }

    // ── Layer 2: Weighted Scoring Algorithm ───────────────────────────────────
    // NOTE: GPA and bert_confidence are used ONLY for scoring computation.
    // They are NOT stored on-chain. Only the resulting eligibility_score is.
    _computeScore(gpa, courses, bert_confidence) {
        const score = W1*(parseFloat(gpa)/4.0) +
                      W2*(courses.length/5.0)  +
                      W3*(parseFloat(bert_confidence||0));
        return {
            score:     Math.round(score*10000)/10000,
            eligible:  score >= THRESHOLD,
            breakdown: {
                gpa_component:    Math.round(W1*(parseFloat(gpa)/4.0)*10000)/10000,
                course_component: Math.round(W2*(courses.length/5.0)*10000)/10000,
                bert_component:   Math.round(W3*(parseFloat(bert_confidence||0))*10000)/10000,
            },
            threshold: THRESHOLD,
        };
    }

    // ── Issue Credential ──────────────────────────────────────────────────────
    async issueMicroCredential(ctx, studentID, nlpPayloadStr) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);

        let payload;
        try { payload = JSON.parse(nlpPayloadStr); }
        catch(e) { throw new Error('Invalid NLP payload JSON.'); }

        const { gpa, courses_completed, bert_confidence, prerequisite_completed } = payload;
        // student_name and gpa intentionally NOT destructured for on-chain use

        const validCourses = (courses_completed||[]).filter(
            c => FCCS_COURSES.includes(c.toUpperCase())
        );

        // Hard pre-checks — computed from off-chain data, not stored
        if (!prerequisite_completed) {
            await this._log(ctx, studentID, 'REJECTED', `Prerequisite ${PREREQUISITE_COURSE} not completed`);
            return JSON.stringify({
                success: false,
                reason: `Prerequisite ${PREREQUISITE_COURSE} (Fundamentals of Programming) must be completed prior to starting the certificate program.`
            });
        }
        if (parseFloat(gpa) < MIN_GPA) {
            await this._log(ctx, studentID, 'REJECTED', `GPA below minimum`);
            // Note: actual GPA value not logged — FERPA protection
            return JSON.stringify({
                success: false,
                reason: `GPA below minimum threshold of ${MIN_GPA}.`
            });
        }
        if (validCourses.length < MIN_COURSES) {
            await this._log(ctx, studentID, 'REJECTED',
                `Only ${validCourses.length} FCCS courses completed`);
            return JSON.stringify({
                success: false,
                reason: `Only ${validCourses.length} valid FCCS courses (need ${MIN_COURSES}).`
            });
        }

        // Layer 2: weighted scoring — computed from off-chain inputs
        const scoring = this._computeScore(gpa, validCourses, bert_confidence);
        if (!scoring.eligible) {
            await this._log(ctx, studentID, 'REJECTED',
                `Score ${scoring.score} below threshold`);
            return JSON.stringify({
                success: false,
                reason:  `Score ${scoring.score} below threshold ${THRESHOLD}.`,
                scoring
            });
        }

        const credentialID = `CERTCHAIN-${studentID}-${ctx.stub.getTxID().substring(0,8)}`;
        const issuedAt     = new Date().toISOString();

        // ── ON-CHAIN CREDENTIAL ───────────────────────────────────────────────
        // FERPA compliant: NO raw GPA, NO student name, NO grades
        // Only eligibility OUTCOME and course LIST stored on ledger
        const credential = {
            credentialID,
            studentID,
            issuerID:          ISSUER,
            program:           PROGRAM,
            courses_completed: validCourses,   // course codes only, no grades
            prerequisite_verified: PREREQUISITE_COURSE,  // gate passed; boolean itself isn't stored, just which prerequisite was checked
            eligibility_score: scoring.score,  // computed score, not raw GPA
            score_breakdown:   scoring.breakdown,
            issuedAt,
            status:            'ACTIVE',
            revokedAt:         null,
            revocationReason:  null,
            // Off-chain reference — set by attachIPFS() after IPFS storage
            ipfs_cid:          null,
            // Post-quantum signature — set by attachPQSignature()
            pq_signature:      null,
            pq_public_key:     null,
            pq_algorithm:      'CRYSTALS-Dilithium3 (NIST FIPS 204 / ML-DSA-65)',
            jsonld_context:    'https://schema.org/',
            jsonld_type:       'EducationalOccupationalCredential',
        };
        // ─────────────────────────────────────────────────────────────────────
        // OFF-CHAIN DATA (stored in IPFS, referenced by ipfs_cid above):
        //   { gpa, student_name, bert_confidence, raw_transcript, ... }
        // The IPFS CID is attached later via attachIPFS()
        // This ensures FERPA-protected data never touches the Fabric ledger
        // ─────────────────────────────────────────────────────────────────────

        const credHash = crypto.createHash('sha256')
            .update(JSON.stringify(credential)).digest('hex');

        await ctx.stub.putState(
            `CRED~${credHash}`,
            Buffer.from(JSON.stringify(credential))
        );

        // Student composite index for range queries
        const idx = await ctx.stub.createCompositeKey(
            'student~hash', [studentID, credHash]
        );
        await ctx.stub.putState(idx, Buffer.from('\u0000'));

        ctx.stub.setEvent('CredentialIssued', Buffer.from(JSON.stringify({
            credentialID, studentID, credHash, issuedAt, program: PROGRAM
        })));

        await this._log(ctx, studentID, 'ISSUED', credentialID);
        return JSON.stringify({ success:true, credentialID, credHash, scoring });
    }

    // ── Attach IPFS CID (off-chain data reference) ────────────────────────────
    // Called after FERPA-protected data (GPA, name, transcript) is stored
    // in IPFS. The CID links on-chain credential to off-chain full record.
    async attachIPFS(ctx, credHash, ipfsCID) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);
        const raw = await ctx.stub.getState(`CRED~${credHash}`);
        if (!raw||raw.length===0) throw new Error(`Credential ${credHash} not found.`);
        const c    = JSON.parse(raw.toString());
        c.ipfs_cid = ipfsCID;
        await ctx.stub.putState(`CRED~${credHash}`, Buffer.from(JSON.stringify(c)));
        await this._log(ctx, c.studentID, 'IPFS_ATTACHED', ipfsCID);
        return JSON.stringify({ success:true, credHash, ipfsCID });
    }

    // ── Attach Post-Quantum Signature ─────────────────────────────────────────
    // CRYSTALS-Dilithium3 signature over the credential JSON
    // Applied at application layer — separate from Fabric's ECDSA layer
    async attachPQSignature(ctx, credHash, pqSignature, pqPublicKey) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);
        const raw = await ctx.stub.getState(`CRED~${credHash}`);
        if (!raw||raw.length===0) throw new Error(`Credential ${credHash} not found.`);
        const c         = JSON.parse(raw.toString());
        c.pq_signature  = pqSignature;
        c.pq_public_key = pqPublicKey;
        await ctx.stub.putState(`CRED~${credHash}`, Buffer.from(JSON.stringify(c)));
        await this._log(ctx, c.studentID, 'PQ_SIGNATURE_ATTACHED', credHash);
        return JSON.stringify({
            success:      true,
            credHash,
            pq_algorithm: 'CRYSTALS-Dilithium3 (NIST FIPS 204 / ML-DSA-65)'
        });
    }

    // ── Verify Credential ─────────────────────────────────────────────────────
    // Item 3: Every verification attempt is logged regardless of outcome.
    // Hash mismatches emit VERIFY_MISMATCH event for admin alerting.
    async verifyCredential(ctx, credHash) {
        this._assertRole(ctx, [ROLES.VERIFIER, ROLES.STUDENT, ROLES.INSTITUTION, ROLES.ADMIN]);

        const txID     = ctx.stub.getTxID();
        const callerID = this._getCallerID(ctx);
        const timestamp = new Date().toISOString();

        const raw = await ctx.stub.getState(`CRED~${credHash}`);

        if (!raw || raw.length === 0) {
            // ── HASH MISMATCH / NOT FOUND ─────────────────────────────────────
            // Log the failed verification attempt
            await this._logVerification(ctx, {
                credHash,
                result:    'NOT_FOUND',
                callerID,
                timestamp,
                txID,
                alert:     true,
                alertMsg:  `Hash ${credHash.substring(0,16)}... not found on ledger`
            });

            // Emit event for admin dashboard alerting (Item 3)
            ctx.stub.setEvent('VerifyMismatch', Buffer.from(JSON.stringify({
                credHash,
                callerID,
                timestamp,
                txID,
                reason: 'Credential hash not found on ledger'
            })));

            return JSON.stringify({
                '@context': 'https://schema.org/',
                '@type':    'EducationalOccupationalCredential',
                isValid:    false,
                credHash,
                message:    'Credential not found on ledger.',
                verificationLog: { result:'NOT_FOUND', timestamp, callerID }
            });
        }

        const c = JSON.parse(raw.toString());
        const isActive = c.status === 'ACTIVE';

        if (!isActive) {
            // ── REVOKED CREDENTIAL ────────────────────────────────────────────
            await this._logVerification(ctx, {
                credHash,
                result:    'REVOKED',
                callerID,
                timestamp,
                txID,
                alert:     true,
                alertMsg:  `Revoked credential verification attempted`
            });

            ctx.stub.setEvent('VerifyMismatch', Buffer.from(JSON.stringify({
                credHash,
                callerID,
                timestamp,
                txID,
                reason: `Credential is ${c.status}`
            })));
        } else {
            // ── SUCCESSFUL VERIFICATION ───────────────────────────────────────
            await this._logVerification(ctx, {
                credHash,
                result:    'VERIFIED',
                callerID,
                timestamp,
                txID,
                alert:     false
            });
        }

        return JSON.stringify({
            '@context':         'https://schema.org/',
            '@type':            'EducationalOccupationalCredential',
            identifier:         c.credentialID,
            credentialHash:     credHash,
            isValid:            isActive,
            credentialStatus:   c.status,
            credentialCategory: 'micro-credential',
            recognizedBy:       c.issuerID,
            educationalProgram: c.program,
            competencyRequired: c.courses_completed,
            dateCreated:        c.issuedAt,
            eligibilityScore:   c.eligibility_score,
            scoreBreakdown:     c.score_breakdown,
            ipfsCID:            c.ipfs_cid,
            postQuantumSigned:  c.pq_signature !== null,
            pqAlgorithm:        c.pq_algorithm,
            revokedAt:          c.revokedAt,
            revocationReason:   c.revocationReason,
            verificationLog:    { result: isActive ? 'VERIFIED' : c.status, timestamp, callerID }
        });
    }

    // ── Get Verification Log (Admin/Institution only) ─────────────────────────
    // Item 3: Exposes verification history including mismatches
    async getVerificationLog(ctx, limit) {
        this._assertRole(ctx, [ROLES.ADMIN, ROLES.INSTITUTION]);
        const maxResults = parseInt(limit||'50');
        const results    = [];
        const it = await ctx.stub.getStateByRange('VERIFYLOG~', 'VERIFYLOG~\uFFFF');
        let r    = await it.next();
        while (!r.done && results.length < maxResults) {
            results.push(JSON.parse(r.value.value.toString()));
            r = await it.next();
        }
        // Sort by timestamp descending (most recent first)
        results.sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        return JSON.stringify({
            count:   results.length,
            entries: results,
            alerts:  results.filter(e => e.alert).length
        });
    }

    // ── Get Mismatch Alerts (Admin only) ──────────────────────────────────────
    async getMismatchAlerts(ctx) {
        this._assertRole(ctx, [ROLES.ADMIN]);
        const results = [];
        const it = await ctx.stub.getStateByRange('VERIFYLOG~', 'VERIFYLOG~\uFFFF');
        let r    = await it.next();
        while (!r.done) {
            const entry = JSON.parse(r.value.value.toString());
            if (entry.alert) results.push(entry);
            r = await it.next();
        }
        results.sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        return JSON.stringify({
            alertCount: results.length,
            alerts:     results.slice(0, 20)
        });
    }

    // ── Get all credentials for a student ─────────────────────────────────────
    async getStudentCredentials(ctx, studentID) {
        this._assertRole(ctx, [ROLES.STUDENT, ROLES.INSTITUTION, ROLES.ADMIN]);
        const results = [];
        const it      = await ctx.stub.getStateByPartialCompositeKey(
            'student~hash', [studentID]
        );
        let r = await it.next();
        while (!r.done) {
            const { attributes } = ctx.stub.splitCompositeKey(r.value.key);
            results.push(JSON.parse(await this.verifyCredential(ctx, attributes[1])));
            r = await it.next();
        }
        return JSON.stringify(results);
    }

    // ── Revoke ─────────────────────────────────────────────────────────────────
    async revokeCredential(ctx, credHash, reason) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);
        const raw = await ctx.stub.getState(`CRED~${credHash}`);
        if (!raw||raw.length===0) throw new Error(`Credential ${credHash} not found.`);
        const c           = JSON.parse(raw.toString());
        c.status          = 'REVOKED';
        c.revokedAt       = new Date().toISOString();
        c.revocationReason = reason||'No reason provided';
        await ctx.stub.putState(`CRED~${credHash}`, Buffer.from(JSON.stringify(c)));
        ctx.stub.setEvent('CredentialRevoked', Buffer.from(JSON.stringify({
            credHash, reason: c.revocationReason
        })));
        await this._log(ctx, c.studentID, 'REVOKED', reason);
        return JSON.stringify({ success:true, credHash, status:'REVOKED' });
    }

    // ── Program Analytics ──────────────────────────────────────────────────────
    async getProgramAnalytics(ctx) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);
        let total=0, active=0, revoked=0, scoreSum=0, pqSigned=0, ipfsLinked=0;
        const courseCounts = {};
        FCCS_COURSES.forEach(c => courseCounts[c]=0);

        const it = await ctx.stub.getStateByRange('CRED~', 'CRED~\uFFFF');
        let r    = await it.next();
        while (!r.done) {
            const c = JSON.parse(r.value.value.toString());
            total++;
            if (c.status==='ACTIVE')  { active++;  scoreSum+=c.eligibility_score; }
            if (c.status==='REVOKED')   revoked++;
            if (c.pq_signature)         pqSigned++;
            if (c.ipfs_cid)             ipfsLinked++;
            (c.courses_completed||[]).forEach(code => {
                if (courseCounts[code] !== undefined) courseCounts[code]++;
            });
            r = await it.next();
        }

        // Note: averageGPA removed — GPA is off-chain (FERPA protected)
        return JSON.stringify({
            program:          PROGRAM,
            generatedAt:      new Date().toISOString(),
            totalIssued:      total,
            activeCount:      active,
            revokedCount:     revoked,
            pqSignedCount:    pqSigned,
            ipfsLinkedCount:  ipfsLinked,
            averageScore:     active>0 ? Math.round(scoreSum/active*10000)/10000 : 0,
            coursePopularity: courseCounts,
            scoringConfig:    { w1:W1, w2:W2, w3:W3, threshold:THRESHOLD },
            pqCryptography:   'CRYSTALS-Dilithium3 (FIPS 204 / ML-DSA-65)',
            dataModel: {
                note: 'GPA and student PII stored off-chain in IPFS per FERPA requirements'
            }
        });
    }

    // ── MMR Anchoring (batched multi-credential integrity root) ───────────────
    // Additive integrity layer on top of the existing 1:1 CRED~<hash> scheme.
    // Credentials are batched (institution/day/week — caller's choice) into an
    // append-only Merkle Mountain Range. Only the resulting root is written to
    // the ledger, under its own MMRROOT~<batchId> key — the existing CRED~<hash>
    // records are untouched. A verifier can still do a single O(1) hash lookup
    // via verifyCredential(), OR request an MMR inclusion proof and audit that
    // credential against the one compact anchored root covering the batch.
    //
    // The root is NOT taken on faith from the caller: this function rebuilds
    // the MMR from the supplied credHashes itself and rejects the transaction
    // if the recomputed root disagrees with the submitted `root`. Because
    // Fabric endorsing peers execute this deterministically and must agree on
    // the write set, that recomputation — not the caller's word — is what
    // actually gets endorsed onto the ledger.
    async anchorMMRRoot(ctx, batchId, root, credHashesJSON, timestamp) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);

        if (!batchId || typeof batchId !== 'string') throw new Error('batchId is required.');

        const existing = await ctx.stub.getState(`MMRROOT~${batchId}`);
        if (existing && existing.length > 0) {
            throw new Error(`Batch '${batchId}' is already anchored. Use a new batchId.`);
        }

        let credHashes;
        try { credHashes = JSON.parse(credHashesJSON); }
        catch (e) { throw new Error('credHashesJSON must be a JSON array of credential hashes.'); }

        if (!Array.isArray(credHashes) || credHashes.length === 0) {
            throw new Error('A batch needs at least one credential hash.');
        }
        if (new Set(credHashes).size !== credHashes.length) {
            throw new Error('Duplicate credHash within the same batch.');
        }

        // Every leaf must be a credential that actually exists on-chain, and
        // must not already belong to a different, already-sealed batch.
        for (const credHash of credHashes) {
            const raw = await ctx.stub.getState(`CRED~${credHash}`);
            if (!raw || raw.length === 0) {
                throw new Error(`Cannot batch unknown credential ${credHash}.`);
            }
            const memberKey = ctx.stub.createCompositeKey('mmrmember', [credHash]);
            const already   = await ctx.stub.getState(memberKey);
            if (already && already.length > 0) {
                throw new Error(`Credential ${credHash} is already anchored in batch ${already.toString()}.`);
            }
        }

        // Recompute the root ourselves — never trust the caller's claim.
        const built = mmr.buildMMR(credHashes);
        if (built.root !== root) {
            throw new Error(
                'Submitted root does not match the root recomputed from the ' +
                'supplied credential hashes. Refusing to anchor.'
            );
        }

        const record = {
            batchId,
            root,
            leafCount:  credHashes.length,
            timestamp,
            anchoredBy: this._getCallerID(ctx),
            anchoredAt: new Date().toISOString(),
        };
        await ctx.stub.putState(`MMRROOT~${batchId}`, Buffer.from(JSON.stringify(record)));

        for (let i = 0; i < credHashes.length; i++) {
            const credHash = credHashes[i];
            const leafKey  = ctx.stub.createCompositeKey('mmrleaf', [batchId, String(i).padStart(8, '0')]);
            await ctx.stub.putState(leafKey, Buffer.from(credHash));
            const memberKey = ctx.stub.createCompositeKey('mmrmember', [credHash]);
            await ctx.stub.putState(memberKey, Buffer.from(batchId));
        }

        ctx.stub.setEvent('MMRRootAnchored', Buffer.from(JSON.stringify(record)));
        await this._log(ctx, batchId, 'MMR_ANCHORED',
            `${credHashes.length} credentials, root ${root.substring(0, 16)}...`);
        return JSON.stringify({ success: true, ...record });
    }

    // ── Get anchored MMR root for a batch ──────────────────────────────────────
    async getMMRRoot(ctx, batchId) {
        const raw = await ctx.stub.getState(`MMRROOT~${batchId}`);
        if (!raw || raw.length === 0) throw new Error(`No MMR root anchored for batch '${batchId}'.`);
        return raw.toString();
    }

    // ── List a batch's members in leaf (append) order ──────────────────────────
    // Needed to rebuild the MMR off-chain and generate an inclusion proof.
    async getMMRBatchMembers(ctx, batchId) {
        const results = [];
        const it = await ctx.stub.getStateByPartialCompositeKey('mmrleaf', [batchId]);
        let r = await it.next();
        while (!r.done) {
            results.push(r.value.value.toString());
            r = await it.next();
        }
        return JSON.stringify({ batchId, leafCount: results.length, credHashes: results });
    }

    // ── Verify a credential's MMR inclusion proof against the anchored root ───
    // Complements verifyCredential(): that does an O(1) single-record lookup;
    // this audits the same credential against a compact root covering an
    // entire batch, using a client-supplied Merkle path. The proof's claimed
    // root is always cross-checked against the ledger's own MMRROOT~<batchId>
    // record — a proof that only "looks" internally consistent is rejected
    // unless it also matches what was actually anchored on-chain.
    async verifyMMRInclusion(ctx, credHash, batchId, proofJSON) {
        this._assertRole(ctx, [ROLES.VERIFIER, ROLES.STUDENT, ROLES.INSTITUTION, ROLES.ADMIN]);

        const txID      = ctx.stub.getTxID();
        const callerID  = this._getCallerID(ctx);
        const timestamp = new Date().toISOString();

        const rootRaw = await ctx.stub.getState(`MMRROOT~${batchId}`);
        if (!rootRaw || rootRaw.length === 0) {
            await this._logVerification(ctx, {
                credHash, batchId, result: 'BATCH_NOT_FOUND', callerID, timestamp, txID,
                alert: true, alertMsg: `Batch '${batchId}' has no anchored root`
            });
            return JSON.stringify({
                isValid: false, credHash, batchId,
                message: `No MMR root anchored for batch '${batchId}'.`,
                verificationLog: { result: 'BATCH_NOT_FOUND', timestamp, callerID }
            });
        }
        const rootRecord = JSON.parse(rootRaw.toString());

        let proof;
        try { proof = JSON.parse(proofJSON); }
        catch (e) {
            await this._logVerification(ctx, {
                credHash, batchId, result: 'MALFORMED_PROOF', callerID, timestamp, txID,
                alert: true, alertMsg: 'Proof JSON could not be parsed'
            });
            return JSON.stringify({ isValid: false, credHash, batchId, message: 'Malformed proof JSON.' });
        }

        const proofInternallyValid = mmr.verifyProof(credHash, proof);
        const rootMatches          = proof.root === rootRecord.root;
        const isValid              = proofInternallyValid && rootMatches;

        await this._logVerification(ctx, {
            credHash, batchId,
            result:   isValid ? 'MMR_VERIFIED' : 'MMR_MISMATCH',
            callerID, timestamp, txID,
            alert:    !isValid,
            alertMsg: isValid ? undefined :
                `MMR inclusion proof failed for ${credHash.substring(0, 16)}... in batch ${batchId}`
        });

        if (!isValid) {
            ctx.stub.setEvent('VerifyMismatch', Buffer.from(JSON.stringify({
                credHash, batchId, callerID, timestamp, txID,
                reason: proofInternallyValid
                    ? 'Proof root does not match anchored root'
                    : 'Proof failed internal verification'
            })));
        }

        return JSON.stringify({
            isValid,
            credHash,
            batchId,
            root:            rootRecord.root,
            leafCount:       rootRecord.leafCount,
            anchoredAt:      rootRecord.anchoredAt,
            verificationLog: { result: isValid ? 'MMR_VERIFIED' : 'MMR_MISMATCH', timestamp, callerID }
        });
    }

    // ── Find credentials not yet folded into any MMR batch ─────────────────────
    // Batch-selection helper: an operator calls this to decide what goes into
    // the next anchorMMRRoot() call (e.g. "everything issued since yesterday").
    async getUnanchoredCredentials(ctx, sinceTimestamp) {
        this._assertRole(ctx, [ROLES.INSTITUTION, ROLES.ADMIN]);
        const results = [];
        const it = await ctx.stub.getStateByRange('CRED~', 'CRED~\uFFFF');
        let r = await it.next();
        while (!r.done) {
            const credHash = r.value.key.substring('CRED~'.length);
            const c = JSON.parse(r.value.value.toString());
            if (!sinceTimestamp || c.issuedAt >= sinceTimestamp) {
                const memberKey = ctx.stub.createCompositeKey('mmrmember', [credHash]);
                const already   = await ctx.stub.getState(memberKey);
                if (!already || already.length === 0) {
                    results.push({
                        credHash, credentialID: c.credentialID,
                        studentID: c.studentID, issuedAt: c.issuedAt
                    });
                }
            }
            r = await it.next();
        }
        return JSON.stringify({ count: results.length, credentials: results });
    }

    // ── Helpers ────────────────────────────────────────────────────────────────
    _assertRole(ctx, allowed) {
        let role;
        try { role = ctx.clientIdentity.getAttributeValue('role'); }
        catch(e) { throw new Error('Cannot read caller role.'); }
        if (!role || !allowed.includes(role))
            throw new Error(`Role '${role}' not permitted. Need: [${allowed.join(',')}]`);
    }

    _getCallerID(ctx) {
        try { return ctx.clientIdentity.getID(); }
        catch(e) { return 'unknown'; }
    }

    async _log(ctx, subject, action, detail) {
        await ctx.stub.putState(
            `LOG~${ctx.stub.getTxID()}`,
            Buffer.from(JSON.stringify({
                subject, action, detail,
                txID:      ctx.stub.getTxID(),
                timestamp: new Date().toISOString(),
            }))
        );
    }

    // Item 3: Separate verification log with alert flag
    async _logVerification(ctx, entry) {
        const key = `VERIFYLOG~${entry.timestamp}~${ctx.stub.getTxID()}`;
        await ctx.stub.putState(key, Buffer.from(JSON.stringify(entry)));
    }
}

module.exports = CertChain;
