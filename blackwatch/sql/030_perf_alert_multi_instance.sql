-- Multi-instance scope for perf alert rules.
--
-- Before: exactly one of (instance_id, tag_key+tag_value) — one host or a
-- tag-matched fleet.
--
-- After: also supports a list of specific instances (instance_ids) OR an
-- "all instances" scope (all three columns NULL).
--
-- Precedence in the evaluator (perf_alerts.py::_rule_targets_instance):
--   1. instance_ids non-empty → match if instance_id ∈ list
--   2. instance_id set        → exact match (legacy single-instance)
--   3. tag_key + tag_value    → tag match
--   4. everything NULL        → matches every host (all-scope)

ALTER TABLE perf_alert_rules
    ADD COLUMN IF NOT EXISTS instance_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
