'use strict';
/**
 * CertChain — REST API v3 (Hardened)
 *
 * Security improvements over v2:
 *  - helmet middleware (H2 fix): X-Frame-Options, HSTS, X-Content-Type-Options,
 *    Referrer-Policy, X-DNS-Prefetch-Control
 *  - Content Security Policy tailored to CertChain (H2 fix)
 *  - express-rate-limit on auth endpoints (H1 fix)
 *  - Strict CORS — no wildcard ngrok matching (H3 fix)
 *  - nlpPayload schema validation (H4 fix)
 *  - Sanitized error responses — no stack traces to client (C4 fix)
 *  - Request ID for audit trail (M3 fix)
 *  - Input length enforcement on all routes
 *  - async login/register (bcrypt)
 */

const express    = require('express');
const helmet     = require('helmet');
const rateLimit  = require('express-rate-limit');
const bodyParser = require('body-parser');
const cors       = require('cors');
const crypto     = require('crypto');
const fs         = require('fs');
const path       = require('path');
const auth       = require('./auth');
const { getContract } = require('../wallet/wallet_setup');
const mmr        = require('../chaincode/mmr');
const sampling   = require('./mmr_sampling');
const multer     = require('multer');
const os         = require('os');
const { execFile } = require('child_process');
const { extractText } = require('./transcript_extract');
const issues     = require('./issues');
const mores      = require('../crypto/mores_client');
const explain    = require('../explain/decision-interpreter');

const app  = express();
const PORT = process.env.PORT || 3000;
const IS_PROD = process.env.NODE_ENV === 'production';

// ── Request ID middleware ────────────────────────────────────────────────────
// Every request gets a unique ID for correlation in logs (M3 fix)
app.use((req, _res, next) => {
    req.id = crypto.randomBytes(8).toString('hex');
    next();
});

// ── Helmet — security headers ────────────────────────────────────────────────
// H2 fix: Sets X-Frame-Options, X-Content-Type-Options, HSTS,
//         Referrer-Policy, X-DNS-Prefetch-Control, Permissions-Policy
app.use(helmet({
    // Content Security Policy tailored to CertChain
    contentSecurityPolicy: {
        directives: {
            defaultSrc:     ["'self'"],
            scriptSrc:      ["'self'", "'unsafe-inline'",
                             "https://fonts.googleapis.com"],       // GUI inline scripts
            styleSrc:       ["'self'", "'unsafe-inline'",
                             "https://fonts.googleapis.com"],
            fontSrc:        ["'self'", "https://fonts.gstatic.com"],
            imgSrc:         ["'self'", "data:"],
            connectSrc:     ["'self'",
                             "https://kidkudos77.github.io",
                             "https://*.ngrok-free.dev",
                             "https://*.ngrok.io"],                 // API calls from GUI
            frameSrc:       ["'none'"],                             // no iframes
            objectSrc:      ["'none'"],
            baseUri:        ["'self'"],
            formAction:     ["'self'"],
            upgradeInsecureRequests: IS_PROD ? [] : null,
        },
        reportOnly: false,
    },
    // HSTS — only in production (local dev uses HTTP)
    hsts: IS_PROD ? { maxAge: 31536000, includeSubDomains: true, preload: true } : false,
    // Prevent MIME-type sniffing
    noSniff: true,
    // Prevent clickjacking
    frameguard: { action: 'deny' },
    // Referrer policy — don't leak URL to third parties
    referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
    // Disable browser DNS prefetch
    dnsPrefetchControl: { allow: false },
}));

// Additional headers not covered by helmet
app.use((_req, res, next) => {
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    res.setHeader('X-Request-ID', _req.id);
    next();
});

// ── CORS — strict origin allowlist ───────────────────────────────────────────
// H3 fix: Use exact regex anchored to the specific ngrok free subdomain pattern,
//         not a loose .includes() check.
const NGROK_PATTERN = /^https:\/\/[a-z0-9-]+\.ngrok-free\.app$/;
const NGROK_DEV_PATTERN = /^https:\/\/[a-z0-9-]+\.ngrok-free\.dev$/;

const ALLOWED_ORIGINS = new Set([
    'https://kidkudos77.github.io',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    'http://localhost:3001',
    'http://localhost:3000',
]);

