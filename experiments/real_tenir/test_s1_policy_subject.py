"""S1 empirical probe against the real tenir_governance PolicyEngine.

This is deliberately NOT a conformance test. It asks what the real public
PolicyEngine can observe when S1 evidence is unavailable.

S1 requires a stateful execution/reconciliation property:
    evidence lost after commit
        -> unresolved attempt
        -> retry for same LEI MUST NOT execute.

The current PolicyEngine is a membrane classifier. It has no LEI, attempt,
permit, receipt, or reconciliation state. This experiment documents that
boundary by calling the real engine rather than a toy substitute.
"""

from __future__ import annotations

from tenir_governance.policy_engine import PolicyEngine


def test_real_policy_engine_has_no_s1_reconciliation_surface():
    policy = PolicyEngine.default()

    public_fields = set(policy.__dataclass_fields__)
    forbidden_state = {
        "lei",
        "attempt_id",
        "permit",
        "receipt",
        "reconciliation",
    }

    assert public_fields.isdisjoint(forbidden_state)


def test_real_policy_engine_can_classify_the_same_retry_input_without_receipt_state():
    policy = PolicyEngine.default()

    first = policy.evaluate_membrane(
        s_score=1.0,
        ds_de=0.0,
        d2s_de2=0.0,
        option_space=1.0,
        projected_events_to_zero=None,
        operating_mode="ENFORCE",
    )
    retry = policy.evaluate_membrane(
        s_score=1.0,
        ds_de=0.0,
        d2s_de2=0.0,
        option_space=1.0,
        projected_events_to_zero=None,
        operating_mode="ENFORCE",
    )

    assert first == retry

    # This is the empirical finding, not a conformance pass:
    # the current public policy subject has no input through which
    # "receipt unavailable / reconciliation pending" can affect the result.
    assert first[0] == "allow"
