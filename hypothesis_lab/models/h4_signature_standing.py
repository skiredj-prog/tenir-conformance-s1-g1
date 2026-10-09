"""H4 — A valid signature is not sufficient standing.

Cryptographic validity alone does not establish authority to authorize an action.

States: SIGNATURE_INVALID | VALID_UNTRUSTED_KEY | VALID_INSUFFICIENT_STANDING |
        VALID_AUTHORIZED_SCOPE (encoded as sig/trust/standing fields).
"""
from __future__ import annotations

from explorer import ExploreResult, explore


def _s(sig, trust, standing, admitted=False, effect="none"):
    return (sig, trust, standing, admitted, effect)


INITIAL = _s("none", "unknown", "none", False, "none")


def hyp_h4_signature_not_standing() -> ExploreResult:
    def present_invalid_sig(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("invalid", trust, standing, adm, eff)

    def present_valid_untrusted(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "untrusted", "none", adm, eff)

    def present_valid_insufficient(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "trusted", "insufficient", adm, eff)

    def present_valid_authorized(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "trusted", "authorized", adm, eff)

    def admit_honest(s):
        sig, trust, standing, adm, eff = s
        if (not adm and sig == "valid" and trust == "trusted" and standing == "authorized"):
            yield _s(sig, trust, standing, True, eff)

    def admit_collapse_crypto(s):
        """Adversarial: any valid signature admits (ignores trust/standing)."""
        sig, trust, standing, adm, eff = s
        if not adm and sig == "valid":
            yield _s(sig, trust, standing, True, eff)

    def execute(s):
        sig, trust, standing, adm, eff = s
        if adm and eff == "none":
            yield _s(sig, trust, standing, adm, "executed")

    def violate(s):
        sig, trust, standing, adm, eff = s
        if eff != "executed":
            return False
        if sig != "valid" or trust != "trusted" or standing != "authorized":
            return True
        return False

    def trigger(s):
        sig, trust, standing, adm, eff = s
        return sig == "valid" and (trust != "trusted" or standing != "authorized")

    return explore(
        hypothesis_id="H4-signature-not-standing",
        invariant_name="NoEffectUnlessValidTrustedAuthorized",
        initial=INITIAL,
        actions={
            "present_invalid_sig": present_invalid_sig,
            "present_valid_untrusted": present_valid_untrusted,
            "present_valid_insufficient": present_valid_insufficient,
            "present_valid_authorized": present_valid_authorized,
            "admit_honest": admit_honest,
            "admit_collapse_crypto": admit_collapse_crypto,
            "execute": execute,
        },
        violates=violate,
        trigger_present=trigger,
    )


def hyp_h4_intended_only() -> ExploreResult:
    def present_valid_untrusted(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "untrusted", "none", adm, eff)

    def present_valid_insufficient(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "trusted", "insufficient", adm, eff)

    def present_valid_authorized(s):
        sig, trust, standing, adm, eff = s
        if sig == "none":
            yield _s("valid", "trusted", "authorized", adm, eff)

    def admit_honest(s):
        sig, trust, standing, adm, eff = s
        if (not adm and sig == "valid" and trust == "trusted" and standing == "authorized"):
            yield _s(sig, trust, standing, True, eff)

    def execute(s):
        sig, trust, standing, adm, eff = s
        if adm and eff == "none":
            yield _s(sig, trust, standing, adm, "executed")

    def violate(s):
        sig, trust, standing, adm, eff = s
        if eff != "executed":
            return False
        return not (sig == "valid" and trust == "trusted" and standing == "authorized")

    def trigger(s):
        sig, trust, standing, adm, eff = s
        return sig == "valid" and (trust != "trusted" or standing != "authorized")

    return explore(
        hypothesis_id="H4-intended-only",
        invariant_name="NoEffectUnlessValidTrustedAuthorized (intended)",
        initial=INITIAL,
        actions={
            "present_valid_untrusted": present_valid_untrusted,
            "present_valid_insufficient": present_valid_insufficient,
            "present_valid_authorized": present_valid_authorized,
            "admit_honest": admit_honest,
            "execute": execute,
        },
        violates=violate,
        trigger_present=trigger,
    )


def run_h4_suite() -> list[ExploreResult]:
    return [hyp_h4_signature_not_standing(), hyp_h4_intended_only()]