app.use(cors({
    origin: (origin, cb) => {
        if (!origin) return cb(null, true);  // same-origin or non-browser
        if (ALLOWED_ORIGINS.has(origin))     return cb(null, true);
        if (NGROK_PATTERN.test(origin))      return cb(null, true);
        if (NGROK_DEV_PATTERN.test(origin))  return cb(null, true);
        cb(new Error(`CORS_BLOCKED: ${origin}`));
    },
    methods:        ['GET', 'POST', 'OPTIONS'],  // only what we use (M2 fix)
    allowedHeaders: ['Content-Type', 'Authorization', 'ngrok-skip-browser-warning', 'X-Request-ID'],
    exposedHeaders: ['X-Request-ID'],
    credentials:    true,
    optionsSuccessStatus: 200,
}));

// ── Body parser — strict limits ──────────────────────────────────────────────
app.use(bodyParser.json({
    limit: '50kb',          // reduced from 1mb — credentials never need 1mb
    strict: true,           // only accept arrays and objects (not raw primitives)
}));

// ── Rate limiting ─────────────────────────────────────────────────────────────
// H1 fix: Limit login attempts. 10 attempts per 15 minutes per IP.
const authLimiter = rateLimit({
    windowMs:         15 * 60 * 1000,
    max:              10,
    standardHeaders:  true,
    legacyHeaders:    false,
    message:          { ok: false, error: 'Too many attempts. Try again in 15 minutes.' },
    skipSuccessfulRequests: true,
});

// General API limiter — 300 requests per 15 min per IP
const apiLimiter = rateLimit({
    windowMs:        15 * 60 * 1000,
    max:             300,
    standardHeaders: true,
    legacyHeaders:   false,
});

app.use('/auth/login',    authLimiter);
app.use('/auth/register', authLimiter);
app.use('/',              apiLimiter);

// ── Structured request logger ────────────────────────────────────────────────
// M3 fix: log with request ID, never log request body (could contain passwords)
app.use((req, _res, next) => {
    const ip = req.headers['x-forwarded-for'] || req.socket.remoteAddress || 'unknown';
    console.log(JSON.stringify({
        t:      new Date().toISOString(),
        id:     req.id,
        method: req.method,
        path:   req.path,
        ip:     ip.toString().substring(0, 45), // limit length
    }));
    next();
});

// ── Input validation helpers ─────────────────────────────────────────────────
const HASH_PATTERN    = /^[a-f0-9]{64}$/;       // SHA-256 hex
const STUDENTID_PATTERN = /^[A-Za-z0-9_-]{3,64}$/;
const BATCHID_PATTERN   = /^[A-Za-z0-9_-]{1,100}$/;

function validateHash(h) {
    return typeof h === 'string' && HASH_PATTERN.test(h);
}

function validateStudentID(id) {
    return typeof id === 'string' && STUDENTID_PATTERN.test(id);
}

function validateBatchId(id) {
    return typeof id === 'string' && BATCHID_PATTERN.test(id);
}

// Phase 8 explainability layer: this system's RBAC roles (admin, institution,
// student, verifier) aren't quite explain/decision-interpreter.js's
// viewerRole set (student, institution, verifier, auditor) — admin maps to
// auditor (full-depth view), matching the existing pattern where admin-only
// endpoints already see everything (getVerificationLog, getMismatchAlerts).
function toViewerRole(sessionRole) {
    return sessionRole === 'admin' ? 'auditor' : sessionRole;
}

// Never let an explanation failure break an otherwise-successful response —
// this field is additive context, not load-bearing.
function tryExplain(rawPayload, requestType, viewerRole) {
    try {
        return explain.summarize(explain.interpret(explain.parseRequest(rawPayload, requestType), requestType), viewerRole);
    } catch (e) {
        return null;
    }
}

// nlpPayload schema validation — H4 fix
// Ensures only expected fields with expected types reach Fabric chaincode
function validateNlpPayload(p) {
    if (!p || typeof p !== 'object') return 'nlpPayload must be an object.';
    if (typeof p.gpa !== 'number' || p.gpa < 0 || p.gpa > 4.0)
        return 'nlpPayload.gpa must be a number between 0 and 4.0.';
    if (!Array.isArray(p.courses_completed))
        return 'nlpPayload.courses_completed must be an array.';
    if (p.courses_completed.length > 20)
        return 'nlpPayload.courses_completed too long.';
    const VALID_COURSES = new Set(['CIS4385C','CIS4360','CIS4361','CNT4406','COP3710','COP3014C']);
    for (const c of p.courses_completed) {
        if (!VALID_COURSES.has(c)) return `Invalid course code: ${c}`;
    }
    if (typeof p.bert_confidence !== 'number' || p.bert_confidence < 0 || p.bert_confidence > 1)
        return 'nlpPayload.bert_confidence must be between 0 and 1.';
    if (typeof p.eligibility_score !== 'number' || p.eligibility_score < 0 || p.eligibility_score > 1)
        return 'nlpPayload.eligibility_score must be between 0 and 1.';
    if (p.student_name && (typeof p.student_name !== 'string' || p.student_name.length > 100))
        return 'nlpPayload.student_name invalid.';
    return null; // valid
}

