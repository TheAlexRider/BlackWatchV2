# BW-004 Notification Studio Implementation Plan

## Goal

Build a cross-module, beginner-friendly Notification Studio. Operators choose a
module and plain-language alert type, configure routing and frequency, edit
guided message fields, preview/test the result, and save without learning rule
syntax or Jinja.

## Design

- Keep the existing channel, worker, retry, rate-limit, digest, ack, and log
  pipeline.
- Add a canonical catalog of supported modules and alert kinds.
- Store profiles in a dedicated table and compile each saved profile into an
  existing `notification_rules` row for dispatch compatibility.
- Use structured message fields for normal editing; allow an explicit advanced
  template override for expert users.
- Fall back to current rule/channel rendering when no profile exists.

## Tasks

1. Add pure catalog/profile compilation tests first and verify the expected red
   state.
2. Add the canonical catalog, profile normalization, structured-to-template
   compilation, and preview helpers.
3. Add the profile migration, storage functions, and compiled-rule dispatch
   integration, including profile digest settings.
4. Add authenticated API endpoints for catalog/list/save/delete/preview/test.
5. Add the Notification Studio list/editor UI and link it from Notifications.
6. Run focused tests, syntax checks, UI typecheck, contract validation, and
   the production build where the environment permits.
