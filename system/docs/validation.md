# Validation

- **Where it runs:** on the control plane, independently of the worker that produced the result.
- **Order:** output schema, then the tool's `validate(out, artifacts)`, then a Receipt with `validation_ok`/`validation_problems` and an audit entry.
- **Outcome:** only `succeeded` jobs trigger `on_accept` side effects.
- **Test that a lying worker gets no credit:** `tests/test_control_plane.py::test_lying_worker_marked_invalid`.
- **Run the suite:** `python -m pytest -q`. Current result: 27 passed.
