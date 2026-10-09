# E1 / E2 — Baseline comparison and bounded exploration

These scripts are the empirical material for §6 and §8 of the manuscript
*Governing the Unobserved* (v6.7).

**E1 — Fault-sequence comparison.** Exhaustive enumeration of 53 fault
sequences over a single logical operation, comparing a stateless PEP/PDP
baseline (B1), an idempotency-key baseline (B2), the membrane without
reconciliation (M0) and the membrane with evidence-bound reconciliation
(M1). Script: `e1_baseline.py`. Raw output: `e1_results.txt`.

**E2 — Bounded exhaustive exploration.** Explicit-state search over the
public API of the lab membrane, under four assumption regimes (honest,
false_attest, hidden_honest, adversarial). Script: `e2_explore.py`.
Raw results: `r6_*.json` and `r8_*.json` (depth is encoded in the filename).

E1 is run by the dedicated GitHub Actions workflow `.github/workflows/e1-baseline.yml`,
separate from the membrane conformance CI. E2 remains outside the conformance CI.
The raw outputs are retained here so the manuscript's results are inspectable and
re-runnable. To rerun them locally:

    python e1_baseline.py
    python e2_explore.py --depth 8 --world honest --out r8_honest.json

Requires the `tenir_conformance` package (this repository) on `PYTHONPATH`.

**E1 safety/liveness metrics.** The script reports both total blocked retry attempts and
the number of sequences containing at least one block; these are distinct measures.
It also computes two trace-conditioned rates from the same fixed 53-sequence set:
15 traces contain only F1/F3/F4 outcomes (no effect expected), and 38 contain at
least one effect-producing F0/F2 outcome (effect expected). A correct no-effect
case requires zero final effects **and positive operation-level evidence of
non-execution**; UNKNOWN or HOLD alone does not qualify. A correct single-effect
case requires exactly one final effect and client-confirmed success. Rates are
model-specific and do not estimate production probabilities.
