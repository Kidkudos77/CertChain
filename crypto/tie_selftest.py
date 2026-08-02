"""
CertChain — TIE self-test
=============================
Standalone correctness check for crypto/tie.py, run directly:
    python3 crypto/tie_selftest.py

Each pairing takes ~3.5s in pure-Python py_ecc (see roadmap Phase 7's
performance finding), so this uses a small N (3) to keep runtime sane —
enough to exercise every branch of Dec's equality logic (some indices equal,
some not, an empty-overlap case) without a multi-minute run.
"""
import time

from tie import dec, enc_l, enc_r, keygen


def run():
    print("Generating TIE keys...")
    kL, kR = keygen()

    # ctL encrypts [10, 20, 30]; ctR encrypts [99, 20, 5]
    # Expected equal pairs (0-indexed): only (1,1) -- value 20 at position 1
    # on both sides. No other position matches on either side.
    M = [10, 20, 30]
    Mp = [99, 20, 5]

    t0 = time.time()
    ctL = enc_l(kL, M)
    ctR = enc_r(kR, Mp)
    print(f"EncL/EncR done in {time.time() - t0:.1f}s")

    t0 = time.time()
    S = dec(ctL, ctR)
    print(f"Dec done in {time.time() - t0:.1f}s (N={len(M)}x{len(Mp)} = {len(M) * len(Mp)} pairing checks)")
    print("Matched pairs:", S)

    expected = {(1, 1)}
    assert S == expected, f"FAIL: expected {expected}, got {S}"
    print("PASS: exactly the expected equal-value pair was found, nothing else.")

    # Second check: no overlap at all
    M2 = [1, 2, 3]
    M2p = [4, 5, 6]
    ctL2 = enc_l(kL, M2)
    ctR2 = enc_r(kR, M2p)
    S2 = dec(ctL2, ctR2)
    print("No-overlap case matched pairs:", S2)
    assert S2 == set(), f"FAIL: expected no matches, got {S2}"
    print("PASS: no false-positive matches when nothing overlaps.")

    # Third check: full overlap (every position equal)
    M3 = [7, 7, 7]
    M3p = [7, 7, 7]
    ctL3 = enc_l(kL, M3)
    ctR3 = enc_r(kR, M3p)
    S3 = dec(ctL3, ctR3)
    print("Full-overlap case matched pairs:", S3)
    expected3 = {(i, j) for i in range(3) for j in range(3)}
    assert S3 == expected3, f"FAIL: expected {expected3}, got {S3}"
    print("PASS: every position matches when every value is identical.")

    print("\nTIE SELF-TEST PASSED")


if __name__ == "__main__":
    run()
