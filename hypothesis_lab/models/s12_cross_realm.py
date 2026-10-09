"""S12 adversarial models — Cross-Realm admissibility.

Includes intended membrane path AND adversarial bypass actions.
"""
from __future__ import annotations

from explorer import ExploreResult, explore


def _s(source, crossing, commit, effect, payload_bound=True, auth_stale=False):
    return (source, crossing, commit, effect, payload_bound, auth_stale)


INITIAL = _s("allowed", "unchecked", "none", "none", True, False)


def hyp_s12_a_source_not_crossing() -> ExploreResult:
    def evaluate_crossing_honest(s):
        src, cross, commit, effect, pb, stale = s
        if cross != "unchecked":
            return
        yield _s(src, "veto", commit, effect, pb, stale)
        yield _s(src, "pass", commit, effect, pb, stale)

    def evaluate_crossing_collapse(s):
        src, cross, commit, effect, pb, stale = s
        if cross != "unchecked":
            return
        if src == "allowed":
            yield _s(src, "pass", commit, effect, pb, stale)

    def commit_only_if_pass(s):
        src, cross, commit, effect, pb, stale = s
        if cross == "pass" and commit == "none" and pb and not stale:
            yield _s(src, cross, "committed", effect, pb, stale)

    def commit_bypass_veto(s):
        src, cross, commit, effect, pb, stale = s
        if cross == "veto" and commit == "none":
            yield _s(src, cross, "committed", effect, pb, stale)

    def execute(s):
        src, cross, commit, effect, pb, stale = s
        if commit == "committed" and effect == "none":
            yield _s(src, cross, commit, "target_effect", pb, stale)

    def violate(s):
        return s[1] == "veto" and s[3] == "target_effect"

    def trigger(s):
        return s[1] == "veto"

    return explore(
        hypothesis_id="S12-H1",
        invariant_name="NoForbiddenEffect: crossing=veto ⇒ effect=none",
        initial=INITIAL,
        actions={
            "evaluate_crossing_honest": evaluate_crossing_honest,
            "evaluate_crossing_collapse": evaluate_crossing_collapse,
            "commit_only_if_pass": commit_only_if_pass,
            "commit_bypass_veto": commit_bypass_veto,
            "execute": execute,
        },
        violates=violate,
        trigger_present=trigger,
    )


def hyp_s12_a_intended_only() -> ExploreResult:
    def evaluate_crossing_honest(s):
        src, cross, commit, effect, pb, stale = s
        if cross != "unchecked":
            return
        yield _s(src, "veto", commit, effect, pb, stale)
        yield _s(src, "pass", commit, effect, pb, stale)

    def commit_only_if_pass(s):
        src, cross, commit, effect, pb, stale = s
        if cross == "pass" and commit == "none" and pb and not stale:
            yield _s(src, cross, "committed", effect, pb, stale)

    def execute(s):
        src, cross, commit, effect, pb, stale = s
        if commit == "committed" and effect == "none":
            yield _s(src, cross, commit, "target_effect", pb, stale)

    def violate(s):
        return s[1] == "veto" and s[3] == "target_effect"

    def trigger(s):
        return s[1] == "veto"

    return explore(
        hypothesis_id="S12-H1-intended-only",
        invariant_name="NoForbiddenEffect (intended path only)",
        initial=INITIAL,
        actions={
            "evaluate_crossing_honest": evaluate_crossing_honest,
            "commit_only_if_pass": commit_only_if_pass,
            "execute": execute,
        },
        violates=violate,
        trigger_present=trigger,
    )


def hyp_s12_h2_stale_and_payload() -> ExploreResult:
    def evaluate(s):
        src, cross, commit, effect, pb, stale = s
        if cross == "unchecked":
            yield _s(src, "pass", commit, effect, pb, stale)
            yield _s(src, "veto", commit, effect, pb, stale)

    def mark_stale(s):
        src, cross, commit, effect, pb, stale = s
        if not stale:
            yield _s(src, cross, commit, effect, pb, True)

    def rebind_payload(s):
        src, cross, commit, effect, pb, stale = s
        if pb:
            yield _s(src, cross, commit, effect, False, stale)

    def commit_guarded(s):
        src, cross, commit, effect, pb, stale = s
        if cross == "pass" and commit == "none" and pb and not stale:
            yield _s(src, cross, "committed", effect, pb, stale)

    def commit_ungarded(s):
        src, cross, commit, effect, pb, stale = s
        if commit == "none":
            yield _s(src, cross, "committed", effect, pb, stale)

    def execute(s):
        src, cross, commit, effect, pb, stale = s
        if commit == "committed" and effect == "none":
            yield _s(src, cross, commit, "target_effect", pb, stale)

    def execute_without_commit(s):
        src, cross, commit, effect, pb, stale = s
        if effect == "none":
            yield _s(src, cross, commit, "target_effect", pb, stale)

    def violate(s):
        src, cross, commit, effect, pb, stale = s
        if effect != "target_effect":
            return False
        if cross == "veto" or (not pb) or stale:
            return True
        return False

    def trigger(s):
        src, cross, commit, effect, pb, stale = s
        return cross == "veto" or (not pb) or stale

    return explore(
        hypothesis_id="S12-H2",
        invariant_name="NoEffectOnVetoOrStaleOrUnboundPayload",
        initial=INITIAL,
        actions={
            "evaluate": evaluate,
            "mark_stale": mark_stale,
            "rebind_payload": rebind_payload,
            "commit_guarded": commit_guarded,
            "commit_ungarded": commit_ungarded,
            "execute": execute,
            "execute_without_commit": execute_without_commit,
        },
        violates=violate,
        trigger_present=trigger,
    )


def run_s12_suite() -> list[ExploreResult]:
    return [
        hyp_s12_a_source_not_crossing(),
        hyp_s12_a_intended_only(),
        hyp_s12_h2_stale_and_payload(),
    ]
