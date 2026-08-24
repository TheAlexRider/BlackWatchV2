# BlackWatch Cycle

This directory is the durable hand-off area for the BlackWatch agent team.

## Lifecycle

```text
BLACKWATCH CYCLE
  -> coordinator
  -> research + QA in parallel
  -> reports and proposed BW tasks
  -> explicit user approval
IMPLEMENT BW-###
  -> one gated coding role in an isolated worktree
  -> tests and review
```

## Task statuses

- `proposed` — discovered by research or QA; no coding is allowed.
- `approved` — explicitly approved by the user; eligible for implementation.
- `in_progress` — a coding role has started in an isolated worktree.
- `review` — implementation is complete and awaiting verification/review.
- `done` — acceptance criteria and verification are complete.
- `blocked` — progress requires a decision, dependency, or external change.

## BlackWatch-specific checks

Backend baseline:

```text
pytest -q
```

UI baseline:

```text
cd blackwatch-ui
npm run typecheck
npm run build
```

The coordinator should inspect `blackwatch/`, `blackwatch-ui/`, `tests/`,
`rules/`, `scripts/`, `deploy/`, `docs/`, and `future_modules.md`.

## Safety

Reports and task proposals are safe autonomous outputs. Application changes,
cloud changes, deployment, merging, and notification delivery require a
separate explicit instruction.
