# Experiments

This directory separates **executable specification** from **empirical subject tests**.

- `harness/`-level tests exercise the S1 model itself.
- `real_tenir/` tests call the published `tenir_governance` package.
- A passing harness test is not evidence about TENIR.
- A real-subject experiment may legitimately return **NOT_CONFORMING / NOT_IMPLEMENTED**.

For S1, the decisive question is whether loss of execution evidence prevents a new execution for the same logical execution identity (LEI) while reconciliation is unresolved.

The current TENIR PolicyEngine exposes membrane classification, but does not expose an execution-attempt/receipt reconciliation gate. The real-subject experiment therefore records that boundary explicitly rather than simulating it.