// C4 fix: never send internal error details to the client
function safeError(e, fallback = 'An internal error occurred.') {
    if (IS_PROD) return fallback;
    // In dev, show the message but not the full stack
    return typeof e?.message === 'string' ? e.message.substring(0, 200) : fallback;
}

// ════════════════════════════════════════════════════════════════════════════
//  HEALTH — public
// ════════════════════════════════════════════════════════════════════════════
app.get('/health', (_req, res) => res.json({
    status:         'ok',
    system:         'CertChain',
    program:        'FAMU-FCCS',
    pqCryptography: 'CRYSTALS-Dilithium3',
    timestamp:      new Date().toISOString(),
    version:        '3.0',
}));

// ════════════════════════════════════════════════════════════════════════════
//  AUTH ENDPOINTS
// ════════════════════════════════════════════════════════════════════════════

// POST /auth/login
app.post('/auth/login', async (req, res) => {
    const { userID, password } = req.body || {};
    if (typeof userID !== 'string' || typeof password !== 'string')
        return res.status(400).json({ ok: false, error: 'userID and password required.' });

    const result = await auth.login(userID, password);
    return res.status(result.ok ? 200 : 401).json(result);
});

// POST /auth/logout
app.post('/auth/logout', (req, res) => {
    const token = (req.headers.authorization || '').replace('Bearer ', '').trim();
    auth.logout(token);
    return res.json({ ok: true });
});

// POST /auth/register
app.post('/auth/register', async (req, res) => {
    const result = await auth.register(req.body || {});
    return res.status(result.ok ? 201 : 400).json(result);
});

// POST /auth/change-password
app.post('/auth/change-password', auth.requireAuth(), async (req, res) => {
    const { currentPassword, newPassword } = req.body || {};
    if (typeof currentPassword !== 'string' || typeof newPassword !== 'string')
        return res.status(400).json({ ok: false, error: 'currentPassword and newPassword required.' });
    if (newPassword.length < 8 || newPassword.length > 128)
        return res.status(400).json({ ok: false, error: 'New password must be 8–128 characters.' });

    // Verify current password before changing
    const verify = await auth.login(req.session.userID, currentPassword);
    if (!verify.ok)
        return res.status(401).json({ ok: false, error: 'Current password incorrect.' });

    const usersPath = path.join(__dirname, 'users.json');
    const store = JSON.parse(fs.readFileSync(usersPath, 'utf8'));
    const user  = store.users.find(u => u.userID === req.session.userID);
    if (!user) return res.status(404).json({ ok: false, error: 'User not found.' });

    user.passwordHash = await auth.hashPassword(newPassword);
    // Atomic write (C2 fix applied here too)
    const tmp = usersPath + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(store, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, usersPath);

    // Invalidate existing session to force re-login with new password
    const token = (req.headers.authorization || '').replace('Bearer ', '').trim();
    auth.logout(token);

    return res.json({ ok: true, message: 'Password updated. Please log in again.' });
});

// ════════════════════════════════════════════════════════════════════════════
//  ADMIN ENDPOINTS
// ════════════════════════════════════════════════════════════════════════════

app.get('/admin/pending', auth.requireAuth(['admin']), (_req, res) => {
    return res.json({ ok: true, pending: auth.getPendingRegistrations() });
});

app.post('/admin/approve/:userID', auth.requireAuth(['admin']), (req, res) => {
    const target = auth.sanitizeStr(req.params.userID, 64);
    const token  = (req.headers.authorization || '').replace('Bearer ', '').trim();
    const result = auth.approveUser(token, target);
    return res.status(result.ok ? 200 : 403).json(result);
});

app.post('/admin/reject/:userID', auth.requireAuth(['admin']), (req, res) => {
    const target = auth.sanitizeStr(req.params.userID, 64);
    const reason = auth.sanitizeStr((req.body || {}).reason || '', 200);
    const token  = (req.headers.authorization || '').replace('Bearer ', '').trim();
    const result = auth.rejectUser(token, target, reason);
    return res.status(result.ok ? 200 : 403).json(result);
});

app.get('/admin/users', auth.requireAuth(['admin']), (req, res) => {
    const token  = (req.headers.authorization || '').replace('Bearer ', '').trim();
    const result = auth.listUsers(token);
    return res.status(result.ok ? 200 : 403).json(result);
});

