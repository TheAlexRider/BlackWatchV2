"""File Integrity Monitoring (FIM) engine for the BlackWatch EC2 agent.

Two detection paths share one local SQLite baseline:

  * **periodic** (Part 1) — every COLLECT_FIM_SEC (6h default), walks a
    configured set of files/directories, computes sha256 + reads metadata,
    diffs against the baseline. Catches drift the inotify watcher missed
    (e.g. files in binary dirs, files modified while agent was down).

  * **inotify** (Part 2) — a separate thread watches a subset of critical
    paths (critical_files + critical_dirs, NOT binary dirs — too many
    files for the kernel watch limit). Sub-second detection. Editor saves
    are debounced over 200ms so vim's swap-file dance produces one event.

  * **auditd** (Part 3 — TODO) — will join a "who-did-it" actor from
    /var/log/audit/audit.log by path + 2-second time window.

All three share the same baseline. Mutations are per-path atomic under a
single RLock so the periodic walk can't blow away an inotify-just-updated
row, and vice versa.

Resource shape: ~30 MB RAM steady, one CPU spike per scan (5-30s for ~500
files), tiny disk (<1 MB baseline.db), low-frequency syscalls from the
inotify thread (~zero when nothing changes).
"""
from __future__ import annotations

import binascii
import hashlib
import os
import re
import sqlite3
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

# --- defaults ----------------------------------------------------------------

_DEFAULT_CRITICAL_FILES: list[str] = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/gshadow",
    "/etc/sudoers",
    "/etc/login.defs",
    "/etc/ssh/sshd_config",
    "/etc/hosts",
    "/etc/hosts.allow",
    "/etc/hosts.deny",
    "/etc/resolv.conf",
    "/etc/crontab",
    "/etc/nsswitch.conf",
    "/etc/pam.conf",
    "/etc/profile",
    "/etc/bashrc",
    "/etc/environment",
]

_DEFAULT_CRITICAL_DIRS: list[str] = [
    "/etc/ssh/sshd_config.d",
    "/etc/sudoers.d",
    "/etc/pam.d",
    "/etc/security",
    "/etc/cron.d",
    "/etc/cron.hourly",
    "/etc/cron.daily",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
    "/etc/systemd/system",
    "/etc/profile.d",
    "/root/.ssh",
]

# Binaries — periodic-only. Too many files for inotify watches.
_DEFAULT_BINARY_DIRS: list[str] = [
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
]

_EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "/proc/", "/sys/", "/dev/", "/run/", "/var/run/",
    "/var/log/", "/var/cache/", "/var/tmp/", "/tmp/",
    "/var/lib/blackwatch-agent",
)

_MAX_HASH_BYTES = 50 * 1024 * 1024  # 50 MB per-file hash cap
_DEFAULT_BASELINE_DIR = "/var/lib/blackwatch-agent/fim"
_MAX_QUEUED_CHANGES = 1000
_INOTIFY_DEBOUNCE_SEC = 0.2  # editor saves usually fire 3-5 events within 50ms

# Default location of the Linux audit log. Read-only access required (root
# can always read it). If absent or unreadable, whodata is best-effort skipped
# without affecting any other FIM functionality.
_DEFAULT_AUDIT_LOG = "/var/log/audit/audit.log"

# How long after an audit record stays "fresh" for FIM-to-actor matching.
# 2s is the textbook window: longer = false attributions if a different
# process touched the same file; shorter = missed attributions because of
# inotify debounce + hashing latency.
_AUDIT_WINDOW_SEC = 2.0

# Cap the in-memory "recent audit writers" map so a flood of audit traffic
# can't OOM the agent. LRU-style: oldest entry evicted on insert past cap.
_AUDIT_RECENT_CAP = 4096


# --- types --------------------------------------------------------------------


class FimChange(dict):
    """Plain dict marker — what the engine emits and the agent ships. Shape:

      {
        "path": "/etc/sudoers",
        "change_type": "modified|created|deleted|perm_changed|owner_changed",
        "sha256_before": "...", "sha256_after": "...",
        "size_before": 1234,   "size_after": 1300,
        "perm_before": 384,    "perm_after": 420,
        "owner_before": "0:0", "owner_after": "0:0",
        "detected_at": "2026-06-26T15:30:00Z",
        "detection":   "baseline" | "inotify" | "auditd",
      }
    """


# --- engine -------------------------------------------------------------------


