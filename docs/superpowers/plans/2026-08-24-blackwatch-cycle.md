# BlackWatch Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repo-native, gated multi-agent workflow for BlackWatch where `BLACKWATCH CYCLE` runs research and QA analysis while coding remains explicitly approved.

**Architecture:** `AGENTS.md` defines the trigger, safety boundary, and coordinator contract. Role prompts under `.blackwatch/roles/` define read-only research/QA behavior and separate coding responsibilities. Reports, proposed tasks, approvals, and cycle state are persisted under `.blackwatch/`; no application source is changed by the autonomous analysis phase.

**Tech Stack:** Markdown instructions, YAML task/state artifacts, pytest contract validation, existing Graphify project context.

**Spec:** Approved conversational design from the preceding task.

## Global Constraints

- `BLACKWATCH CYCLE` may start R&D and QA only.
- R&D and QA may write only reports, task proposals, and cycle state.
- Coding requires an explicit `IMPLEMENT BW-###` instruction.
- No agent may deploy, mutate AWS resources, send production notifications, or alter production data as part of the cycle.
- Preserve unrelated user changes already present in the worktree.

---

### Task 1: Add the project-level coordinator contract

**Files:**
- Create: `AGENTS.md`
- Create: `.blackwatch/README.md`

**Steps:**
- [ ] Define the exact `BLACKWATCH CYCLE` trigger.
- [ ] Define the read-only boundary for R&D and QA.
- [ ] Define the `IMPLEMENT BW-###` approval gate.
- [ ] Document the Graphify preflight and current BlackWatch validation commands.

**Verification:** Read the instructions and confirm every autonomous action has an allowed output location.

### Task 2: Add role prompts and durable artifact templates

**Files:**
- Create: `.blackwatch/roles/coordinator.md`
- Create: `.blackwatch/roles/research.md`
- Create: `.blackwatch/roles/qa.md`
- Create: `.blackwatch/roles/coder-backend.md`
- Create: `.blackwatch/roles/coder-ui.md`
- Create: `.blackwatch/roles/coder-infrastructure.md`
- Create: `.blackwatch/roles/coder-tests.md`
- Create: `.blackwatch/templates/task.yaml`
- Create: `.blackwatch/templates/cycle.json`
- Create: `.blackwatch/reports/.gitkeep`
- Create: `.blackwatch/tasks/.gitkeep`

**Steps:**
- [ ] Give R&D and QA explicit scopes and write restrictions.
- [ ] Give coding agents explicit activation and worktree rules.
- [ ] Define the task schema shared between research, QA, coordinator, and coding agents.
- [ ] Define the cycle-state schema and report locations.

**Verification:** Validate that role prompts agree on the same task id, status, and approval vocabulary.

### Task 3: Add an automated contract check

**Files:**
- Create: `scripts/validate_blackwatch_cycle.py`
- Create: `tests/test_blackwatch_cycle_contract.py`

**Steps:**
- [ ] Write tests that require the trigger, approval gate, role files, and task template.
- [ ] Run the tests and observe the expected failure before implementation.
- [ ] Implement the validator with standard-library-only checks.
- [ ] Run the focused tests and the existing Python test suite.

**Verification:** `pytest -q tests/test_blackwatch_cycle_contract.py` and `python scripts/validate_blackwatch_cycle.py` both exit successfully.

### Task 4: Review and hand off

**Files:**
- Modify: `.gitignore` only if runtime state needs exclusion.

**Steps:**
- [ ] Confirm no application source files were changed.
- [ ] Confirm the existing dirty files remain untouched.
- [ ] Run the focused validator, Python tests, and UI typecheck if dependencies are available.
- [ ] Report the exact trigger and activation gate.
