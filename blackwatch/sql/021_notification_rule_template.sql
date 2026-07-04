-- Per-rule message template. When set, dispatch renders THIS Jinja source
-- for the outgoing message instead of the channel's default template. Lets
-- the same channel deliver differently-worded alerts depending on which
-- rule matched — e.g. a terse "🚨 CRITICAL" line for the critical rule and
-- a friendlier "FYI:" line for the medium rule, both routed to #ops-slack.
--
-- Null / empty = use the channel's default template (existing behavior).
ALTER TABLE notification_rules
    ADD COLUMN IF NOT EXISTS message_template TEXT;
