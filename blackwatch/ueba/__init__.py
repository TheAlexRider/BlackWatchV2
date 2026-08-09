"""UEBA-lite baseline / first-seen anomaly module.

Maintains per-principal rolling baselines of a small fixed set of dimensions
in a separate SQLite file (baseline.db). After a per-principal warm-up window,
any never-before-seen value for a dimension fires a synthetic
`<category>.anomaly.first_seen_<dimension>` event.
"""

from . import check, config, db  # noqa: F401
