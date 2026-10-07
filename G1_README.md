# S1 G1 Harness — TENIR / REG Conformance Companion

This artifact implements the first **executable** harness for  
**S1 — Evidence Lost After Commit**.

## Epistemic status (read carefully)

| Claim | Status |
|-------|--------|
| G0 operational definition exists | Yes (candidate) |
| G1 harness executes and passes G0 assertions | Yes |
| Harness validates a real REG / TENIR kernel | **No** |
| S1 is empirically validated against production code | **No** |

Passing the tests in this package only proves that **this harness** satisfies the G0 assertions.  
It does **not** validate REG, TENIR, or any distributed system.

To obtain genuine empirical evidence the harness must be turned into an **adapter** that drives the real subject under test.

## Scope of G1

- Deterministic fake clock  
- Effect sink  
- Permit state + permit log  
- Fault injector for S1a / S1b / S1c  
- Append-only JSONL transition log  
- Minimal T1 permit guard  
- Client-visible `HOLD` disposition  
- Pytest assertions matching G0  

## Run

```bash
python -m pytest tests/test_s1.py -v
python tools/run_s1.py
```

Evidence is written under `artifacts/s1/<run-id>/`.
