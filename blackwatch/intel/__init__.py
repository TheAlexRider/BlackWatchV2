"""Threat-intel enrichment: local IP -> country / ASN / feed-tag lookup.

Feeds and MMDBs live in a separate SQLite/file store so the hot events db is
never touched by refreshes. See docs/threat-intel.md for the runbook."""

from .enrich import enrich_event

__all__ = ["enrich_event"]
