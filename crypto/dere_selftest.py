"""
CertChain — DERE self-test
===============================
Known-answer correctness check for crypto/dere.py, run directly:
    python3 crypto/dere_selftest.py

Each Test() call costs 4 pairings (2 numerator + 2 denominator across d0/d1)
at ~3.5s/pairing — a few seconds per case, not the minutes MORES/TIE's
N^2 comparisons cost, since DERE.Test is a single equality check, not a
sampled/looped comparison.
"""
import time

import dere


def check(sk_u, pk_u, sk_v, pk_v, m_u, m_v, expected, label):
    ct_u = dere.enc(m_u, sk_u)
    ct_v = dere.enc(m_v, sk_v)
    tok_v_to_u = dere.tokgen(sk_u, pk_v)
    tok_u_to_v = dere.tokgen(sk_v, pk_u)

    t0 = time.time()
    result = dere.test(ct_u, ct_v, tok_v_to_u, tok_u_to_v)
    elapsed = time.time() - t0
    print(f"{label}: m_u={m_u!r}, m_v={m_v!r} -> Test={result} [{elapsed:.1f}s]")
    assert result == expected, f"FAIL ({label}): expected {expected}, got {result}"


def run():
    print("Generating DERE keys for two clients (u, v)...")
    sk_u, pk_u = dere.keygen()
    sk_v, pk_v = dere.keygen()

    check(sk_u, pk_u, sk_v, pk_v, "GPA:3.75", "GPA:3.75", True, "equal messages")
    check(sk_u, pk_u, sk_v, pk_v, "GPA:3.75", "GPA:2.90", False, "different messages")
    check(sk_u, pk_u, sk_v, pk_v, 42, 42, True, "equal integers")
    check(sk_u, pk_u, sk_v, pk_v, "", "", True, "equal empty strings")

    # Re-encrypting the SAME message under fresh randomness (r) must still
    # test equal -- this is the property that would break if the r*beta
    # term didn't fully cancel (the exact bug the division/product fix
    # addressed), so re-run the equal case a few times with fresh ct/tok
    # each time as extra assurance.
    for i in range(2):
        check(sk_u, pk_u, sk_v, pk_v, "repeat-check", "repeat-check", True, f"equal messages, fresh randomness (run {i+1})")

    print("\nDERE SELF-TEST PASSED — equality-revealing correctness verified across multiple cases.")


if __name__ == "__main__":
    run()