// ════════════════════════════════════════════════════════════════════════════
//  CREDENTIAL ENDPOINTS
// ════════════════════════════════════════════════════════════════════════════

// POST /issue
app.post('/issue', auth.requireAuth(['institution', 'admin']), async (req, res) => {
    const { studentID, nlpPayload } = req.body || {};

    if (!validateStudentID(studentID))
        return res.status(400).json({ error: 'Invalid studentID format.' });

    // H4 fix: strict schema validation before passing to Fabric
    const schemaError = validateNlpPayload(nlpPayload);
    if (schemaError)
        return res.status(400).json({ error: schemaError });

    if (nlpPayload.bert_confidence < 0.60)
        return res.status(422).json({ error: 'BERT confidence below threshold.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        // Rebuild a clean payload object — never pass raw user input directly to chaincode
        const cleanPayload = {
            gpa:               Number(nlpPayload.gpa.toFixed(2)),
            courses_completed: nlpPayload.courses_completed,
            bert_confidence:   Number(nlpPayload.bert_confidence.toFixed(4)),
            eligibility_score: Number(nlpPayload.eligibility_score.toFixed(4)),
            student_name:      auth.sanitizeStr(nlpPayload.student_name || '', 100),
        };
        const result = await contract.submitTransaction(
            'issueMicroCredential', studentID, JSON.stringify(cleanPayload));
        await gateway.disconnect();
        const parsed = JSON.parse(result.toString());
        const explanation = tryExplain(parsed, explain.REQUEST_TYPES.CREDENTIAL_ISSUANCE, toViewerRole(req.session.role));
        return res.status(parsed.success ? 201 : 422).json(explanation ? { ...parsed, explanation } : parsed);
    } catch(e) {
        console.error({ id: req.id, route: '/issue', error: e.message });
        return res.status(500).json({ error: safeError(e) });  // C4 fix
    }
});

// ════════════════════════════════════════════════════════════════════════════
//  TRANSCRIPT UPLOAD — extracts text from PDF/DOCX/TXT, hands it to the
//  existing integration/pipeline.py --transcript path unchanged. Extraction
//  lives entirely in Node (see transcript_extract.js); BERT parsing and
//  scoring stay entirely in Python. Processing runs asynchronously — the
//  Python subprocess spins up a fresh interpreter and may load a BERT
//  model from disk, which is not reliably fast enough to hold an HTTP
//  request open for. Poll GET /transcripts/status/:uploadID for the result.
// ════════════════════════════════════════════════════════════════════════════
const UPLOAD_DIR = path.join(os.tmpdir(), 'certchain-uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const ALLOWED_UPLOAD_MIME = new Set([
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
]);
const ALLOWED_UPLOAD_EXT = new Set(['.pdf', '.docx', '.txt']);

const transcriptUpload = multer({
    dest: UPLOAD_DIR,
    limits: { fileSize: 10 * 1024 * 1024, files: 1 }, // 10MB — reject bigger uploads at the route level
    fileFilter: (req, file, cb) => {
        const ext = path.extname(file.originalname || '').toLowerCase();
        if (!ALLOWED_UPLOAD_MIME.has(file.mimetype) && !ALLOWED_UPLOAD_EXT.has(ext)) {
            return cb(new Error(`Unsupported file type: ${ext || file.mimetype}. Only PDF, DOCX, and TXT are accepted.`));
        }
        cb(null, true);
    },
});

// In-memory job store — consistent with how api/auth.js keeps sessions
// in-memory; this system has no database. Jobs are not persisted across
// a server restart, which is an accepted limitation of this scale of
// deployment (same as sessions).
const uploadJobs = new Map(); // uploadID -> { status, result, error, createdAt }

function cleanupFiles(paths) {
    for (const p of paths) { fs.unlink(p, () => { /* best effort */ }); }
}

