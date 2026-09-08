# Engineering lessons

These fixes are based on observed regressions:

- Taxi routing now requires overtime context before checking the pre-approval
  rule; ordinary travel taxi lines use the transport cap.
- Hotel limits compare total claim amount with `cap * nights`, avoiding a
  floor-division miss for fractional overages.
- SQLite storage `id` is mapped to the public task contract field `jobId`.
- JSON status and artifact writes use file locks and atomic replacement.
- LLM, OCR, and individual claim failures are recorded and downgraded instead
  of aborting a whole batch.
- Windows Docker bind mounts exposed intermittent SQLite WAL open errors. This
  remains a deployment limitation and must stay visible in public docs.

Each item should keep a focused regression test and an evidence link in release
notes when its implementation changes.