class FimEngine:
    """Owns the local baseline + scan thread + inotify thread."""

    def __init__(
        self,
        baseline_dir: str = _DEFAULT_BASELINE_DIR,
        scan_interval_sec: int = 21_600,   # 6 hours
        critical_files: Iterable[str] | None = None,
        critical_dirs: Iterable[str] | None = None,
        binary_dirs: Iterable[str] | None = None,
    ):
        self._baseline_dir = Path(baseline_dir)
        self._baseline_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._baseline_dir, 0o700)
        except OSError:
            pass
        self._db_path = self._baseline_dir / "baseline.db"
        self._scan_interval = max(60, int(scan_interval_sec))

        self.critical_files = list(critical_files) if critical_files else list(_DEFAULT_CRITICAL_FILES)
        self.critical_dirs  = list(critical_dirs)  if critical_dirs  else list(_DEFAULT_CRITICAL_DIRS)
        self.binary_dirs    = list(binary_dirs)    if binary_dirs    else list(_DEFAULT_BINARY_DIRS)

        self._pending: list[FimChange] = []
        self._pending_lock = threading.Lock()

        # One lock guards every baseline mutation. Both threads acquire it
        # for read-then-write of a single path. Held briefly per path so the
        # inotify thread isn't blocked for the duration of a 30s scan.
        self._baseline_lock = threading.RLock()

        # Coverage snapshot — updated at end of each scan, queried by the
        # main agent tick to ship on heartbeat.
        self._coverage = {
            "paths_configured": (
                len(self.critical_files)
                + len(self.critical_dirs)
                + len(self.binary_dirs)
            ),
            "files_tracked": 0,
            "last_full_scan_at": None,
            "last_scan_duration_ms": None,
            "scan_errors": 0,
            "paths_inotify": 0,
            "paths_baseline_only": 0,
            "inotify_active": False,
            "inotify_watch_count": 0,
            "auditd_active": False,
            "configured_paths": {
                "critical_files": list(self.critical_files),
                "critical_dirs":  list(self.critical_dirs),
                "binary_dirs":    list(self.binary_dirs),
            },
        }
        self._coverage_lock = threading.Lock()

        self._stopping = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self._inotify: InotifyWatcher | None = None
        self._audit: AuditReaderThread | None = None

        self._ensure_schema()

    # -------- public API ---------

    def start(self) -> None:
        """Spawn the scan thread + try to spawn the inotify watcher + try to
        spawn the auditd reader. All three threads are independent — failure
        of one doesn't disable the others. Idempotent."""
        if self._scan_thread is None or not self._scan_thread.is_alive():
            self._scan_thread = threading.Thread(
                target=self._scan_loop, name="bw-fim-scan", daemon=True
            )
            self._scan_thread.start()

        if self._inotify is None:
            inotify_paths = self._inotify_paths()
            self._inotify = InotifyWatcher(
                paths=inotify_paths,
                on_change=self._handle_realtime_change,
            )
            self._inotify.start()
            # Coverage reflects the announced intent, regardless of whether
            # inotify_simple is installed (so the UI can flag "wanted N, got 0").
            with self._coverage_lock:
                self._coverage["paths_inotify"] = len(inotify_paths)
                # Baseline-only = paths the scanner walks that inotify doesn't.
                self._coverage["paths_baseline_only"] = (
                    len(self.binary_dirs)  # binary dirs aren't inotify'd
                )

        # Part 3: try to start the audit reader. It's purely opportunistic —
        # absence of auditd is normal on many boxes; we silently fall back.
        if self._audit is None:
            self._audit = AuditReaderThread()
            self._audit.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._inotify is not None:
            self._inotify.stop()
        if self._audit is not None:
            self._audit.stop()

    def drain_changes(self) -> list[FimChange]:
        with self._pending_lock:
            out, self._pending = self._pending, []
        return out

    def coverage(self) -> dict:
        with self._coverage_lock:
            # Refresh real-time component liveness on every read so the UI
            # catches the case where one of these started, then crashed.
            if self._inotify is not None:
                self._coverage["inotify_active"] = self._inotify.is_active()
                self._coverage["inotify_watch_count"] = self._inotify.watch_count()
            if self._audit is not None:
                self._coverage["auditd_active"] = self._audit.is_active()
            return dict(self._coverage)

    # -------- inotify path selection ---------

    def _inotify_paths(self) -> list[str]:
        """Subset of paths to watch in real-time. We DON'T watch binary_dirs
        because thousands of files would exhaust the kernel watch budget on
        small instances; the periodic scanner covers those.

        We DO watch:
          * every critical_file (one watch per file)
          * every critical_dir (one watch per dir — fires for files inside)
          * for each critical_dir, one level of subdirs (so /etc/security/limits.d
            fires too without us walking deeply)
        """
        paths: set[str] = set()
        for p in self.critical_files:
            if _path_allowed(p) and os.path.exists(p):
                paths.add(p)
        for d in self.critical_dirs:
            if not _path_allowed(d):
                continue
            if os.path.isdir(d):
                paths.add(d)
                # One level of subdirs (e.g. /etc/systemd/system/multi-user.target.wants).
                try:
                    for entry in os.scandir(d):
                        if entry.is_dir(follow_symlinks=False) and _path_allowed(entry.path):
                            paths.add(entry.path)
                except OSError:
                    continue
        return sorted(paths)

    # -------- realtime handler (called by InotifyWatcher) ---------

    def _handle_realtime_change(self, path: str) -> None:
        """InotifyWatcher hands us a path with debounced events. We do the
        actual stat/hash/baseline-compare here, under the baseline lock so
        we don't race with the periodic scanner. After we have a change,
        consult the audit reader for actor info."""
        try:
            meta = _stat_and_hash(path)
        except FileNotFoundError:
            # File was deleted / moved away after the inotify event.
            with self._baseline_lock:
                prior = self._read_baseline_path(path)
                if prior is None:
                    return
                self._delete_baseline_path(path)
            change = _make_delete_change(path, prior, detection="inotify")
            self._attach_actor(change, path)
            self._queue_change(change)
            return
        except Exception as e:
            _log(f"inotify hash failed for {path}: {e!r}")
            return

        # File exists — compare to baseline, emit if changed, refresh baseline.
        with self._baseline_lock:
            prior = self._read_baseline_path(path)
            change = _diff_one(path, prior, meta, detection="inotify")
            self._upsert_baseline_path(path, meta)
        if change is not None:
            self._attach_actor(change, path)
            self._queue_change(change)

    def _attach_actor(self, change: FimChange, path: str) -> None:
        """If the audit reader has a recent writer record for this path
        within the 2-second window, embed it in the change. The reader's
        lookup is non-blocking; absence of an actor isn't an error."""
        if self._audit is None:
            return
        actor = self._audit.lookup(path)
        if actor is not None:
            change["actor"] = actor

    # -------- periodic scan loop ---------

    def _scan_loop(self) -> None:
        """First scan starts 15s after launch (lets agent finish startup);
        subsequent scans every scan_interval."""
        self._stopping.wait(15)
        while not self._stopping.is_set():
            try:
                self._do_scan()
            except Exception as e:
                with self._coverage_lock:
                    self._coverage["scan_errors"] += 1
                _log(f"fim scan failed: {e!r}")
            self._stopping.wait(self._scan_interval)

    def _do_scan(self) -> None:
        started = time.monotonic()
        scan_started_at = time.time()
        scan_errors = 0
        seen_paths: set[str] = set()
        truncated = False

        for path in self._iter_paths():
            seen_paths.add(path)
            try:
                change = self._scan_one_path(path)
            except Exception as e:
                scan_errors += 1
                _log(f"scan_one_path failed for {path}: {e!r}")
                continue
            if change is not None:
                if len(self._pending) < _MAX_QUEUED_CHANGES:
                    self._queue_change(change)
                else:
                    truncated = True

        # Detect deletes: any baseline path inside our scan scope that we
        # didn't walk this scan. Skip paths the inotify thread is also
        # tracking — if a watched file was deleted, the inotify handler
        # already emitted the delete and removed the baseline row.
        with self._baseline_lock:
            baseline_paths = self._all_baseline_paths()
            inotify_set = set(self._inotify_paths()) if self._inotify else set()
            for path in baseline_paths - seen_paths:
                if not self._is_in_scan_scope(path):
                    continue
                if path in inotify_set:
                    # Re-stat: if file still exists, was an inotify hiccup;
                    # otherwise inotify already deleted the row, but we lost
                    # a race — re-emit delete now.
                    if os.path.exists(path):
                        continue
                prior = self._read_baseline_path(path)
                if prior is None:
                    continue
                self._delete_baseline_path(path)
                change = _make_delete_change(path, prior, detection="baseline")
                if len(self._pending) < _MAX_QUEUED_CHANGES:
                    self._queue_change(change)
                else:
                    truncated = True

        if truncated:
            self._queue_change(_truncation_marker(_MAX_QUEUED_CHANGES))

        duration_ms = int((time.monotonic() - started) * 1000)
        files_tracked = self._count_baseline_paths()
        path_stats = self._compute_path_stats()
        with self._coverage_lock:
            self._coverage.update({
                "files_tracked": files_tracked,
                "last_full_scan_at": _now_iso(),
                "last_scan_duration_ms": duration_ms,
                "scan_errors": scan_errors,
                "path_stats": path_stats,
            })

    def _scan_one_path(self, path: str) -> FimChange | None:
        """Compute fresh hash, compare to baseline, upsert. All under the
        lock so inotify can't pull the rug out from under us mid-path.

        Periodic detections rarely benefit from auditd attribution (the
        2-second audit window will almost always have expired), but we
        look anyway for the edge case of a change that happens to land
        seconds before the scan reaches that path."""
        try:
            meta = _stat_and_hash(path)
        except OSError:
            return None
        with self._baseline_lock:
            prior = self._read_baseline_path(path)
            change = _diff_one(path, prior, meta, detection="baseline")
            self._upsert_baseline_path(path, meta)
        if change is not None:
            self._attach_actor(change, path)
        return change

    def _is_in_scan_scope(self, path: str) -> bool:
        if path in self.critical_files:
            return True
        for d in self.critical_dirs + self.binary_dirs:
            if path == d or path.startswith(d + "/"):
                return True
        return False

    # -------- path iteration (periodic walk) ---------

    def _iter_paths(self) -> Iterable[str]:
        for p in self.critical_files:
            if _path_allowed(p) and os.path.isfile(p):
                yield p
        for root in self.critical_dirs + self.binary_dirs:
            if not _path_allowed(root):
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                    if not _path_allowed(dirpath + "/"):
                        dirnames[:] = []
                        continue
                    for name in filenames:
                        p = os.path.join(dirpath, name)
                        if not _path_allowed(p):
                            continue
                        try:
                            if not os.path.isfile(p):
                                continue
                            if os.path.getsize(p) > _MAX_HASH_BYTES:
                                continue
                            yield p
                        except OSError:
                            continue
            except OSError:
                continue

    # -------- SQLite baseline (atomic per-path) ---------

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS baseline (
                    path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    perm INTEGER NOT NULL,
                    owner_uid INTEGER NOT NULL,
                    owner_gid INTEGER NOT NULL,
                    mtime REAL NOT NULL
                )
            """)
            conn.execute("PRAGMA journal_mode=WAL")
        try:
            os.chmod(self._db_path, 0o600)
        except OSError:
            pass

    def _read_baseline_path(self, path: str) -> dict | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT sha256, size, perm, owner_uid, owner_gid, mtime "
                "FROM baseline WHERE path = ?",
                (path,),
            ).fetchone()
        if not row:
            return None
        return {
            "sha256": row[0], "size": row[1], "perm": row[2],
            "owner_uid": row[3], "owner_gid": row[4], "mtime": row[5],
        }

    def _upsert_baseline_path(self, path: str, meta: dict) -> None:
        # INSERT OR REPLACE works on every SQLite version (vs. ON CONFLICT DO
        # UPDATE which needs 3.24+). Amazon Linux 2 ships an older SQLite
        # bundled with Python 3.7 — INSERT OR REPLACE is the compatible upsert.
        # Semantically identical for our case: PK is `path`, we always update
        # every column with the fresh values.
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO baseline "
                "(path, sha256, size, perm, owner_uid, owner_gid, mtime) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, meta["sha256"], meta["size"], meta["perm"],
                 meta["owner_uid"], meta["owner_gid"], meta["mtime"]),
            )

    def _delete_baseline_path(self, path: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM baseline WHERE path = ?", (path,))

    def _all_baseline_paths(self) -> set[str]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT path FROM baseline").fetchall()
        return {r[0] for r in rows}

    def _count_baseline_paths(self) -> int:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM baseline").fetchone()
        return int(row[0]) if row else 0

    def _compute_path_stats(self) -> dict:
        """For each configured path, how many files + total bytes the
        baseline currently has under it. The per-instance UI uses this so
        it can show "X files in /etc/sudoers.d" without the backend having
        to know the full baseline set. Single SQL pass per path — cheap.

        Returns: {path: {file_count: N, total_size_bytes: N, category: str}}
        """
        stats: dict[str, dict] = {}
        with sqlite3.connect(self._db_path) as conn:
            # Critical files: exact-match.
            for p in self.critical_files:
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size), 0) "
                    "FROM baseline WHERE path = ?",
                    (p,),
                ).fetchone()
                stats[p] = {
                    "file_count": int(row[0]),
                    "total_size_bytes": int(row[1]),
                    "category": "critical_files",
                }
            # Directories: exact-match OR prefix-match.
            for category, paths in (
                ("critical_dirs", self.critical_dirs),
                ("binary_dirs", self.binary_dirs),
            ):
                for p in paths:
                    pref = p.rstrip("/") + "/"
                    row = conn.execute(
                        "SELECT COUNT(*), COALESCE(SUM(size), 0) "
                        "FROM baseline WHERE path = ? OR path LIKE ?",
                        (p, pref + "%"),
                    ).fetchone()
                    stats[p] = {
                        "file_count": int(row[0]),
                        "total_size_bytes": int(row[1]),
                        "category": category,
                    }
        return stats

    # -------- queue helpers ---------

    def _queue_change(self, change: FimChange) -> None:
        with self._pending_lock:
            self._pending.append(change)


# --- inotify watcher ---------------------------------------------------------


class InotifyWatcher:
    """Real-time FIM via Linux inotify. Optional — degrades gracefully to
    'periodic only' if inotify_simple isn't installed.

    Behaviour:
      * one watch per path in `paths` (file or dir)
      * coalesces rapid events for the same path (200ms debounce — editor
        saves usually fire 3-5 events within 50ms; we want one logical
        change, not five)
      * doesn't recurse into subdirs automatically — caller decides what to
        watch (FimEngine watches critical_dirs and one level of their subdirs)
      * fires `on_change(path)` after the debounce window expires
      * the callback does the actual stat/hash/baseline-compare; this thread
        just buffers and times events
    """

    def __init__(self, paths: list[str], on_change: Callable[[str], None]):
        self._paths = list(paths)
        self._on_change = on_change
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._watch_count = 0

    def start(self) -> None:
        # Probe for inotify_simple here so a missing package degrades to
        # baseline-only with a single log line, not a crash.
        try:
            import inotify_simple  # noqa: F401
        except ImportError:
            _log("inotify_simple not installed; real-time FIM disabled "
                 "(pip install inotify_simple, then restart agent)")
            return
        self._thread = threading.Thread(
            target=self._loop, name="bw-fim-inotify", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()

    def is_active(self) -> bool:
        return self._active

    def watch_count(self) -> int:
        return self._watch_count

    def _loop(self) -> None:
        from inotify_simple import INotify, flags
        # MODIFY      content write
        # CREATE      new file appeared in a watched dir
        # DELETE      file removed from a watched dir
        # ATTRIB      perm/owner/xattr changed
        # MOVED_TO/FROM same as CREATE/DELETE but via rename
        # DELETE_SELF/MOVE_SELF the watched file itself disappeared
        WATCH_FLAGS = (
            flags.MODIFY | flags.CREATE | flags.DELETE | flags.ATTRIB
            | flags.MOVED_TO | flags.MOVED_FROM
            | flags.DELETE_SELF | flags.MOVE_SELF
        )
        try:
            with INotify() as inot:
                wd_to_path: dict[int, str] = {}
                for p in self._paths:
                    if not os.path.exists(p):
                        continue
                    try:
                        wd = inot.add_watch(p, WATCH_FLAGS)
                        wd_to_path[wd] = p
                        self._watch_count += 1
                    except OSError as e:
                        # Most common cause: hit fs.inotify.max_user_watches.
                        # Install script tries to bump this; if we still hit
                        # it, log loudly and continue with what we have.
                        _log(f"inotify add_watch failed for {p}: {e} "
                             f"(may have hit fs.inotify.max_user_watches)")

                if not wd_to_path:
                    _log("inotify started with zero watches; giving up")
                    return

                self._active = True
                _log(f"inotify active: {self._watch_count} watches")

                pending: dict[str, float] = {}   # path -> monotonic time of last event

                while not self._stopping.is_set():
                    try:
                        # Short read timeout so we can flush pending paths
                        # every 100ms even if nothing new arrives.
                        events = inot.read(timeout=100)
                    except Exception as e:
                        _log(f"inotify read failed: {e}")
                        time.sleep(1)
                        continue

                    now = time.monotonic()
                    for event in events:
                        root = wd_to_path.get(event.wd)
                        if root is None:
                            continue
                        # event.name is the entry name when event came from a
                        # dir watch; empty when from a file watch (use root).
                        full = os.path.join(root, event.name) if event.name else root
                        pending[full] = now

                    # Fire any path that's been quiet for at least DEBOUNCE.
                    cutoff = now - _INOTIFY_DEBOUNCE_SEC
                    ready = [p for p, t in pending.items() if t <= cutoff]
                    for p in ready:
                        del pending[p]
                        try:
                            self._on_change(p)
                        except Exception as e:
                            _log(f"inotify on_change failed for {p}: {e}")
        except Exception as e:
            _log(f"inotify watcher crashed: {e}")
        finally:
            self._active = False


# --- audit reader (whodata) --------------------------------------------------


_AUDIT_ID_RE = re.compile(r"msg=audit\(([0-9.]+):(\d+)\)")
_AUDIT_KEY_RE = re.compile(r'key="bw_fim"')
_AUDIT_NAME_RE = re.compile(r'\bname="([^"]*)"')
_AUDIT_NAME_HEX_RE = re.compile(r'\bname=([0-9A-F]+)\b')  # name= can be hex if special chars
_AUDIT_KV_QUOTED_RE = re.compile(r'\b(\w+)="([^"]*)"')
_AUDIT_KV_BARE_RE = re.compile(r'\b(\w+)=(\S+)')
_AUDIT_PROCTITLE_HEX_RE = re.compile(r'\bproctitle=([0-9A-F]+)\b')
_AUDIT_PROCTITLE_QUOTED_RE = re.compile(r'\bproctitle="([^"]*)"')

# Fields we want from the SYSCALL line.
_ACTOR_FIELDS = ("uid", "gid", "euid", "egid", "pid", "ppid", "comm", "exe", "tty")


class AuditReaderThread:
    """Tails /var/log/audit/audit.log, finds records tagged `key="bw_fim"`,
    and maintains a short-lived `path -> actor` map that the FIM engine
    consults when emitting changes.

    Audit log structure for one event (4 lines, same audit_id):

        type=SYSCALL  msg=audit(1782486231.594:12345): uid=1000 pid=22 comm="vim" exe="..." key="bw_fim"
        type=CWD      msg=audit(1782486231.594:12345): cwd="/root"
        type=PATH     msg=audit(1782486231.594:12345): item=0 name="/etc/sudoers" ...
        type=PROCTITLE msg=audit(1782486231.594:12345): proctitle="vim /etc/sudoers"

    We accumulate partial events keyed by audit_id and commit when we see
    PROCTITLE (usually the last record) or after a 5-second timeout.

    The audit log is rotated by logrotate; we detect inode change and
    re-open. We always tail from the END on first open (we don't need
    historical events) — a brief gap on agent restart is fine.

    Whodata is opportunistic. If auditd isn't running, audit.log is missing,
    or we can't read it, the thread logs once and exits cleanly — FIM still
    works, just without actor attribution.
    """

    def __init__(self, audit_log_path: str = _DEFAULT_AUDIT_LOG):
        self._log_path = audit_log_path
        # path -> (timestamp, actor_dict). LRU-trimmed in _add().
        self._recent: dict[str, tuple[float, dict]] = {}
        self._recent_lock = threading.Lock()
        # audit_id -> {actor: {...}, paths: [...], ts: epoch}
        self._partials: dict[str, dict] = {}
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._fh = None
        self._inode = -1

    def start(self) -> None:
        if not os.path.exists(self._log_path):
            _log(f"audit log not found at {self._log_path}; whodata disabled "
                 "(install / start auditd to enable)")
            return
        try:
            with open(self._log_path, "rb"):
                pass
        except PermissionError:
            _log(f"no read access to {self._log_path}; whodata disabled "
                 "(agent must run as root)")
            return
        self._thread = threading.Thread(
            target=self._loop, name="bw-fim-audit", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()

    def is_active(self) -> bool:
        return self._active

    def lookup(self, path: str) -> dict | None:
        """Return actor dict for the most recent writer of `path`, but only
        if it happened within _AUDIT_WINDOW_SEC. Non-blocking; safe from
        any thread."""
        with self._recent_lock:
            entry = self._recent.get(path)
            if entry is None:
                return None
            ts, actor = entry
            if time.time() - ts > _AUDIT_WINDOW_SEC:
                # Stale — drop and report miss. Cheap cleanup pass.
                self._recent.pop(path, None)
                return None
            return dict(actor)

    def _loop(self) -> None:
        try:
            self._open_at_end()
            self._active = True
            _log(f"auditd reader active on {self._log_path}")
            while not self._stopping.is_set():
                # Detect log rotation by inode change.
                try:
                    current_inode = os.stat(self._log_path).st_ino
                except FileNotFoundError:
                    time.sleep(1)
                    continue
                if current_inode != self._inode:
                    self._open_at_end()

                line = self._fh.readline() if self._fh else ""
                if not line:
                    self._sweep_stale_partials()
                    time.sleep(0.25)
                    continue
                try:
                    self._process_line(line.rstrip("\n"))
                except Exception as e:
                    # Never let a malformed line kill the reader.
                    _log(f"audit line parse failed: {e!r}")
        except Exception as e:
            _log(f"audit reader crashed: {e!r}")
        finally:
            self._active = False
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass

    def _open_at_end(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        try:
            self._fh = open(self._log_path, "r", encoding="utf-8", errors="replace")
            self._fh.seek(0, os.SEEK_END)
            self._inode = os.fstat(self._fh.fileno()).st_ino
        except OSError as e:
            _log(f"audit log open failed: {e!r}")
            self._fh = None
            self._inode = -1
            raise

    def _process_line(self, line: str) -> None:
        if "bw_fim" not in line and "PROCTITLE" not in line and "PATH" not in line:
            return
        m = _AUDIT_ID_RE.search(line)
        if not m:
            return
        audit_id = f"{m.group(1)}:{m.group(2)}"
        now = time.time()

        if line.startswith("type=SYSCALL") and _AUDIT_KEY_RE.search(line):
            actor = self._parse_syscall(line)
            if actor:
                self._partials[audit_id] = {
                    "actor": actor,
                    "paths": [],
                    "ts": now,
                }
        elif line.startswith("type=PATH"):
            partial = self._partials.get(audit_id)
            if partial is None:
                return
            path = self._parse_path(line)
            if path and self._is_meaningful_nametype(line):
                partial["paths"].append(path)
        elif line.startswith("type=PROCTITLE"):
            partial = self._partials.get(audit_id)
            if partial is None:
                return
            proctitle = self._parse_proctitle(line)
            if proctitle:
                partial["actor"]["proctitle"] = proctitle
            self._commit(audit_id, partial)

    def _commit(self, audit_id: str, partial: dict) -> None:
        actor = partial["actor"]
        for path in partial["paths"]:
            self._add(path, actor)
        self._partials.pop(audit_id, None)

    def _add(self, path: str, actor: dict) -> None:
        now = time.time()
        with self._recent_lock:
            if len(self._recent) >= _AUDIT_RECENT_CAP:
                # Drop the single oldest. dict insertion-order preserved
                # since Python 3.7, so the first key is the oldest.
                try:
                    oldest = next(iter(self._recent))
                    self._recent.pop(oldest, None)
                except StopIteration:
                    pass
            self._recent[path] = (now, actor)

    def _sweep_stale_partials(self) -> None:
        """Audit events that never receive PROCTITLE (rare) would leak the
        partial entry indefinitely. Drop anything older than 5s."""
        now = time.time()
        stale = [aid for aid, p in self._partials.items() if now - p["ts"] > 5.0]
        for aid in stale:
            partial = self._partials.pop(aid, None)
            if partial:
                # Commit what we have — likely incomplete but better than nothing.
                self._commit(aid, partial)

    @staticmethod
    def _parse_syscall(line: str) -> dict:
        """Extract the actor fields we care about from a SYSCALL line."""
        actor: dict = {}
        for k, v in _AUDIT_KV_QUOTED_RE.findall(line):
            if k in _ACTOR_FIELDS:
                actor[k] = v
        # uid/gid/pid/etc. arrive unquoted ("uid=1000" not 'uid="1000"').
        for k, v in _AUDIT_KV_BARE_RE.findall(line):
            if k in _ACTOR_FIELDS and k not in actor:
                # Strip trailing punctuation that bare-key regex captures.
                v = v.rstrip(":,;")
                if k in ("uid", "gid", "euid", "egid", "pid", "ppid"):
                    try:
                        actor[k] = int(v)
                    except ValueError:
                        actor[k] = v
                else:
                    actor[k] = v
        return actor

    @staticmethod
    def _parse_path(line: str) -> str | None:
        m = _AUDIT_NAME_RE.search(line)
        if m:
            return m.group(1)
        m = _AUDIT_NAME_HEX_RE.search(line)
        if m:
            try:
                return binascii.unhexlify(m.group(1)).decode("utf-8", "replace")
            except (binascii.Error, ValueError):
                return None
        return None

    @staticmethod
    def _is_meaningful_nametype(line: str) -> bool:
        """auditd PATH records have a nametype field. We want NORMAL,
        CREATE, DELETE, REPLACE, PARENT — but NOT UNKNOWN (no useful data)
        or DELETE/CREATE redundant pairs for the same op."""
        if "nametype=NORMAL" in line:
            return True
        if "nametype=CREATE" in line:
            return True
        if "nametype=DELETE" in line:
            return True
        return False

    @staticmethod
    def _parse_proctitle(line: str) -> str | None:
        m = _AUDIT_PROCTITLE_QUOTED_RE.search(line)
        if m:
            return m.group(1)
        m = _AUDIT_PROCTITLE_HEX_RE.search(line)
        if m:
            try:
                # Audit hex-encodes proctitle when it has spaces or nulls;
                # nulls separate argv entries — replace with space.
                raw = binascii.unhexlify(m.group(1))
                return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            except (binascii.Error, ValueError):
                return None
        return None


# --- helpers ------------------------------------------------------------------


def _path_allowed(p: str) -> bool:
    return not any(p.startswith(pref) for pref in _EXCLUDED_PATH_PREFIXES)


def _stat_and_hash(path: str) -> dict:
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return {
        "sha256": h.hexdigest(),
        "size": int(st.st_size),
        "perm": stat.S_IMODE(st.st_mode),
        "owner_uid": int(st.st_uid),
        "owner_gid": int(st.st_gid),
        "mtime": float(st.st_mtime),
    }


def _diff_one(path: str, prior: dict | None, meta: dict, *,
              detection: str = "baseline") -> FimChange | None:
    """Compare current meta vs baseline. Returns the change to emit, or None
    if there's no real change."""
    if prior is None:
        return FimChange(
            path=path,
            change_type="created",
            sha256_before=None,
            sha256_after=meta["sha256"],
            size_before=None,
            size_after=meta["size"],
            perm_before=None,
            perm_after=meta["perm"],
            owner_before=None,
            owner_after=_fmt_owner(meta["owner_uid"], meta["owner_gid"]),
            detected_at=_now_iso(),
            detection=detection,
        )

    if (meta["sha256"] == prior["sha256"]
            and meta["perm"] == prior["perm"]
            and meta["owner_uid"] == prior["owner_uid"]
            and meta["owner_gid"] == prior["owner_gid"]):
        return None

    if meta["sha256"] != prior["sha256"]:
        change_type = "modified"
    elif meta["perm"] != prior["perm"]:
        change_type = "perm_changed"
    else:
        change_type = "owner_changed"

    return FimChange(
        path=path,
        change_type=change_type,
        sha256_before=prior["sha256"],
        sha256_after=meta["sha256"],
        size_before=prior["size"],
        size_after=meta["size"],
        perm_before=prior["perm"],
        perm_after=meta["perm"],
        owner_before=_fmt_owner(prior["owner_uid"], prior["owner_gid"]),
        owner_after=_fmt_owner(meta["owner_uid"], meta["owner_gid"]),
        detected_at=_now_iso(),
        detection=detection,
    )


def _make_delete_change(path: str, prior: dict, *, detection: str) -> FimChange:
    return FimChange(
        path=path,
        change_type="deleted",
        sha256_before=prior.get("sha256"),
        sha256_after=None,
        size_before=prior.get("size"),
        size_after=None,
        perm_before=prior.get("perm"),
        perm_after=None,
        owner_before=_fmt_owner(prior.get("owner_uid"), prior.get("owner_gid")),
        owner_after=None,
        detected_at=_now_iso(),
        detection=detection,
    )


def _truncation_marker(cap: int) -> FimChange:
    return FimChange(
        path="<<truncated>>",
        change_type="modified",
        sha256_before=None,
        sha256_after=None,
        size_before=None,
        size_after=None,
        perm_before=None,
        perm_after=None,
        owner_before=None,
        owner_after=None,
        detected_at=_now_iso(),
        detection="baseline",
        note=f"more than {cap} changes in this scan; truncated",
    )


def _fmt_owner(uid: int | None, gid: int | None) -> str | None:
    if uid is None or gid is None:
        return None
    return f"{uid}:{gid}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    try:
        import sys
        print(f"[fim] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass
