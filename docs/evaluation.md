# Evaluation

Evaluation is code, not a claim copied from a design document. Run from the
repository root with the project Python environment:

```bash
python -m pytest
python tools/eval_retrieval.py --mode both
python tools/eval_hard_set.py --gate
python tools/eval_injection.py
python tools/prompt_regression.py
```

The public sample labels are a small regression set, not a production accuracy
estimate. The difficult set covers boundary values, special approvals,
duplicate invoices, prompt injection, and routing cases.

The latest local retrieval run recorded keyword Recall@8 = 0.78 and hybrid
Recall@8 = 1.00 on 50 labeled cases. Latency depends on CPU, model cache state,
and runtime configuration; the latest local run was approximately 1 second per
query. Publish latency only with machine, cache, sample count, and command.

Business-scale figures belong to the private ERP acceptance report unless the
corresponding data and authorization are included in the public release.
