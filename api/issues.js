'use strict';
/**
 * CertChain — Issue Reporting (Phase 2)
 * =========================================
 * A way for anyone to flag that CertChain itself isn't working correctly —
 * a bug/issue report path, not credential feedback. No MMR, no blockchain
 * involvement, no new RBAC role: operational support tooling, not
 * credential data. Flat JSON log with atomic writes, same pattern as
 * api/auth.js's users.json — genuinely appropriate here given the low
 * stakes (support tickets, not credentials).
 */
const fs   = require('fs');
const path = require('path');
const os   = require('os');
const crypto = require('crypto');

const ISSUES_FILE = path.join(__dirname, 'issues.json');
const VALID_STATUSES = ['open', 'in-progress', 'resolved'];

function loadIssues() {
    if (!fs.existsSync(ISSUES_FILE)) return { issues: [] };
    try {
        return JSON.parse(fs.readFileSync(ISSUES_FILE, 'utf8'));
    } catch (e) {
        return { issues: [] };
    }
}

function saveIssues(store) {
    const serialized = JSON.stringify(store, null, 2);
    const tmp = path.join(os.tmpdir(), `certchain-issues-${process.pid}-${Date.now()}.tmp`);
    fs.writeFileSync(tmp, serialized, { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(tmp, ISSUES_FILE); // atomic on POSIX
}

function createIssue({ reporterID, reporterRole, description, credentialId }) {
    const store = loadIssues();
    const issue = {
        id:           crypto.randomBytes(8).toString('hex'),
        reporterID,
        reporterRole,
        description,
        credentialId: credentialId || null,
        status:       'open',
        createdAt:    new Date().toISOString(),
        updatedAt:    new Date().toISOString(),
    };
    store.issues.push(issue);
    saveIssues(store);
    return issue;
}

function listIssues() {
    const store = loadIssues();
    return store.issues.slice().sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function updateIssueStatus(id, status) {
    if (!VALID_STATUSES.includes(status)) {
        return { ok: false, error: `status must be one of: ${VALID_STATUSES.join(', ')}` };
    }
    const store = loadIssues();
    const issue = store.issues.find(i => i.id === id);
    if (!issue) return { ok: false, error: 'Issue not found.' };
    issue.status    = status;
    issue.updatedAt = new Date().toISOString();
    saveIssues(store);
    return { ok: true, issue };
}

module.exports = { createIssue, listIssues, updateIssueStatus, VALID_STATUSES };
