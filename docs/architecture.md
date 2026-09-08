# Architecture

## Runtime boundaries

```text
Vue 3 -> FastAPI -> application services/job queue -> core audit engines
                                             |-> ERP adapter
                                             |-> local OCR / retrieval / optional LLM
```

M2 evaluates expense claims with deterministic rules, optional OCR fields,
optional LLM review, and a human review boundary. M3 audits an invoice ledger
for duplicates and invoice anomalies. M4 reconciles bank CSV input with open
receivables.

The rule engine is the deterministic baseline and evaluates every selected
claim. The LLM is a second opinion, not an authority. Disagreement moves the
result to `FLAG`; it cannot turn a rule violation into automatic approval.
Investigation tools are read-only. `adjudicate` can only move toward human
attention. The final state-changing operation is a human review submitted
through the ERP adapter.

Batch jobs, audit status, and workflow artifacts are persisted under `output/`
during self-hosted runs. File locks and atomic replacement protect JSON state;
workflow checkpoints support resuming an interrupted human gate. A failed
claim is recorded in the failure report and does not abort the whole batch.

The public release must provide a local demo adapter backed by synthetic
fixtures. The ERP adapter remains an optional self-hosted integration.

This is not a production deployment architecture: identity-aware authorization,
tenant isolation, HA job execution, managed secret storage, a durable message
broker, and formal database migrations are outside this learning POC.
