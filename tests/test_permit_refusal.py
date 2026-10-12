"""A5 — permit unusability: a consumed permit cannot be used or consumed again.

The refusal path is asserted explicitly, not only the flags. The membrane raises
PERMIT_ALREADY_CONSUMED on a second consumption and exposes is_execution_permit_usable.
"""

import pytest

from test_non_execution_attested_conformance import ATTEMPT, LEI, NONCE, PAYLOAD, _membrane


def test_consumed_permit_is_unusable_and_cannot_be_consumed_again():
    m = _membrane()
    result = m.process_transaction(lei=LEI, attempt_id=ATTEMPT, payload=PAYLOAD, nonce=NONCE)
    assert result.disposition.value == "PASS"
    assert m.permits[ATTEMPT].consumed is True
    assert m.is_execution_permit_usable(ATTEMPT) is False
    with pytest.raises(ValueError, match="PERMIT_ALREADY_CONSUMED"):
        m._consume_permit(m.attempts[ATTEMPT])
    # Rationale: after a consumption, 'consumed' is the state the refusal must leave behind.
    # 'revoked' is a different state (set by conflict or quarantine). Asserting it stays False
    # shows that the refusal is not mistaken for, or converted into, a revocation.
    assert m.permits[ATTEMPT].consumed is True
    assert m.permits[ATTEMPT].revoked is False