async function processUpload(uploadID, file, studentID, authToken) {
    let text;
    try {
        const extracted = await extractText(file.path, file.mimetype, file.originalname);
        text = extracted.text;
    } catch (e) {
        cleanupFiles([file.path]);
        throw new Error(`Text extraction failed: ${e.message}`);
    }

    const tmpTextPath = file.path + '.txt';
    const tmpOutPath  = file.path + '.result.json';
    fs.writeFileSync(tmpTextPath, text, 'utf8');

    try {
        await new Promise((resolve, reject) => {
            execFile('python3', [
                path.join(__dirname, '..', 'integration', 'pipeline.py'),
                '--transcript', tmpTextPath,
                '--student', studentID,
                '--output', tmpOutPath,
            ], {
                timeout: 120000, // 2 min — Python startup + possible BERT model load
                // pipeline.py's own /issue call loops back into this same server —
                // point it at the port we're actually listening on, not its
                // http://localhost:3000 default, which only works by coincidence
                // when PORT is left unset.
                env: { ...process.env, CERTCHAIN_TOKEN: authToken, CERTCHAIN_API: `http://localhost:${PORT}` },
            }, (err, stdout, stderr) => {
                if (err) return reject(new Error(`pipeline.py failed: ${(stderr || err.message).slice(0, 500)}`));
                resolve();
            });
        });

        if (!fs.existsSync(tmpOutPath)) {
            throw new Error('pipeline.py did not produce a result file.');
        }
        const result = JSON.parse(fs.readFileSync(tmpOutPath, 'utf8'));
        uploadJobs.set(uploadID, { status: 'complete', result, createdAt: Date.now() });
    } finally {
        cleanupFiles([file.path, tmpTextPath, tmpOutPath]);
    }
}

// POST /transcripts/upload — multipart field name: "transcript"; body also needs studentID
app.post('/transcripts/upload', auth.requireAuth(['institution', 'admin']), (req, res) => {
    transcriptUpload.single('transcript')(req, res, (err) => {
        if (err instanceof multer.MulterError) {
            if (err.code === 'LIMIT_FILE_SIZE')
                return res.status(413).json({ error: 'File exceeds the 10MB limit.' });
            return res.status(400).json({ error: err.message });
        }
        if (err) return res.status(415).json({ error: err.message }); // fileFilter rejection

        if (!req.file)
            return res.status(400).json({ error: 'No file uploaded (multipart field name must be "transcript").' });

        const studentID = req.body.studentID;
        if (!validateStudentID(studentID)) {
            cleanupFiles([req.file.path]);
            return res.status(400).json({ error: 'Invalid or missing studentID format.' });
        }

        const uploadID = crypto.randomBytes(16).toString('hex');
        uploadJobs.set(uploadID, { status: 'processing', createdAt: Date.now() });
        res.status(202).json({ uploadID, status: 'processing' });

        // Processing continues after the response is sent — errors are
        // recorded on the job, never silently dropped (H4/data-entry fix:
        // a bad upload must surface as a failed status, not disappear).
        const authToken = (req.headers.authorization || '').replace('Bearer ', '').trim();
        processUpload(uploadID, req.file, studentID, authToken).catch((e) => {
            console.error({ id: req.id, route: '/transcripts/upload', uploadID, error: e.message });
            uploadJobs.set(uploadID, { status: 'failed', error: safeError(e), createdAt: Date.now() });
        });
    });
});

// GET /transcripts/status/:uploadID
app.get('/transcripts/status/:uploadID', auth.requireAuth(['institution', 'admin']), (req, res) => {
    const job = uploadJobs.get(req.params.uploadID);
    if (!job) return res.status(404).json({ error: 'Unknown uploadID.' });
    return res.json({ uploadID: req.params.uploadID, ...job });
});

// GET /verify/:hash
app.get('/verify/:hash', auth.requireAuth(), async (req, res) => {
    if (!validateHash(req.params.hash))
        return res.status(400).json({ error: 'Invalid hash format.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('verifyCredential', req.params.hash);
        await gateway.disconnect();
        const parsed = JSON.parse(result.toString());
        const explanation = tryExplain(parsed, explain.REQUEST_TYPES.CREDENTIAL_VERIFICATION, toViewerRole(req.session.role));
        res.setHeader('Content-Type', 'application/ld+json');
        return res.json(explanation ? { ...parsed, explanation } : parsed);
    } catch(e) {
        console.error({ id: req.id, route: '/verify', error: e.message });
        return res.status(500).json({ error: safeError(e) });
    }
});

// GET /student/:id
app.get('/student/:id', auth.requireAuth(), async (req, res) => {
    const sess = req.session;
    const targetID = auth.sanitizeStr(req.params.id, 64);

    if (!validateStudentID(targetID))
        return res.status(400).json({ error: 'Invalid student ID format.' });

    if (sess.role === 'student' && sess.userID !== targetID)
        return res.status(403).json({ error: 'Access denied.' });

    try {
        const { contract, gateway } = await getContract(sess.fabricID);
        const result = await contract.evaluateTransaction('getStudentCredentials', targetID);
        await gateway.disconnect();
        res.setHeader('Content-Type', 'application/ld+json');
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        return res.status(500).json({ error: safeError(e) });
    }
});

// POST /revoke
app.post('/revoke', auth.requireAuth(['institution', 'admin']), async (req, res) => {
    const { credHash, reason } = req.body || {};
    if (!validateHash(credHash))
        return res.status(400).json({ error: 'Invalid credential hash format.' });

    const cleanReason = auth.sanitizeStr(reason || '', 200);

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.submitTransaction('revokeCredential', credHash, cleanReason);
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        return res.status(500).json({ error: safeError(e) });
    }
});

