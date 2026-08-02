"""
CertChain — MORES Service (Phase 7 — cryptographic core implemented)
==========================================================================
KGen/Enc/TGen/Cmp now call the real transcribed construction (tie.py,
mores_core.py) instead of raising NotImplementedError. Per the roadmap's
equation-verification pass: transcription is done, checked algebraically
(see tie.py's docstring) and against known-answer test cases
(mores_selftest.py: equal / less-than / greater-than, including edge
cases like values differing only in their least-significant bit). It is
NOT yet independently reviewed by anyone other than the person who wrote
this transcription — see the roadmap, Phase 7, item 3. Do not treat this
as cleared for real FERPA data until that review happens.

Cmp is genuinely slow — 2n+3 pairings at ~3.5s/pairing in pure-Python
py_ecc (see mores_core.py's docstring on the measured pairing count and
its discrepancy with the paper's own Table I figure). For CertChain's
actual GPA/score bit-widths (9-12 bits per the roadmap), that's multiple
minutes per comparison — nowhere near viable synchronously. Cmp is
therefore async here: POST /mores/cmp starts the computation in a
background thread and returns a job ID immediately; GET
/mores/cmp/status/:jobId polls for the result. This is the same
uploadID+polling shape api/server.js already uses for transcript
uploads (api/transcript_extract.js) — no new pattern, just applied here
too, per the roadmap's own recommendation.

KGen/Enc/TGen involve no pairings (only group exponentiations, which are
fast even in pure Python) and stay synchronous.
"""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mores_core
import mores_serialize as ser

# ── Async job store for Cmp ─────────────────────────────────────────────────
# In-memory only, matches this sidecar's existing "long-running local process"
# scope (same as the transcript-upload job Map in api/server.js) — not meant
# to survive a restart, and that's fine for this use case.
_jobs = {}
_jobs_lock = threading.Lock()


def _run_cmp_job(job_id, ctx, ty):
    try:
        result = mores_core.cmp(ctx, ty)
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result, "finishedAt": time.time()}
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e), "finishedAt": time.time()}


def Health():
    """Cheap liveness check — no cryptographic material generated or
    returned. Exists so callers that just want to confirm the sidecar is
    reachable (e.g. api/server.js's GET /ore/status diagnostic) don't have
    to call KGen() to do it. KGen() now does real work and returns a real
    usable (msk, qk) pair — using it as a connectivity ping would silently
    leak a secret key in the HTTP response and generate a throwaway keypair
    on every status check. Caught while wiring this up, not left as a
    latent issue for whoever eventually turns on real ORE traffic.
    """
    return {"status": "ok", "cryptoCore": "implemented", "pendingIndependentReview": True}


def KGen():
    """Institution key generation -> (msk, qk), JSON-serializable."""
    msk, qk = mores_core.keygen()
    return {"msk": ser.ser_kL(msk), "qk": ser.ser_kR(qk)}


def Enc(msk, x, n, lam=None):
    """Encrypt an n-bit value x under the institution's msk."""
    msk_native = ser.deser_kL(msk)
    ctx = mores_core.enc(msk_native, int(x), int(n), lam)
    return {"ctx": ser.ser_ctx(ctx)}


def TGen(qk, y, n, lam=None):
    """Build a comparison token for value y under the verifier's qk."""
    qk_native = ser.deser_kR(qk)
    ty = mores_core.tgen(qk_native, int(y), int(n), lam)
    return {"ty": ser.ser_ty(ty)}


def CmpStart(ctx, ty):
    """Kick off an async Cmp job. Returns a jobId immediately — the actual
    (n+2)-ish-pairing computation runs in a background thread; poll
    /mores/cmp/status/:jobId for the result."""
    ctx_native = ser.deser_ctx(ctx)
    ty_native = ser.deser_ty(ty)
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending", "startedAt": time.time()}
    thread = threading.Thread(target=_run_cmp_job, args=(job_id, ctx_native, ty_native), daemon=True)
    thread.start()
    return {"jobId": job_id, "status": "pending"}


def CmpStatus(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise KeyError(f"No such job: {job_id}")
    return dict(job)


# ── HTTP sidecar ────────────────────────────────────────────────────────────
# Mirrors the shape api/server.js already uses to call into the BERT
# pipeline (a separate Python component the Node API invokes) — except this
# one is a real long-running HTTP service, since MORES needs a persistent
# process holding key material, not a one-shot subprocess per call.

POST_ROUTES = {
    "/mores/health": lambda body: Health(),
    "/mores/kgen": lambda body: KGen(),
    "/mores/enc": lambda body: Enc(body.get("msk"), body.get("x"), body.get("n"), body.get("lam")),
    "/mores/tgen": lambda body: TGen(body.get("qk"), body.get("y"), body.get("n"), body.get("lam")),
    "/mores/cmp": lambda body: CmpStart(body.get("ctx"), body.get("ty")),
}


class MoresHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/mores/cmp/status/"):
            job_id = self.path[len("/mores/cmp/status/"):]
            try:
                result = CmpStatus(job_id)
                return self._send_json(200, {"ok": True, "result": result})
            except KeyError as e:
                return self._send_json(404, {"ok": False, "error": str(e)})
        return self._send_json(404, {"error": f"No such route: {self.path}"})

    def do_POST(self):
        handler = POST_ROUTES.get(self.path)
        if handler is None:
            return self._send_json(404, {"error": f"No such route: {self.path}"})

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "Malformed JSON body."})

        try:
            result = handler(body)
            return self._send_json(200, {"ok": True, "result": result})
        except NotImplementedError as e:
            return self._send_json(501, {"ok": False, "error": str(e)})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": f"Unexpected error: {e}"})

    def log_message(self, fmt, *args):
        pass  # keep stdout quiet


def run(port=5100):
    server = ThreadingHTTPServer(("127.0.0.1", port), MoresHandler)
    print(f"MORES sidecar listening on http://127.0.0.1:{port}")
    print("Cryptographic core implemented (roadmap Phase 7) — pending independent review, see module docstring.")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5100)
    args = p.parse_args()
    run(args.port)
