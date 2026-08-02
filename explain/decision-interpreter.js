'use strict';
/**
 * CertChain — Framework-Wide Explainability Layer (Phase 8, SSD-derived)
 * ==========================================================================
 * SSD's actual contribution is a reusable pattern, not a wallet-signing
 * feature: parse a raw request → interpret it against a rule-based
 * knowledge base → produce a plain-language, risk-flagged summary before
 * a human commits to something consequential. FabricVault's signing
 * confirmation is one place that pattern applies in CertChain — it is not
 * the only one (see the consumer table below). Building it once here,
 * shared, instead of four separate times, is the point: one thing to keep
 * correct instead of four things to keep in sync.
 *
 * Deterministic, rule-based, no ML anywhere in this layer — same as SSD's
 * own design. Three-stage shape:
 *
 *   parseRequest(rawPayload, requestType) -> parsedFields
 *   interpret(parsedFields, requestType)  -> interpretation
 *   summarize(interpretation, viewerRole) -> plain-language summary
 *
 * Consumers (as of Phase 8):
 *   - api/server.js can call this directly today.
 *   - FabricVault (the browser extension) is a consumer in design, not in
 *     code: its source isn't in this repository, so it isn't wired to
 *     import this module here. Whoever has that source imports this file
 *     the same way api/server.js does — nothing about the module's shape
 *     is API-side-specific.
 *   - ore_query (Phase 7) is deliberately left out of REQUEST_TYPES below
 *     until the ORE cryptographic core exists — adding it now would imply
 *     a feature that isn't built.
 */

const REQUEST_TYPES = Object.freeze({
    PQC_SIGNING:             'pqc_signing',
    CREDENTIAL_ISSUANCE:     'credential_issuance',
    CREDENTIAL_VERIFICATION: 'credential_verification',
    MMR_BATCH_VERIFICATION:  'mmr_batch_verification',
});

const VIEWER_ROLES = Object.freeze(['student', 'institution', 'verifier', 'auditor']);

// ── dotted-path helper (payloads here are one or two levels deep) ─────────
function getPath(obj, dottedPath) {
    return dottedPath.split('.').reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
}

// ── Rule-based knowledge base ───────────────────────────────────────────────
// One entry per requestType: which fields matter, their plain-language
// label, and deterministic anomaly checks. Same "deterministic template"
// approach as SSD — no model, no inference, just rules over known fields.
const KNOWLEDGE_BASE = {
    [REQUEST_TYPES.PQC_SIGNING]: {
        fields: {
            studentID:          'Student ID',
            program:             'Program',
            courses_completed:   'Courses being certified',
            eligibility_score:   'Eligibility score',
            credHash:            'Credential hash (this is what actually gets signed)',
        },
        anomalies(f) {
            const flags = [];
            if (typeof f.eligibility_score === 'number' && f.eligibility_score < 0.70)
                flags.push('Eligibility score is below the 0.70 issuance threshold — signing a credential that should not have been eligible.');
            if (!f.credHash)
                flags.push('No credential hash present — nothing verifiable is actually being signed.');
            return flags;
        },
    },

    [REQUEST_TYPES.CREDENTIAL_ISSUANCE]: {
        fields: {
            success:                            'Outcome',
            reason:                              'Reason (if rejected)',
            'scoring.score':                     'Computed eligibility score',
            'scoring.breakdown.gpa_component':    'GPA contribution to score',
            'scoring.breakdown.course_component': 'Course-count contribution to score',
            'scoring.breakdown.bert_component':   'BERT-confidence contribution to score',
        },
        anomalies(f) {
            const flags = [];
            if (f.success === false && !f.reason)
                flags.push('Rejected with no reason recorded.');
            const components = ['scoring.breakdown.gpa_component', 'scoring.breakdown.course_component', 'scoring.breakdown.bert_component']
                .map(k => f[k]).filter(v => typeof v === 'number');
            if (f.success === false && components.length === 3) {
                const weakest = ['GPA', 'course count', 'BERT confidence'][components.indexOf(Math.min(...components))];
                flags.push(`Weakest contributing factor: ${weakest}.`);
            }
            return flags;
        },
    },

    [REQUEST_TYPES.CREDENTIAL_VERIFICATION]: {
        fields: {
            isValid:            'Valid',
            credentialStatus:    'Status',
            'verificationLog.result':    'What the ledger actually checked',
            revocationReason:    'Revocation reason (if revoked)',
        },
        anomalies(f) {
            const flags = [];
            if (f.isValid === false && f.credentialStatus === 'REVOKED')
                flags.push(`Credential was explicitly revoked${f.revocationReason ? ': ' + f.revocationReason : ' (no reason on file)'}.`);
            if (f.isValid === false && f.credentialStatus !== 'REVOKED')
                flags.push('Credential hash was not found on the ledger at all — this is not a "revoked" case, the hash may be wrong or forged.');
            return flags;
        },
    },

    [REQUEST_TYPES.MMR_BATCH_VERIFICATION]: {
        fields: {
            confidenceLevel:    'Statistical confidence the batch is intact',
            roundsRun:           'Sampling rounds completed',
            itemsChecked:        'Individual credentials actually checked',
            batchSize:           'Total credentials in the batch',
            itemsFlagged:        'Credentials that failed verification',
        },
        anomalies(f) {
            const flags = [];
            if (Array.isArray(f.itemsFlagged) && f.itemsFlagged.length > 0)
                flags.push(`${f.itemsFlagged.length} credential(s) failed inclusion-proof verification during sampling — treat this batch as compromised, not partially trustworthy.`);
            if (typeof f.confidenceLevel === 'number' && f.confidenceLevel < 0.5)
                flags.push('Confidence level is below 50% — a targeted single-item tamper has a good chance of not being caught by this sampling run. Consider a larger sampleSize/rounds or full verification.');
            return flags;
        },
    },
};