// GET /analytics
app.get('/analytics', auth.requireAuth(['institution', 'admin']), async (req, res) => {
    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getProgramAnalytics');
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        return res.status(403).json({ error: safeError(e) });
    }
});

// ════════════════════════════════════════════════════════════════════════════
//  MMR BATCH ANCHORING — additive integrity layer (see chaincode/mmr.js)
//  Batches credentials into a Merkle Mountain Range so a verifier can audit
//  many credentials against one compact anchored root, instead of only the
//  existing per-credential O(1) hash lookup at /verify/:hash.
// ════════════════════════════════════════════════════════════════════════════

// GET /mmr/unanchored?since=<ISO8601>  — batch-selection helper
app.get('/mmr/unanchored', auth.requireAuth(['institution', 'admin']), async (req, res) => {
    const since = typeof req.query.since === 'string' ? auth.sanitizeStr(req.query.since, 40) : '';
    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getUnanchoredCredentials', since);
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        console.error({ id: req.id, route: '/mmr/unanchored', error: e.message });
        return res.status(500).json({ error: safeError(e) });
    }
});

// POST /mmr/anchor  — body: { batchId, credHashes: [ ... ] }
// Builds the MMR off-chain to derive the root, then submits it to the
// chaincode, which independently recomputes the root from the same
// credHashes and rejects the transaction if it disagrees (see
// anchorMMRRoot in chaincode/certchain.js) — this endpoint cannot force
// through a bogus root, it can only propose one.
app.post('/mmr/anchor', auth.requireAuth(['institution', 'admin']), async (req, res) => {
    const { batchId, credHashes } = req.body || {};

    if (!validateBatchId(batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });
    if (!Array.isArray(credHashes) || credHashes.length === 0 || credHashes.length > 500)
        return res.status(400).json({ error: 'credHashes must be a non-empty array (max 500).' });
    if (!credHashes.every(validateHash))
        return res.status(400).json({ error: 'One or more credHashes are not valid SHA-256 hex hashes.' });

    let built;
    try { built = mmr.buildMMR(credHashes); }
    catch(e) { return res.status(400).json({ error: safeError(e) }); }

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.submitTransaction(
            'anchorMMRRoot', batchId, built.root, JSON.stringify(credHashes), new Date().toISOString());
        await gateway.disconnect();
        return res.status(201).json(JSON.parse(result.toString()));
    } catch(e) {
        console.error({ id: req.id, route: '/mmr/anchor', error: e.message });
        return res.status(422).json({ error: safeError(e) });
    }
});

