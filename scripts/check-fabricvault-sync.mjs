#!/usr/bin/env node
// CertChain — FabricVault decision-interpreter behavioral sync check
// =======================================================================
// FabricVault (fabricvault/, a git submodule) can't import
// packages/decision-interpreter/index.js directly — it must stay
// buildable as a standalone repo with its own users, and a browser
// extension bundle has no way to reach across a submodule boundary at
// build time. So it keeps two ported copies instead:
//   - fabricvault/packages/extension/src/lib/decision-interpreter.ts
//   - fabricvault/chrome-extension/popup.js's inline copy
//
// A text diff across JS/TypeScript/a minified bundle isn't meaningful.
// This script instead runs a battery of test payloads through all three
// implementations and asserts they produce the same headline, the same
// anomalies, and the same field values — a behavioral equivalence check.
// It caught a real drift once already (see packages/decision-interpreter's
// credentialHash-alias fix) — this is not a hypothetical safety net.
//
// Run: node scripts/check-fabricvault-sync.mjs
// Requires Node's --experimental-strip-types support (Node >=22.6) to
// load the .ts port directly without a build step or ts-node dependency.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

const FABRICVAULT_DIR = path.join(ROOT, 'fabricvault');
if (!fs.existsSync(FABRICVAULT_DIR) || fs.readdirSync(FABRICVAULT_DIR).length === 0) {
    console.log('fabricvault/ submodule not initialized (git submodule update --init) — skipping sync check.');
    process.exit(0);
}

const decisionInterpreter = require(path.join(ROOT, 'packages/decision-interpreter'));

const TEST_CASES = [
    { label: 'fully eligible, has credHash', payload: { studentID: 'FAMU10001', program: 'FAMU-FCCS', courses_completed: ['CIS4385C', 'CIS4360', 'CIS4361'], eligibility_score: 0.83, credHash: 'a'.repeat(64) } },
    { label: 'below threshold, has credHash', payload: { studentID: 'FAMU10002', program: 'FAMU-FCCS', courses_completed: ['CIS4385C'], eligibility_score: 0.42, credHash: 'b'.repeat(64) } },
    { label: 'eligible but missing hash', payload: { studentID: 'FAMU10003', program: 'FAMU-FCCS', courses_completed: ['CIS4385C', 'CIS4360', 'CIS4361'], eligibility_score: 0.9 } },
    { label: 'below threshold and missing hash', payload: { studentID: 'FAMU10004', eligibility_score: 0.1 } },
    { label: 'empty payload', payload: {} },
    { label: 'credentialHash alias instead of credHash', payload: { eligibility_score: 0.95, credentialHash: 'c'.repeat(64) } },
    { label: 'exactly at threshold (0.70)', payload: { eligibility_score: 0.70, credHash: 'd'.repeat(64) } },
];

function normalizeFieldValue(v) {
    if (v === undefined || v === null || v === '') return '—';
    if (Array.isArray(v)) return v.join(', ');
    return String(v);
}

// pqc_signing's fixed field set — used to backfill fields the authoritative
// source omits when absent (summarize() drops not-present fields entirely)
// so they compare equally against FabricVault's ports, which always show
// all five with a "—" placeholder. Different representations of the same
// fact ("field omitted" vs. "field shown as —"), not a behavioral gap.
const PQC_SIGNING_FIELD_KEYS = ['studentID', 'program', 'courses_completed', 'eligibility_score', 'credHash'];

function fillMissingFields(fieldValues) {
    const filled = { ...fieldValues };
    for (const key of PQC_SIGNING_FIELD_KEYS) {
        if (!(key in filled)) filled[key] = '—';
    }
    return filled;
}

// ── Implementation 1: the authoritative source ──────────────────────────────
function runAuthoritative(payload) {
    const parsed = decisionInterpreter.parseRequest(payload, decisionInterpreter.REQUEST_TYPES.PQC_SIGNING);
    const interpretation = decisionInterpreter.interpret(parsed, decisionInterpreter.REQUEST_TYPES.PQC_SIGNING);
    const summary = decisionInterpreter.summarize(interpretation, 'institution');
    const fieldValues = {};
    for (const f of summary.fields) fieldValues[f.key] = normalizeFieldValue(f.value);
    return { headline: summary.headline, anomalies: summary.anomalies, fieldValues: fillMissingFields(fieldValues) };
}

// ── Implementation 2: FabricVault's TypeScript port ─────────────────────────
async function runTsPort(payload) {
    const tsPath = path.join(FABRICVAULT_DIR, 'packages/extension/src/lib/decision-interpreter.ts');
    const mod = await import(tsPath);
    const result = mod.explainPqcSigning(payload);
    const fieldValues = {};
    for (const key of Object.keys(result.fields)) fieldValues[key] = normalizeFieldValue(result.fields[key]);
    return { headline: result.headline, anomalies: result.anomalies, fieldValues };
}

// ── Implementation 3: FabricVault's compiled popup.js inline copy ──────────
// Drives the REAL shipped bundle through its actual preview flow (not an
// extracted function) via a minimal DOM/chrome.storage mock — the same
// harness pattern used to verify the sign flow itself when it was built.
function makeEl(tag) {
    const listeners = {};
    return {
        tag, value: '', textContent: '', innerHTML: '', className: '', disabled: false, checked: false,
        style: { display: '' },
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        _fire(type) { (listeners[type] || []).forEach(fn => fn()); },
    };
}

