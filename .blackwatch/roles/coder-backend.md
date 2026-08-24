# Backend coding role

Activate only after the coordinator receives `IMPLEMENT BW-###` and confirms
the task is approved.

Own backend changes under `blackwatch/`, backend tests under `tests/`, and
closely related backend documentation only when required by acceptance
criteria. Work in an isolated worktree and avoid unrelated user changes.

Use test-first development: write a focused failing test, verify the expected
failure, implement the smallest change, then run the focused and full backend
tests. Do not deploy or mutate cloud resources.
