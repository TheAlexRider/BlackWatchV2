-- Allow operators to override a rule's severity from the UI in addition to
-- its enabled flag. Null severity means "use whatever the YAML says" —
-- the override only sticks when the operator explicitly picks a value.
ALTER TABLE rule_overrides
    ADD COLUMN IF NOT EXISTS severity TEXT;
