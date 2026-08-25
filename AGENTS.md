# BlackWatch agent workflow

This file is the project-level operating contract for Codex and other agentic
workers. `CLAUDE.md` contains the existing Graphify-specific guidance; these
rules add the BlackWatch coordination and safety boundary.

## Non-negotiable data-safety priority

Data preservation is the first priority. Existing Postgres data, tables,
columns, rows, configuration, audit history, and collected security evidence
must never be removed as a side effect of a build, rebuild, migration, agent
run, or feature change.

All agents and developers must:

- preserve the `bw_pgdata` Compose volume and never use `docker compose down -v`;
- treat migration SQL as additive and data-preserving; automatic `DROP TABLE`,
  `DROP COLUMN`, `TRUNCATE`, `DELETE FROM`, `DROP SCHEMA`, and `DROP DATABASE`
  operations are prohibited;
- stop and request an explicit operator decision if a change appears to need
  destructive data handling; never work around the safety check;
- keep deployment, migration, backup, and volume changes separate from normal
  application builds;
- verify the existing database and volume before changing Compose storage or
  migration behavior.

The database migration runner fails closed when it detects a prohibited
destructive statement. A successful image build is not evidence that data is
safe; storage and migration verification are required before claiming a
deployment is complete.

## Trigger: `BLACKWATCH CYCLE`

When the user says `BLACKWATCH CYCLE`, start one analysis cycle:

1. Read `.blackwatch/roles/coordinator.md`, the current cycle state, and the
   existing Graphify context.
2. Check the current Git status and preserve unrelated user changes.
3. Start the Research & Development and QA roles in parallel.
4. Reconcile their reports into durable, evidence-backed proposed tasks under
   `.blackwatch/tasks/`.
5. Write the cycle metadata and task IDs to `.blackwatch/state/cycle.json`.
6. Start the dedicated Graphify role as the final step. It refreshes the
   repository graph after all R&D, QA, and task-reconciliation work is done.
7. Record the Graphify result in cycle state, then summarize findings, risks,
   Graphify status, and task IDs for the user.

The cycle must not start a coding role.

## Autonomous analysis boundary

During `BLACKWATCH CYCLE`, Research & Development and QA may:

- read project files and documentation;
- inspect Git history and the Graphify output;
- run safe local tests, typechecks, builds, and static diagnostics;
- write only reports, proposed task files, and cycle state under `.blackwatch/`;
- produce reports, proposed task files, and cycle-state updates only.

The dedicated Graphify role may:

- read the repository and existing Graphify output;
- run the required Graphify refresh after R&D, QA, and task reconciliation;
- write only generated Graphify output and its refresh result to the approved
  Graphify/cycle-state locations;
- report a blocked refresh without modifying application code or inventing
  findings.

Graphify is deliberately the last analysis role in every cycle. R&D and QA
must use the previous graph as context; they must not refresh it early.

They must not:

- modify application source, tests, rules, deployment files, or documentation;
- create commits, branches, pull requests, or worktrees;
- deploy or mutate AWS/cloud resources;
- send production notifications or change production data;
- expose secrets, tokens, credentials, or `.env` contents.

Existing user changes in the worktree belong to the user. Do not reset,
overwrite, or reformat unrelated files.

## Coding gate

Coding roles may start only after the user explicitly says:

```text
IMPLEMENT BW-###
```

where `BW-###` is an existing task with `status: approved` or a task the user
has just explicitly approved. Before coding, the coordinator must:

1. confirm the task ID and acceptance criteria;
2. identify the smallest non-overlapping coding role;
3. use an isolated worktree when available;
4. require tests before implementation and verification after implementation;
5. keep deployment and merge as separate, explicit user decisions.

Every newly discovered task must start with `implementation_allowed: false`.

`BLACKWATCH CYCLE` never implies implementation approval.

## Shared artifacts

- `.blackwatch/reports/research.md` — R&D findings and opportunities.
- `.blackwatch/reports/qa.md` — QA findings and verification evidence.
- `.blackwatch/tasks/BW-###.yaml` — canonical proposed or approved work items.
- `.blackwatch/state/cycle.json` — current cycle metadata and role status.
- `.blackwatch/roles/` — role-specific operating prompts.
- `.blackwatch/templates/` — schemas for new artifacts.

Use the vocabulary in `.blackwatch/README.md` and the task template. Agents
communicate through these artifacts rather than relying on hidden conversation
state.
