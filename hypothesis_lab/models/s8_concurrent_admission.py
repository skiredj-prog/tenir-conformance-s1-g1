"""S8 — concurrent same-LEI admission (bounded interleavings).

Properties:
  S8-P1  At-most-one effect for contested LEI
  S8-P2  Concurrent same-LEI admission: at most one registration
  S8-P3  Stale commit after peer already effected must not add effect

Scope: finite two-thread model only. Not multi-process, not crash recovery.
"""
from __future__ import annotations

from explorer import ExploreResult, explore


def hyp_s8_p1_at_most_one_effect_adversarial() -> ExploreResult:
    INITIAL = (0, 0, 0, 0)

    def t1_register(s):
        reg, cons, eff, lock = s
        if lock != 0:
            return
        if reg == 0:
            yield (1, cons, eff, 0)

    def t2_register(s):
        reg, cons, eff, lock = s
        if lock != 0:
            return
        if reg == 0:
            yield (1, cons, eff, 0)

    def adversarial_double_register(s):
        reg, cons, eff, lock = s
        if reg < 2:
            yield (reg + 1, cons, eff, lock)

    def consume_and_effect(s):
        reg, cons, eff, lock = s
        if reg >= 1 and cons < reg and eff < 1:
            yield (reg, cons + 1, eff + 1, lock)

    def adversarial_double_effect(s):
        reg, cons, eff, lock = s
        if reg >= 1 and eff < 2:
            yield (reg, cons, eff + 1, lock)

    return explore(
        hypothesis_id="S8-P1-adversarial",
        invariant_name="AtMostOneEffectPerLEI",
        initial=INITIAL,
        actions={
            "t1_register": t1_register,
            "t2_register": t2_register,
            "adversarial_double_register": adversarial_double_register,
            "consume_and_effect": consume_and_effect,
            "adversarial_double_effect": adversarial_double_effect,
        },
        violates=lambda s: s[2] > 1,
        trigger_present=lambda s: s[0] >= 1,
    )


def hyp_s8_p1_intended() -> ExploreResult:
    INITIAL = (0, 0, 0, 0)

    def t1_register(s):
        reg, cons, eff, lock = s
        if reg == 0:
            yield (1, cons, eff, lock)

    def t2_register(s):
        reg, cons, eff, lock = s
        if reg == 0:
            yield (1, cons, eff, lock)

    def consume_and_effect(s):
        reg, cons, eff, lock = s
        if reg == 1 and cons == 0 and eff == 0:
            yield (reg, 1, 1, lock)

    return explore(
        hypothesis_id="S8-P1-intended",
        invariant_name="AtMostOneEffectPerLEI (serialized)",
        initial=INITIAL,
        actions={
            "t1_register": t1_register,
            "t2_register": t2_register,
            "consume_and_effect": consume_and_effect,
        },
        violates=lambda s: s[2] > 1,
        trigger_present=lambda s: s[0] >= 1,
    )


def hyp_s8_p2_double_admission_adversarial() -> ExploreResult:
    INITIAL = (0, 0)

    def t1_admit(s):
        a, b = s
        if a == 0:
            yield (1, b)

    def t2_admit(s):
        a, b = s
        if b == 0:
            yield (a, 1)

    def adversarial_both_see_clear(s):
        a, b = s
        if a + b < 2:
            yield (1, 1)

    return explore(
        hypothesis_id="S8-P2-adversarial",
        invariant_name="AtMostOneSameLEIRegistration",
        initial=INITIAL,
        actions={
            "t1_admit": t1_admit,
            "t2_admit": t2_admit,
            "adversarial_both_see_clear": adversarial_both_see_clear,
        },
        violates=lambda s: s[0] + s[1] > 1,
        trigger_present=lambda s: s[0] + s[1] >= 1,
    )


def hyp_s8_p2_intended() -> ExploreResult:
    INITIAL = (0, 0)

    def t1_admit(s):
        a, b = s
        if a == 0 and b == 0:
            yield (1, b)

    def t2_admit(s):
        a, b = s
        if a == 0 and b == 0:
            yield (a, 1)

    return explore(
        hypothesis_id="S8-P2-intended",
        invariant_name="AtMostOneSameLEIRegistration (guarded)",
        initial=INITIAL,
        actions={"t1_admit": t1_admit, "t2_admit": t2_admit},
        violates=lambda s: s[0] + s[1] > 1,
        trigger_present=lambda s: s[0] + s[1] >= 1,
    )


def hyp_s8_p3_stale_commit_adversarial() -> ExploreResult:
    INITIAL = (0, 0)

    def first_effect(s):
        eff, stale = s
        if eff == 0:
            yield (1, stale)

    def mark_stale_commit(s):
        eff, stale = s
        if stale == 0:
            yield (eff, 1)

    def adversarial_apply_stale(s):
        eff, stale = s
        if stale == 1 and eff < 2:
            yield (eff + 1, stale)

    return explore(
        hypothesis_id="S8-P3-adversarial",
        invariant_name="StaleCommitDoesNotAddEffect",
        initial=INITIAL,
        actions={
            "first_effect": first_effect,
            "mark_stale_commit": mark_stale_commit,
            "adversarial_apply_stale": adversarial_apply_stale,
        },
        violates=lambda s: s[0] > 1,
        trigger_present=lambda s: s[1] == 1,
    )


def hyp_s8_p3_intended() -> ExploreResult:
    INITIAL = (0, 0)

    def first_effect(s):
        eff, stale = s
        if eff == 0:
            yield (1, stale)

    def mark_stale_commit(s):
        eff, stale = s
        if stale == 0:
            yield (eff, 1)

    return explore(
        hypothesis_id="S8-P3-intended",
        invariant_name="StaleCommitDoesNotAddEffect (honest)",
        initial=INITIAL,
        actions={
            "first_effect": first_effect,
            "mark_stale_commit": mark_stale_commit,
        },
        violates=lambda s: s[0] > 1,
        trigger_present=lambda s: s[1] == 1,
    )


def run_s8_suite() -> list[ExploreResult]:
    return [
        hyp_s8_p1_at_most_one_effect_adversarial(),
        hyp_s8_p1_intended(),
        hyp_s8_p2_double_admission_adversarial(),
        hyp_s8_p2_intended(),
        hyp_s8_p3_stale_commit_adversarial(),
        hyp_s8_p3_intended(),
    ]
