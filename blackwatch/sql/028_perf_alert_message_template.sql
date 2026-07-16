-- Per-rule custom message template for performance alerts. When set,
-- replaces the auto-generated "CPU load > 80% for 15m (current: 92%)"
-- string in extra.message before dispatch, so operators can craft the
-- text that lands in Slack/email/PagerDuty.
--
-- Rendered with Jinja over the event's extra dict (instance_id, hostname,
-- metric, metric_label, threshold, current_value, window_seconds, tags,
-- rule_name). If render errors or template is NULL/blank, we fall back
-- to the auto-generated line.

ALTER TABLE perf_alert_rules ADD COLUMN IF NOT EXISTS message_template TEXT;
