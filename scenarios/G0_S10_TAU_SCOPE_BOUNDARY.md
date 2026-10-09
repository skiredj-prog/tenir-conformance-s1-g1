# G0 S10 — TAU scope boundary

## Contract

`TAUContract` loads a versioned manifest, validates its required governance fields, recomputes SHA-256 over canonical JSON of the unsigned core, and verifies the Ed25519 signature over `{manifest, sha256}`. A signature authenticates the manifest bytes and signer under the configured public key; it does not establish that the declared policy is appropriate.

Scope membership is exact. The only wildcard behavior is an explicit `"*"` entry in a signed scope list. Case folding and prefix matching are forbidden.

`process_transaction` calls `scope_check` before attempt registration and before `KernelBridge.evaluate`. A rejected scope returns HOLD / `NOT_EVALUATED`, with no kernel call and no effect.

The bundled `tau.yaml` and public key are public conformance-test fixtures only. Its wildcard scope keeps prior membrane scenarios runnable; it is not a production TAU policy. Deployments must replace it with a least-privilege manifest signed by their own trust root.

## Oracle

- S10a: LEI outside scope is rejected before kernel.
- S10b: action class outside scope is rejected before kernel.
- S10c: principal outside scope is rejected before kernel.
- S10d: in-scope admission reaches kernel exactly once.
- S10e: case variant is rejected (no case folding).
- S10f: prefix is rejected (no prefix matching).
- S10g: same payload under two different TAU scopes yields divergent verdicts.
- TAU-001: startup with no manifest fails closed.
- TAU-002: manifest modification after signing is rejected.

S11 is explicitly out of scope for this change.
