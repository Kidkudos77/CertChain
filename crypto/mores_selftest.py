"""
CertChain — MORES self-test
================================
Known-answer correctness check for crypto/mores_core.py, run directly:
    python3 crypto/mores_selftest.py

Uses a small bit-width (n=3, values 0-7) to keep runtime sane — each Cmp
call costs 2n+3 pairings at ~3.5s/pairing (see mores_core.py's docstring
on the measured-vs-paper-Table-I discrepancy), so n=3 is ~9 pairings
(~31s) per comparison. This is a correctness check, not a benchmark of
CertChain's real GPA bit-width (9-12 bits per the roadmap) — that would
take minutes per comparison in pure-Python py_ecc and belongs in the
async job pattern the roadmap specifies, not a quick self-test.
"""
import time

from mores_core import cmp, enc, keygen, tgen

N_BITS = 3  # values 0..7


def check(msk, qk, x, y, expected, label):
    t0 = time.time()
    ctx = enc(msk, x, N_BITS)
    ty = tgen(qk, y, N_BITS)
    result = cmp(ctx, ty)
    elapsed = time.time() - t0
    outcome = {0: "x == y", 1: "x < y", None: "x > y"}[result]
    print(f"{label}: x={x}, y={y} -> Cmp={result!r} ({outcome}) [{elapsed:.1f}s]")
    assert result == expected, f"FAIL ({label}): expected {expected!r}, got {result!r}"


def run():
    print("Generating MORES keys...")
    msk, qk = keygen()

    check(msk, qk, 5, 5, 0, "equal")
    check(msk, qk, 2, 6, 1, "less-than")
    check(msk, qk, 6, 2, None, "greater-than")
    check(msk, qk, 0, 0, 0, "equal-at-zero-boundary")
    check(msk, qk, 4, 5, 1, "less-than-differ-at-LSB-only")
    check(msk, qk, 0, 7, 1, "less-than-extreme")
    check(msk, qk, 7, 0, None, "greater-than-extreme")

    print("\nMORES SELF-TEST PASSED — all three comparison outcomes verified against known values.")


if __name__ == "__main__":
    run()
