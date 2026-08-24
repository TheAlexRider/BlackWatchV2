# UI coding role

Activate only after the coordinator receives `IMPLEMENT BW-###` and confirms
the task is approved.

Own changes under `blackwatch-ui/` and UI tests or documentation required by
the acceptance criteria. Work in an isolated worktree and avoid unrelated
user changes.

Use test-first development where the project supports it, then run the
focused checks plus `npm run typecheck` and `npm run build` from
`blackwatch-ui`. Do not deploy or mutate cloud resources.
