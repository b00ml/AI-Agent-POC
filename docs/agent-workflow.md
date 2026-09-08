# Agent workflow contract

The M2 graph is a controlled workflow because its input schema, policy checks,
and output states are known in advance. The Agent portion is used for bounded
investigation of disagreement or `FLAG` cases, not unrestricted approval.

```text
rule review -> optional LLM second opinion -> bounded read-only investigation
            -> conservative adjudication -> human gate -> human-authorized write-back
```

The implementation enforces step and token budgets, request timeouts/retries,
grounding checks for evidence references, and failure downgrade to human
review. Tool definitions are in `core/agent_tools.py`; graph orchestration is
in `core/workflow.py`; checkpoint persistence is in `core/checkpoints.py` and
`core/workflow_store.py`.

This is intentionally not an autonomous-agent claim. External tools are
read-only, evidence must point back to returned tool data, and no model output
can authorize automatic release.
