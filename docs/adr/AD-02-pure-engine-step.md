# AD-02: The engine is a pure function with an incremental step()

- **Status:** Accepted (Software Design Document v1.0, client-approved 5 Nov 2026)
- **Source:** Software Design Document, architecture decisions table; PROJECT_HANDOFF.md section 3

## Context

Live scanning, custom settings and (Release 2) replay must give identical results; repainting is unacceptable.

## Decision

`tradelens_engine` has no I/O, clock or randomness. `run()` is defined as repeated `step()`. Purity is enforced by tests (`test_purity.py`) and the `engine-purity` import contract.
