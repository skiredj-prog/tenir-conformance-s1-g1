"""S8 — concurrent same-LEI admission (bounded two-thread model)."""
from __future__ import annotations

from explorer import ExploreResult, explore


def hyp_s8_at_most_one_effect() -> ExploreResult:
    INITIAL = (0, 0, 0, 0)

    def t1_try_register(s):
        reg, cons, eff, lock = s
        if lock != 0:
            return
        if reg == 0:
            yield (1, cons, eff, 0)

    def t2_try_register(s):
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

    def violate(s):
        return s[2] > 1

    def trigger(s):
        return s[0] >= 1

    return explore(
        hypothesis_id="S8-H1",
        invariant_name="AtMostOneEffectPerLEI (with adversarial races)",
        initial=INITIAL,
        actions={
            "t1_try_register": t1_try_register,
            "t2_try_register": t2_try_register,
            "adversarial_double_register": adversarial_double_register,
            "consume_and_effect": consume_and_effect,
            "adversarial_double_effect": adversarial_double_effect,
        },
        violates=violate,
        trigger_present=trigger,
    )


def hyp_s8_intended_serialized() -> ExploreResult:
    INITIAL = (0, 0, 0, 0)

    def t1_try_register(s):
        reg, cons, eff, lock = s
        if reg == 0:
            yield (1, cons, eff, lock)

    def t2_try_register(s):
        reg, cons, eff, lock = s
        if reg == 0:
            yield (1, cons, eff, lock)

    def consume_and_effect(s):
        reg, cons, eff, lock = s
        if reg == 1 and cons == 0 and eff == 0:
            yield (reg, 1, 1, lock)

    def violate(s):
        return s[2] > 1

    def trigger(s):
        return s[0] >= 1

    return explore(
        hypothesis_id="S8-H1-intended-only",
        invariant_name="AtMostOneEffectPerLEI (serialized admission)",
        initial=INITIAL,
        actions={
            "t1_try_register": t1_try_register,
            "t2_try_register": t2_try_register,
            "consume_and_effect": consume_and_effect,
        },
        violates=violate,
        trigger_present=trigger,
    )


def run_s8_suite() -> list[ExploreResult]:
    return [hyp_s8_at_most_one_effect(), hyp_s8_intended_serialized()]
