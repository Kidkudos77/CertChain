"""
CertChain — UNIQUE (Kwon & Hahn) — building block verified, full construction blocked
==========================================================================================
UNIQUE is NOT implemented here. This module exists to say precisely why,
and precisely what would unblock it — not to be a stub that silently does
nothing, the way crypto/mores_service.py's pre-transcription stubs worked.

What IS verified and built: crypto/dere.py (Delegable Equality-Revealing
Encryption, Section 3) — UNIQUE's underlying building block. Its
correctness was checked two ways: worked through the pairing algebra by
hand (see dere.py's docstring), and confirmed against known-answer tests
(crypto/dere_selftest.py) across multiple equal/unequal message pairs,
including repeated runs with fresh randomness. A real transcription error
was caught and fixed in this process: an early pass had DERE.TokGen's
second token using alpha(u)/beta(u) (division); working the algebra by
hand showed that form doesn't cancel and would make equality-testing fail
even for equal messages — re-checking directly against the source PDF
confirmed the paper actually states alpha(u)*beta(u) (product). Fixed and
re-verified before any code was written against the wrong form.

What is NOT implemented, and why: UNIQUE's own contribution over DERE is
replacing DERE's bidirectional token pair (both parties must generate a
token for each other) with a one-way token:

    OWTv->u = ( H(pk(v)^(1/alpha(u))), H(pk(v)^(beta(u))) )

The paper's correctness proof for this term (and everything built on top
of it — UNIQUE's full Setup/KeyGen/TokGen/Enc/Test, Section 4, the
bit-decomposition range-comparison construction) depends on H behaving
multiplicatively under exponentiation: H(x^c) == H(x)^c for scalars c.
An ordinary collision-resistant hash-to-group function does NOT have this
property — it would need to be instantiated as something closer to a
fixed exponentiation, H(x) = x^s for a system-wide secret/public exponent
s, which is a real cryptographic design decision, not an implementation
detail left open by the spec (the same category as choosing an HMAC for a
generic "secure PRF" placeholder — except this one changes what security
guarantee the scheme actually has, not just which primitive instantiates
it).

This is NOT a repeat of the TokGen transcription error: that one was
confirmed as a PDF-extraction character error and had a working algebraic
correction. This one was checked directly against the source PDF too and
transcribed accurately — it's a property of the published construction
itself. Guessing an instantiation of H here would mean silently
authoring the actual security design of an unpublished part of this
scheme, which is exactly what this project's standing rule (don't
improvise cryptography) exists to prevent.

Unblocking this needs a cryptographer's answer to one specific question:
what instantiation of H does Kwon & Hahn actually use or recommend for
OWTv->u, and does the paper's own proof (or a further reduction) show it's
secure for that specific instantiation? Once that answer exists, Section
4's Setup/KeyGen/TokGen/Enc/Test can be transcribed and implemented on top
of the already-verified dere.py, the same way MORES was built on top of
tie.py once its equations were confirmed.

Also still open regardless of the above (per the roadmap): whether
CertChain actually has an institution-to-institution encrypted-query use
case that needs UNIQUE's one-way token property at all, versus MORES's qk
model already covering the stated "employer shouldn't need reciprocal
access" requirement on its own.
"""

BLOCKED_REASON = (
    "UNIQUE's Section 4 construction (Setup/KeyGen/TokGen/Enc/Test) depends on "
    "OWTv->u, whose correctness proof requires H(x^c) == H(x)^c -- a property an "
    "ordinary hash-to-group function does not have. This is a cryptographic "
    "design question for the paper's own H instantiation, not an implementation "
    "gap. See this module's docstring for what specifically would unblock it."
)


def not_implemented(*_args, **_kwargs):
    raise NotImplementedError(BLOCKED_REASON)


Setup = KeyGen = TokGen = Enc = Test = not_implemented