function runPopupJsPort(payload) {
    const elements = {
        credentialInput: makeEl('textarea'), previewBtn: makeEl('button'),
        explainResult: makeEl('div'), ackRow: makeEl('label'), ackAnomalies: makeEl('input'),
        signBtn: makeEl('button'), signResult: makeEl('div'), keyStatus: makeEl('span'),
    };
    const genBtn = makeEl('button'), viewBtn = makeEl('button');
    const docListeners = {};
    const fakeDocument = {
        getElementById: (id) => elements[id] || null,
        querySelector: (sel) => (sel === '.btn1' ? genBtn : sel === '.btn2' ? viewBtn : null),
        addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
        createElement: (tag) => {
            const el = makeEl(tag);
            Object.defineProperty(el, 'textContent', {
                set(v) { this._text = v; this.innerHTML = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
                get() { return this._text; },
            });
            return el;
        },
    };
    const store = {};
    const fakeChrome = { storage: { local: { get: async () => ({}), set: async () => {} } } };
    const sandbox = { document: fakeDocument, chrome: fakeChrome, crypto: globalThis.crypto, TextEncoder, alert: () => {}, console };
    vm.createContext(sandbox);
    const src = fs.readFileSync(path.join(FABRICVAULT_DIR, 'chrome-extension/popup.js'), 'utf8');
    vm.runInContext(src, sandbox, { filename: 'popup.js' });
    (docListeners['DOMContentLoaded'] || []).forEach(fn => fn());

    elements.credentialInput.value = JSON.stringify(payload);
    elements.previewBtn._fire('click');

    const html = elements.explainResult.innerHTML;
    const headlineMatch = html.match(/<div class="hl">(.*?)<\/div>/);
    const headline = headlineMatch ? unescapeHtml(headlineMatch[1]) : null;
    const anomalies = [...html.matchAll(/<li>(.*?)<\/li>/g)].map(m => unescapeHtml(m[1]));
    const fieldMatches = [...html.matchAll(/<div class="field"><span>(.*?)<\/span><span>(.*?)<\/span><\/div>/g)];
    const LABEL_TO_KEY = { 'Student ID': 'studentID', 'Program': 'program', 'Courses': 'courses_completed', 'Eligibility score': 'eligibility_score', 'Credential hash': 'credHash' };
    const fieldValues = {};
    for (const [, label, value] of fieldMatches) {
        const key = LABEL_TO_KEY[label];
        if (key) fieldValues[key] = unescapeHtml(value);
    }
    return { headline, anomalies, fieldValues };
}

function unescapeHtml(s) {
    return s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

// ── Compare ──────────────────────────────────────────────────────────────────
// Two things are deliberately NOT compared as exact text, because they are
// legitimate per-consumer presentation choices rather than the underlying
// rule logic this check exists to protect:
//   - headline wording: FabricVault's ports hardcode "credential signing"
//     for friendlier UI copy instead of deriving it from the raw
//     requestType string ("pqc signing").
//   - the "missing credential hash" anomaly's exact wording: the ports'
//     version explains consequences for a person about to click Sign
//     ("you are about to sign this exact text..."); the authoritative
//     source's version is terser, written for API consumers generally.
// What must match, strictly: field VALUES (identical dotted-path lookups
// and identical fallback/alias behavior), and that the same NUMBER of
// anomalies fire for the same input (same underlying trigger conditions —
// if one implementation flags something the other doesn't, that's a real
// rule-logic drift, not a wording choice).
function hasAnomaliesPhrasing(headline) {
    return !/no anomalies/i.test(headline);
}

// Order-independent structural equality — JSON.stringify alone is
// key-order-sensitive, which would flag identical objects built via a
// different insertion order as "different." Good enough for this script's
// plain string-keyed, non-nested field-value objects and string arrays.
function deepEqual(a, b) {
    if (Array.isArray(a) || Array.isArray(b)) return JSON.stringify(a) === JSON.stringify(b);
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return a === b;
    const aKeys = Object.keys(a).sort();
    const bKeys = Object.keys(b).sort();
    if (JSON.stringify(aKeys) !== JSON.stringify(bKeys)) return false;
    return aKeys.every(k => a[k] === b[k]);
}

async function run() {
    let failures = 0;
    for (const { label, payload } of TEST_CASES) {
        const authoritative = runAuthoritative(payload);
        const tsPort = await runTsPort(payload);
        const popupPort = runPopupJsPort(payload);

        const check = (impl, name) => {
            const problems = [];
            if (hasAnomaliesPhrasing(impl.headline) !== (authoritative.anomalies.length > 0))
                problems.push(`headline anomaly-presence mismatch (headline: ${JSON.stringify(impl.headline)})`);
            if (authoritative.anomalies.length !== impl.anomalies.length)
                problems.push(`anomaly count differs (${authoritative.anomalies.length} vs ${impl.anomalies.length})`);
            if (!deepEqual(authoritative.fieldValues, impl.fieldValues))
                problems.push('field values differ');
            return problems;
        };

        const tsProblems = check(tsPort, 'ts port');
        const popupProblems = check(popupPort, 'popup.js port');

        if (tsProblems.length === 0 && popupProblems.length === 0) {
            console.log(`ok:   ${label}`);
        } else {
            failures++;
            console.log(`FAIL: ${label}`);
            console.log('  authoritative:', JSON.stringify(authoritative));
            if (tsProblems.length)    console.log(`  ts port [${tsProblems.join('; ')}]:`, JSON.stringify(tsPort));
            if (popupProblems.length) console.log(`  popup.js port [${popupProblems.join('; ')}]:`, JSON.stringify(popupPort));
        }
    }

    console.log('\n' + (failures === 0
        ? `ALL ${TEST_CASES.length} CASES MATCH ACROSS ALL THREE IMPLEMENTATIONS`
        : `${failures}/${TEST_CASES.length} CASES DIVERGED — FabricVault's ports and the authoritative source disagree, see above`));
    process.exit(failures === 0 ? 0 : 1);
}

run().catch(e => { console.error('HARNESS ERROR:', e); process.exit(1); });
