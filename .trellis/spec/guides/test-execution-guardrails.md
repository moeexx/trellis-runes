# Test Execution Guardrails

## Evidence Discipline

- Run only the commands declared by the test plan, or record why a replacement is necessary.
- A skipped, unavailable, or failed command is evidence, not a pass. Report its reason, affected ACs, and next action.
- Keep command output or a stable summary sufficient for another developer to reproduce the conclusion.
- Execute layers in order: unit, then API/integration, then E2E. A failed lower layer blocks higher layers.

## Repair Loop Circuit Breaker

- After a failed verification, state the hypothesis before making the next repair.
- Do not repeat the same repair/test cycle three times in one phase without new evidence.
- On the third failed cycle, record a rollback, request human intervention, and preserve the failed evidence instead of continuing speculative edits.
- Resume only after the intervention identifies a changed assumption, environment condition, or implementation approach.

## Report Minimum

Every review or test report names scope, commands, outcomes, P0/P1/P2 findings, fixes or blockers, and reproducible evidence. Write `none` for an empty severity; never omit it silently.
