# Scientific status of this package

## What this package establishes

1. G0 for S1 is written as an explicit, reviewable operational definition.
2. A G1 harness exists that realises those assertions.
3. Six pytest tests pass against the harness.
4. Evidence artifacts (JSONL, snapshots, scenario hash) are produced deterministically.

## What this package does **not** establish

- That REG / TENIR / any real PolicyEngine behaves this way.
- That a production gateway would return HOLD under S1a/S1b/S1c.
- That S1 is “CONFORMING” for the protocol.

The harness currently hard-codes the expected client projection.  
It is a useful executable specification, not a test of an independent subject.

## Required next step for genuine empirical evidence

1. Extract this package into the real workspace.
2. Replace `S1Gateway` internals with an adapter that calls the real kernel.
3. Re-run the same G0 assertions against that kernel.
4. Only then may a result be labelled “S1 empirical outcome against subject X”.

Until step 3–4 are done, the correct public statement is:

> “G1 harness executes G0 assertions for S1.  
> S1 has not yet been validated against a real REG/TENIR kernel.”
