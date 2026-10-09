# G0 S7 — Forged Non-Execution Attestation

## Claim
A non-execution attestation may move an attempt to `FAILED` and release the LEI lock only when its Ed25519 signature verifies against the versioned trust root and the signed payload binds the exact attempt ID, LEI, nonce, and non-execution claim. Rejected attestations are retained as audit evidence marked `unverified`; they do not mutate attempt state or permits.

## Initial state
- `permit(L, A1)` is consumed.
- Attempt `A1` is `UNKNOWN`.
- Attempt `A2` has not been admitted.
- Trust root `TENIR-LAB-S7-TEST-ROOT`, epoch 1, declares `K1` as Ed25519.
- The repository trust root and private signing vector are test fixtures only.

## Sub-cases
- **S7a — Unsigned:** missing signature → `SIGNATURE_INVALID`, reason `missing_signature`.
- **S7b — Unknown key:** `key_id=K9` → `SIGNATURE_INVALID`, reason `unknown_key`.
- **S7c — Revoked key:** trust root epoch 2 revokes K1 at epoch 2; an attestation carrying key epoch 1 is rejected with reason `revoked_key`.
- **S7d — Content tampering:** a signed payload is altered after signing → `SIGNATURE_INVALID`, reason `content_mismatch`.
- **S7e — Nominal control:** exact signed payload from active K1 verifies; A1 becomes `FAILED`, and A2 may be admitted.
- **S7f — Cross-LEI replay:** a valid signed claim for LEI M presented against LEI L is rejected with `BINDING_LEI_MISMATCH`.

## Required assertions
For every rejection: A1 remains `UNKNOWN`; the LEI stays locked; A2 remains unadmitted; the rejection event includes the attestation ID and reason; no permit is issued, consumed, or replayed by the rejection path; and the attempted attestation is appended to the evidence registry as `unverified`.

For S7e: signature and binding are verified before state mutation; A1 becomes `FAILED` with non-execution established; the LEI lock releases; A2 can be admitted via the normal path.

## Evidence
Each sub-case emits a JSONL transition bundle and structured JSON snapshots containing the signed payload, signature, versioned trust-root snapshot, verification trace, attempt state before/after, permit registry before/after, evidence-registry entry, and SHA-256 of this scenario definition.

## Threat-model boundary
S7 detects unsigned, unknown-key, revoked-key, tampered-content, and cross-LEI replay cases. It does not establish the truthfulness of a validly signed attestation, protect a compromised signing key, protect an administratively replaced trust root, address invalid-attestation denial of service, provide threshold signatures, or claim post-quantum security.
