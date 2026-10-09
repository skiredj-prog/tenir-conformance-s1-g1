"""S11 — Transition object binding across admission and commit."""
from __future__ import annotations

from explorer import ExploreResult, explore


def hyp_s11_binding() -> ExploreResult:
    INITIAL = ("T1", "T1", "D1", "D1", "idle", "none")

    def admit(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "idle":
            yield ("T1", ct, "D1", cd, "admitted", effect)

    def swap_id(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "admitted":
            yield (at, "T2", ad, cd, phase, effect)

    def swap_digest(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "admitted":
            yield (at, ct, ad, "D2", phase, effect)

    def commit_bound(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "admitted" and at == ct and ad == cd:
            yield (at, ct, ad, cd, "committed", effect)

    def commit_unbound(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "admitted":
            yield (at, ct, ad, cd, "committed", effect)

    def execute(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "committed" and effect == "none":
            yield (at, ct, ad, cd, "executed", "effect")

    def violate(s):
        at, ct, ad, cd, phase, effect = s
        return effect == "effect" and (at != ct or ad != cd)

    def trigger(s):
        at, ct, ad, cd, phase, effect = s
        return at != ct or ad != cd

    return explore(
        hypothesis_id="S11-H1",
        invariant_name="CommitObjectEqualsAdmittedObject",
        initial=INITIAL,
        actions={
            "admit": admit,
            "swap_id": swap_id,
            "swap_digest": swap_digest,
            "commit_bound": commit_bound,
            "commit_unbound": commit_unbound,
            "execute": execute,
        },
        violates=violate,
        trigger_present=trigger,
    )


def hyp_s11_intended_only() -> ExploreResult:
    INITIAL = ("T1", "T1", "D1", "D1", "idle", "none")

    def admit(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "idle":
            yield ("T1", "T1", "D1", "D1", "admitted", effect)

    def commit_bound(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "admitted" and at == ct and ad == cd:
            yield (at, ct, ad, cd, "committed", effect)

    def execute(s):
        at, ct, ad, cd, phase, effect = s
        if phase == "committed" and effect == "none":
            yield (at, ct, ad, cd, "executed", "effect")

    def violate(s):
        at, ct, ad, cd, phase, effect = s
        return effect == "effect" and (at != ct or ad != cd)

    def trigger(s):
        at, ct, ad, cd, phase, effect = s
        return at != ct or ad != cd

    return explore(
        hypothesis_id="S11-H1-intended-only",
        invariant_name="CommitObjectEqualsAdmittedObject (intended)",
        initial=INITIAL,
        actions={"admit": admit, "commit_bound": commit_bound, "execute": execute},
        violates=violate,
        trigger_present=trigger,
    )


def run_s11_suite() -> list[ExploreResult]:
    return [hyp_s11_binding(), hyp_s11_intended_only()]