// ── Stage 1: parseRequest ────────────────────────────────────────────────────
function parseRequest(rawPayload, requestType) {
    if (!KNOWLEDGE_BASE[requestType]) {
        throw new Error(`Unknown requestType '${requestType}'. Known types: ${Object.values(REQUEST_TYPES).join(', ')}`);
    }
    if (!rawPayload || typeof rawPayload !== 'object') {
        throw new Error('rawPayload must be an object.');
    }
    const { fields } = KNOWLEDGE_BASE[requestType];
    const parsedFields = {};
    for (const path of Object.keys(fields)) {
        parsedFields[path] = getPath(rawPayload, path);
    }
    return parsedFields;
}

// ── Stage 2: interpret ────────────────────────────────────────────────────────
function interpret(parsedFields, requestType) {
    const kb = KNOWLEDGE_BASE[requestType];
    if (!kb) throw new Error(`Unknown requestType '${requestType}'.`);

    const fieldEntries = Object.entries(kb.fields).map(([path, label]) => ({
        key:   path,
        label,
        value: parsedFields[path],
        present: parsedFields[path] !== undefined,
    }));

    return {
        requestType,
        fields:    fieldEntries,
        anomalies: kb.anomalies(parsedFields),
    };
}

// ── Stage 3: summarize ────────────────────────────────────────────────────────
// viewerRole controls detail depth — this is what makes "progressive
// explainability" concrete as one parameter rather than four separate UIs.
//   student:     headline outcome + anomalies only, no raw field dump
//   verifier:    headline + all fields, no internal breakdown fields
//   institution: everything
//   auditor:     everything, plus the raw field list is never trimmed
function summarize(interpretation, viewerRole) {
    if (!VIEWER_ROLES.includes(viewerRole)) {
        throw new Error(`Unknown viewerRole '${viewerRole}'. Known roles: ${VIEWER_ROLES.join(', ')}`);
    }

    const { requestType, fields, anomalies } = interpretation;
    const presentFields = fields.filter(f => f.present);

    const headline = anomalies.length > 0
        ? `${anomalies.length} thing(s) worth your attention on this ${requestType.replace(/_/g, ' ')}.`
        : `No anomalies detected for this ${requestType.replace(/_/g, ' ')}.`;

    if (viewerRole === 'student') {
        return { requestType, viewerRole, headline, anomalies, fields: [] };
    }

    // verifier/institution/auditor all get the full field list; institution
    // and auditor are the same today (no fields are currently marked
    // internal-only) — the distinction exists so a future field can be
    // flagged institution/auditor-only without changing this function's shape.
    return { requestType, viewerRole, headline, anomalies, fields: presentFields };
}

module.exports = { REQUEST_TYPES, VIEWER_ROLES, parseRequest, interpret, summarize };