// GET /mmr/root/:batchId
app.get('/mmr/root/:batchId', auth.requireAuth(), async (req, res) => {
    if (!validateBatchId(req.params.batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getMMRRoot', req.params.batchId);
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        return res.status(404).json({ error: safeError(e, 'Batch not found.') });
    }
});

// GET /mmr/batch/:batchId/members
app.get('/mmr/batch/:batchId/members', auth.requireAuth(), async (req, res) => {
    if (!validateBatchId(req.params.batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getMMRBatchMembers', req.params.batchId);
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        return res.status(500).json({ error: safeError(e) });
    }
});

// GET /mmr/proof/:batchId/:credHash
// Rebuilds the batch's MMR from its on-chain leaf list and returns an
// inclusion proof for credHash — the thing a verifier needs to audit one
// credential against the batch's compact anchored root via POST /mmr/verify.
app.get('/mmr/proof/:batchId/:credHash', auth.requireAuth(), async (req, res) => {
    const { batchId, credHash } = req.params;
    if (!validateBatchId(batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });
    if (!validateHash(credHash))
        return res.status(400).json({ error: 'Invalid hash format.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const membersResult = await contract.evaluateTransaction('getMMRBatchMembers', batchId);
        await gateway.disconnect();
        const { credHashes } = JSON.parse(membersResult.toString());

        const leafIndex = credHashes.indexOf(credHash);
        if (leafIndex === -1)
            return res.status(404).json({ error: `Credential not found in batch '${batchId}'.` });

        const built = mmr.buildMMR(credHashes);
        const proof = mmr.generateProof(built, leafIndex);
        return res.json({ credHash, batchId, proof });
    } catch(e) {
        console.error({ id: req.id, route: '/mmr/proof', error: e.message });
        return res.status(500).json({ error: safeError(e) });
    }
});

// POST /mmr/verify  — body: { credHash, batchId, proof }
// Complements GET /verify/:hash (single-credential lookup): this audits a
// credential against a compact root covering its whole batch, using a
// caller-supplied inclusion proof. Verification happens on-chain — the
// chaincode cross-checks proof.root against the ledger's own anchored
// root, so a proof that is merely self-consistent is not enough.
app.post('/mmr/verify', auth.requireAuth(), async (req, res) => {
    const { credHash, batchId, proof } = req.body || {};
    if (!validateHash(credHash))
        return res.status(400).json({ error: 'Invalid credential hash format.' });
    if (!validateBatchId(batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });
    if (!proof || typeof proof !== 'object')
        return res.status(400).json({ error: 'proof is required.' });

    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction(
            'verifyMMRInclusion', credHash, batchId, JSON.stringify(proof));
        await gateway.disconnect();
        res.setHeader('Content-Type', 'application/ld+json');
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        console.error({ id: req.id, route: '/mmr/verify', error: e.message });
        return res.status(500).json({ error: safeError(e) });
    }
});

// GET /verify-batch?batchId=X&sampleSize=M&rounds=r
// IN ADDITION TO the full/per-credential path above (/mmr/verify), not a
// replacement: samples M items per round (without replacement, exponential
// growth across rounds — see api/mmr_sampling.js) instead of checking every
// credential in the batch, and reuses the exact same on-chain
// verifyMMRInclusion check per sampled item. Reports a statistical
// confidence rather than a definitive yes/no over the whole batch.
app.get('/verify-batch', auth.requireAuth(), async (req, res) => {
    if (!validateBatchId(req.query.batchId))
        return res.status(400).json({ error: 'Invalid batchId format.' });

    const sampleSize = parseInt(req.query.sampleSize, 10) || sampling.DEFAULT_BASE_SAMPLE_SIZE;
    const rounds      = parseInt(req.query.rounds, 10)     || sampling.DEFAULT_ROUNDS;
    if (!Number.isInteger(sampleSize) || sampleSize < 1 || sampleSize > 200)
        return res.status(400).json({ error: 'sampleSize must be an integer between 1 and 200.' });
    if (!Number.isInteger(rounds) || rounds < 1 || rounds > 20)
        return res.status(400).json({ error: 'rounds must be an integer between 1 and 20.' });

    const batchId = req.query.batchId;
    let contract, gateway;
    try {
        ({ contract, gateway } = await getContract(req.session.fabricID));

        const membersResult = await contract.evaluateTransaction('getMMRBatchMembers', batchId);
        const { credHashes } = JSON.parse(membersResult.toString());
        if (!credHashes || credHashes.length === 0)
            return res.status(404).json({ error: `Batch '${batchId}' not found or empty.` });

        const built = mmr.buildMMR(credHashes);

        const verifyOne = async (credHash) => {
            const leafIndex = credHashes.indexOf(credHash);
            const proof = mmr.generateProof(built, leafIndex);
            const result = await contract.evaluateTransaction(
                'verifyMMRInclusion', credHash, batchId, JSON.stringify(proof));
            return JSON.parse(result.toString()).isValid === true;
        };

        const { roundsRun, itemsChecked, itemsFlagged, perRound } = await sampling.runSamplingRounds({
            items: credHashes,
            baseSampleSize: sampleSize,
            rounds,
            growthFactor: sampling.DEFAULT_GROWTH_FACTOR,
            verifyOne,
        });

        const confidenceLevel = sampling.computeConfidence(sampling.DEFAULT_PV, roundsRun);

        const responseBody = {
            confidenceLevel,
            roundsRun,
            itemsChecked,
            itemsFlagged,
            batchId,
            batchSize: credHashes.length,
            sampleSize,
            perRound,
            pv:           sampling.DEFAULT_PV,
            pvProvenance: sampling.DEFAULT_PV_PROVENANCE,
        };
        const explanation = tryExplain(responseBody, explain.REQUEST_TYPES.MMR_BATCH_VERIFICATION, toViewerRole(req.session.role));
        return res.json(explanation ? { ...responseBody, explanation } : responseBody);
    } catch(e) {
        console.error({ id: req.id, route: '/verify-batch', error: e.message });
        return res.status(500).json({ error: safeError(e) });
    } finally {
        if (gateway) await gateway.disconnect();
    }
});


// GET /admin/verify-alerts — hash mismatch alerts (Item 3)
app.get('/admin/verify-alerts', auth.requireAuth(['admin']), async (req, res) => {
    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getMismatchAlerts');
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        // If chaincode not yet upgraded, return empty alerts
        console.error({ id: req.id, route: '/admin/verify-alerts', error: e.message });
        return res.json({ alertCount: 0, alerts: [], note: 'Chaincode upgrade pending' });
    }
});

// GET /admin/verify-log — full verification log (Item 3)
app.get('/admin/verify-log', auth.requireAuth(['admin', 'institution']), async (req, res) => {
    const limit = Math.min(parseInt(req.query.limit||'50'), 200);
    try {
        const { contract, gateway } = await getContract(req.session.fabricID);
        const result = await contract.evaluateTransaction('getVerificationLog', String(limit));
        await gateway.disconnect();
        return res.json(JSON.parse(result.toString()));
    } catch(e) {
        console.error({ id: req.id, route: '/admin/verify-log', error: e.message });
        return res.json({ count: 0, entries: [], alerts: 0, note: 'Chaincode upgrade pending' });
    }
});

// ════════════════════════════════════════════════════════════════════════════
//  ISSUE REPORTING — flag that CertChain itself isn't working correctly.
//  Not credential feedback: no MMR, no blockchain, no new RBAC role. A flat
//  JSON log is genuinely appropriate here (support tickets, not credentials).
// ════════════════════════════════════════════════════════════════════════════

// POST /report-issue — any authenticated role
app.post('/report-issue', auth.requireAuth(), (req, res) => {
    const description = auth.sanitizeStr((req.body || {}).description || '', 2000);
    if (!description || description.length < 5)
        return res.status(400).json({ error: 'description is required (min 5 characters).' });

    const credentialIdRaw = (req.body || {}).credentialId;
    let credentialId = null;
    if (credentialIdRaw) {
        if (!validateHash(credentialIdRaw))
            return res.status(400).json({ error: 'credentialId, if provided, must be a valid credential hash.' });
        credentialId = credentialIdRaw;
    }

    const issue = issues.createIssue({
        reporterID:   req.session.userID,
        reporterRole: req.session.role,
        description,
        credentialId,
    });
    return res.status(201).json({ ok: true, issue });
});

// GET /issues — admin only
app.get('/issues', auth.requireAuth(['admin']), (_req, res) => {
    return res.json({ issues: issues.listIssues() });
});

// PATCH /issues/:id — admin only
app.patch('/issues/:id', auth.requireAuth(['admin']), (req, res) => {
    const status = (req.body || {}).status;
    const result = issues.updateIssueStatus(req.params.id, status);
    if (!result.ok) {
        const code = result.error === 'Issue not found.' ? 404 : 400;
        return res.status(code).json({ error: result.error });
    }
    return res.json({ ok: true, issue: result.issue });
});

// ════════════════════════════════════════════════════════════════════════════
//  ORE (MORES) — Phase 7 scaffolding, cryptographic core paused
//  Diagnostic only: proves the Node → Python sidecar chain is wired
//  (crypto/mores_service.py must be running separately). No range-query
//  API is exposed here — that would imply a working feature that doesn't
//  exist yet. Every response comes back as the sidecar's stub 501.
// ════════════════════════════════════════════════════════════════════════════
app.get('/ore/status', auth.requireAuth(['admin']), async (_req, res) => {
    try {
        const { status, body } = await mores.kgen();
        return res.json({ sidecarReachable: true, sidecarStatus: status, sidecarResponse: body });
    } catch (e) {
        return res.json({ sidecarReachable: false, error: safeError(e) });
    }
});

// ── 404 ───────────────────────────────────────────────────────────────────────
app.use((_req, res) => res.status(404).json({ error: 'Route not found.' }));

// ── Error handler ─────────────────────────────────────────────────────────────
// C4 fix: never leak stack traces or internal details
app.use((err, req, res, _next) => {
    if (err.message?.startsWith('CORS_BLOCKED'))
        return res.status(403).json({ error: 'Origin not allowed.' });
    if (err.type === 'entity.parse.failed')
        return res.status(400).json({ error: 'Invalid JSON.' });
    if (err.status === 413)
        return res.status(413).json({ error: 'Request too large.' });
    console.error({ id: req.id, error: err.message });
    return res.status(500).json({ error: 'Internal server error.' });
});

app.listen(PORT, () => {
    console.log(`\n  CertChain API v3 (Hardened)  →  http://localhost:${PORT}`);
    console.log('  Helmet: ✓  Rate-limiting: ✓  bcrypt: ✓  Atomic writes: ✓\n');
});

module.exports = app;
