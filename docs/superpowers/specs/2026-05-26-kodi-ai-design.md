# Kodi-AI — Design Spec

**Status:** Locked (all 7 sections passed fresh Opus 4.7 reviewer sign-off)
**Date:** 2026-05-26
**Audience:** Implementation lead (handoff to `writing-plans` skill follows)
**Project:** Kodi-AI — Kodi `xbmc.service` add-on that monitors Kodi logs, classifies issues with a cheap LLM, attempts auto-fixes via a tool-calling LLM agent, and surfaces results / asks confirmation via a Telegram bot.

> **Review discipline:** Every section in this spec was drafted, then audited by a fresh independent Claude Opus 4.7 reviewer agent, then revised until the reviewer returned a clean verdict. 22 total review rounds (§1-§3: 8, §4: 4, §5: 4, §6: 2, §7: 4). Same discipline applies to the implementation plan and to every code change downstream.

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [§ 1 Architecture](#-1--architecture)
- [§ 2 Components](#-2--components)
- [§ 3 Data Flows](#-3--data-flows)
- [§ 4 Tool Catalog](#-4--tool-catalog)
- [§ 5 Safety](#-5--safety)
- [§ 6 Testing & Acceptance](#-6--testing--acceptance)
- [§ 7 Setup, Configuration, Distribution](#-7--setup-configuration-distribution)
- [Appendix A — Locked Product Decisions](#appendix-a--locked-product-decisions)
- [Appendix B — Parked for V2](#appendix-b--parked-for-v2)
- [Appendix C — Verified Kodi Facts](#appendix-c--verified-kodi-facts)

---

## Executive Summary

**Problem.** Kodi is highly extensible; users install third-party repositories, add-ons, skins, builds. Quality varies. When things break (dep import errors, dead repos, playback failures), debugging is hard for non-developer users — and even for developers, the multi-layered customization makes root causes hard to find.

**Solution.** A Kodi service add-on (`service.kodi.ai`) that:
1. Monitors `kodi.log` continuously in the background (T2 LogPoll thread).
2. Pre-filters benign noise, clusters errors by normalized signature.
3. Asks a **cheap LLM** ("triage") whether a cluster is genuinely critical.
4. On critical, runs a **stronger LLM** ("reasoner") with a tool-use loop over a curated tool catalog (read logs, install/enable/disable/restart add-ons, edit settings, etc.).
5. Auto-applies safe (`tier=immediate, disruptive=False`) fixes; asks user via Telegram inline keyboard for risky (`tier=confirm` or `disruptive=True`) ones.
6. Snapshots state before every mutation, validates snapshots before undo, supports `/undo` / `/panic` recovery.

**Constraints.**
- V1 = personal use, single user on **Nvidia Shield Pro (Android TV)**. Public release is V2 (architecture future-proofed for hosted-relay LLM provider).
- Distribution: standard Kodi non-official repo (GitHub-Pages-hosted), installed via the user's familiar Settings → File manager → Install-from-zip flow.
- AI: **OpenRouter** (one API key, dozens of models) with **Auto mode** (TaskModelRouter picks per-task) and **Manual mode** (user picks one model). Defaults shipped in `recommended_models.json`, user-overridable.
- Interface: **Telegram bot** (long-poll, no webhooks).
- V1 acceptance scope: (a) addon dep/import errors, (b) repository unreachable / update failures, (c) stream playback failures (source dead, geo-block, codec, hangs).
- Out of V1 scope: auth-token expiry (Trakt/RD/AllDebrid), config automation (skins/menus/builds) — both V2.

**Key risks managed.**
- Reasoner→log→reasoner loop (the AI sees its own side-effects and re-triggers): mitigated by in-memory `ActiveCalls` with target-addon scoping, overlapping-window holding, `[service.kodi.ai]` prefix filter, audit-only log sentinels.
- Shutdown latency / Telegram unresponsiveness during reasoning: 4-thread model with single-flight T4 Worker, abort_event-aware streaming LLM with chunk-level abort, interruptible notifier retry.
- Half-applied mutations: hard rule "no snapshot, no mutation." Snapshot staleness validated on undo.
- Runaway cost: 3-tier budget (per-incident, daily, monthly) with mid-stream truncation producing clean synthetic tool-error envelopes.
- Secrets leaking to LLM or audit log: pattern + heuristic redactor with self-test, type-aware (excludes bool/int), user-extensible `allow_list`.

---

## § 1 — Architecture

### 1.1 Process layout

A single Kodi service add-on (`service.kodi.ai`) installed via standard Kodi non-official repo. Runs inside Kodi's embedded CPython process. **4 OS threads** (Main is minimal):

| Thread | Role | Loop |
|---|---|---|
| **Main** | Bare `xbmc.Monitor()`. Startup orchestration + shutdown coordination only. | `monitor.waitForAbort(1.0)` |
| **T2 LogPoll** | Tail `special://logpath/kodi.log` with adaptive polling. | poll → parse → cluster → enqueue |
| **T3 TGPoll** | Long-poll Telegram Bot API `getUpdates`. | `requests.get(getUpdates, timeout=(3,10))` |
| **T4 Worker** | Single-flight execution: boot pass → triage → reasoner → tool exec → verifier → notifier (inline). | `work_queue.get(timeout=1.0)` |

**Startup order**: Main starts T4 first → T4 boot pass (sessions/* terminal-state recovery + orphan-snapshot cleanup + 24h paused-session expiry) → T4 sets `startup_complete_event` → THEN Main starts T2 and T3. This prevents stale callbacks from racing with boot recovery.

### 1.2 Cross-thread state

All in `lib/concurrency.py`:

```python
abort_event = threading.Event()
startup_complete_event = threading.Event()
_seq = itertools.count()
work_queue = queue.PriorityQueue(maxsize=500)
# Priorities: ResumeWork=0, UserMsg=5, LogIncident=10
# enqueue() helper is the ONLY put API (asserted)

def enqueue(payload):
    prio = {"ResumeWork": 0, "UserMsg": 5, "LogIncident": 10}[type(payload).__name__]
    work_queue.put((prio, next(_seq), payload))

# Fairness: every 10 ResumeWorks drained, T4 force-processes 1 LogIncident if queued
# (private-API peek of PriorityQueue._queue[0] — version-pinned to xbmc.python 3.0.1)

coalesce_lock = threading.Lock()
active_cluster_ids: set[str] = set()       # dedupe at T2 enqueue time
drop_counter = AtomicCounter()              # T2 backpressure increments; T4 reports throttled 5min
paused_sessions: dict[str, SessionState] = {}
paused_sessions_lock = threading.Lock()

class ActiveCalls:
    """Two-scope bracketing with multi-target + 'ALL' support + deferred resolution."""
    def __init__(self):
        self._active_tools: dict[str, set[str] | Literal["ALL"]] = {}  # call_id → targets
        self._active_sessions: set[str] = set()
        self._linger: dict[tuple[str,str], tuple[float, set[str]|str]] = {}
        self._lock = threading.Lock()
    def add_tool(self, call_id, target_addons): ...
    def update_tool_target(self, call_id, target_addons): ...  # deferred refinement
    def schedule_remove_tool(self, call_id, after=1.0): ...
    def add_session(self, sid): ...
    def schedule_remove_session(self, sid, after=2.0): ...
    def is_active(self) -> bool: ...
    def get_active_target_addons_at(self, ts: float) -> set[str] | "ALL": ...
```

### 1.3 Reasoner→log loop prevention (triple defense)

Three layers cooperate; lines pass to incident_queue only if all three allow:

1. **In-memory `ActiveCalls` (primary sync)**. T4 calls `add_tool(call_id, target_addons)` BEFORE every tool call and `schedule_remove_tool(call_id, after=1s)` after. The 1s linger catches delayed log writes (addon shutdown messages, async log flush). T2's parse layer holds new lines in a buffer during active windows.
2. **Per-tool-boundary post-window evaluation**. When a tool's linger expires, T2 evaluates buffered lines whose timestamps fall in that tool's window: lines whose addon_context ∈ tool's target_addons (or target_addons=="ALL") are **discarded** as side-effects; non-target lines are **emitted** as new incidents. Overlapping tool windows: lines held until ALL covering windows expire; suppressed if ANY covering tool's targets include the line's addon. Buffer cap 5 MB / 5000 lines → overflow drops oldest + synthetic "post-window eval skipped" incident.
3. **`[service.kodi.ai]` prefix filter (belt-and-braces)**. Lines with our addon prefix are always suppressed at parse layer, independent of ActiveCalls state.

**Log sentinels** (`xbmc.log("[service.kodi.ai] reason-start <session_id>", LOGINFO)` / `reason-end`) are written for **audit only** — they appear in `kodi.log` for forensic debugging but are NEVER used as a synchronization channel (`xbmc.log` is buffered/async; relying on it for cooperating-thread sync is broken).

**Logging capture for stray output** (`requests`, `urllib3`, `anthropic` SDK if used, native C extensions): see § 5.9.

### 1.4 LogWatcher (T2) details

**Adaptive polling cadence**: 750 ms when log is growing; 2.5 s after 30 s of no growth; snap back to 750 ms on first growth.

**Per-tick read cap**: 1 MB. If size grew >1 MB → read 1 MB, queue catch-up for next tick.

**Burst-mode (skip-to-tail)**: triggered when `work_queue.qsize() >= 400` (80%) AND lag growing across 2 consecutive ticks. Action: read last 1 MB of file, drop middle bytes, do **streaming grep over skipped region** to count ERROR lines per addon prefix, emit synthetic incident `"log burst, N MB skipped; counts: [plugin.video.seren: 50 ERR, ...]"`. Resume normal polling next tick.

**3-signal rotation detection** (any one triggers reopen from offset 0):
- `xbmcvfs.Stat().st_size()` shrunk.
- `st_ino` changed (if available; SAF content URIs may not expose it).
- First-line timestamp regressed (fallback for SAF).

**Boot post-mortem pass** (after T4 sets `startup_complete_event`): scan `kodi.old.log` backward in 256 KB chunks until first sentinel boundary OR (2 MB cap if file ≥50 MB; else EOF). Parse forward, track open sessions (`reason-start` without matching `reason-end`). Suppression in dangling-session regions: ONLY `[service.kodi.ai]`-prefixed lines AND lines whose signature matches a tool call recorded in `sessions/<id>.json`'s tool-history. Foreign-addon errors in the same window surface as **backdated incidents** (so we don't silently lose them).

If `kodi.old.log` doesn't exist (first boot ever) → skip post-mortem, log INFO.

**Signature normalization** (for stable cluster_id): strip memory addresses (`0x[0-9a-fA-F]+`), line numbers in tracebacks (`line \d+`), timestamps (ISO + Unix), UUIDs, file paths (basename only). Two stack traces differing only by line numbers cluster together.

**Polling semantics on Android SAF** (`xbmcvfs.File` is SAF-backed): no blocking-on-growth available. Use `xbmcvfs.Stat(path).st_size()`, `seek(last_offset)`, read incremental bytes.

### 1.5 Quiescence window (trace-continuation aware)

When a new cluster opens, T2 holds it for a quiescence window before enqueueing.

**Continuation patterns**: `^Traceback `, `^\s+File "...", line \d+, in `, `^\s+raise `, `^[A-Z][A-Za-z]+(Error|Exception): `, `^\s+(at|in) `.

**Attachment rules**: Continuation lines have NO addon context of their own. They attach to the **most-recent ERROR-level line in the global stream** ONLY IF:
(a) Within 200 ms of that ERROR, AND
(b) No intervening line from a **different** addon prefix between them.
Lines with NO addon prefix (Kodi core logs, raw stderr captures attributed to nothing) do NOT count as "intervening" — they are transparent for continuation purposes.

Otherwise → orphan → attached to a synthetic "unattributed traceback" incident.

**Hard cap**: 10 s from first cluster line (the ERROR-level opener — not continuations). Beyond that, cluster fires regardless of late continuation arrivals.

### 1.6 Triage rate-limit + cost gate

T2 **never blocks** on rate budget. Always enqueues with `triage_deferred=True`. T4 enforces the token bucket (6 calls/min, burst 3) at triage call time. If no budget → T4 sleeps `next_token_arrival_ms` (interruptible via `abort_event.wait`).

If `work_queue` is full → T2 drops with `drop_counter.inc()`; T4 surfaces drop counts via throttled (1 per 5 min) Telegram notification.

### 1.7 Non-blocking ask_user + pause sequence

When a tool needs user input (any `tier=confirm` tool, or `tier=immediate` tool whose `disruptive(args)=True`), reasoner pauses:

**Pause sequence (deterministic order — round-7 ordering)**:
1. `with paused_sessions_lock: paused_sessions[session_id] = state` (memory).
2. `MonotonicBudget.pause()` (memory — updates `elapsed_baseline`).
3. Atomic disk write under `special://profile/addon_data/service.kodi.ai/sessions/<sid>.json` (POSIX, app-private, atomic rename verified at startup + every 50 writes; smoke tests in `.smoke/` subdir). Captures post-pause budget state.
4. Send Telegram inline keyboard with 15 s deadline.
   - **Success**: reasoner returns from T4.
   - **Failure**: mark state `pause_notify_failed`; persist; Kodi toast; surface via `/status`. Boot watchdog retries on next startup. Session NEVER orphaned.

**Resume**:
- T3 receives callback → `ResumeWork(session_id, user_reply)` → `enqueue()` (priority 0 = highest).
- T4 dequeues. With `paused_sessions_lock`, lookup `paused_sessions[id]` (memory primary, disk fallback for process restart).
- `MonotonicBudget.resume()`. Re-eval `disruptive(args)` ONE final time (single re-eval policy). If newly True → second confirmation via Telegram. Otherwise proceed to tool execution.

### 1.8 MonotonicBudget — typed exceptions

```python
class BudgetStateError(RuntimeError): pass
class BudgetState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()

class MonotonicBudget:
    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self.elapsed_baseline = 0.0
        self.state = BudgetState.IDLE
        self.started_at = None
    def start(self):
        if self.state != BudgetState.IDLE: raise BudgetStateError("...")
        self.state = BudgetState.RUNNING
        self.started_at = time.monotonic()
    def pause(self):
        if self.state != BudgetState.RUNNING: raise BudgetStateError("...")
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.state = BudgetState.PAUSED
    def resume(self):
        if self.state != BudgetState.PAUSED: raise BudgetStateError("...")
        self.started_at = time.monotonic()
        self.state = BudgetState.RUNNING
    def stop(self):
        if self.state != BudgetState.RUNNING: raise BudgetStateError("...")
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.state = BudgetState.IDLE
    def elapsed(self) -> float:
        if self.state == BudgetState.RUNNING:
            return self.elapsed_baseline + (time.monotonic() - self.started_at)
        return self.elapsed_baseline
```

Reasoner catches `BudgetStateError`, logs + aborts gracefully via "internal state error" Telegram message. T4 stays alive.

**Serialization**: `state`, `elapsed_baseline`, `limit_s`. `started_at` is monotonic — NOT serialized; restored as `time.monotonic()` on rehydrate-to-RUNNING. Only PAUSED state is ever persisted (RUNNING crashes lose the session — no recovery by design).

**60 s wall-clock cap** per reasoner session (excluding ask_user pause time). Cap measured against `MonotonicBudget.elapsed()`. Per-incident cost cap: see § 5.5.

### 1.9 Two-tier mutation policy + dynamic disruptive

```python
@tool(
    name=...,
    description=...,
    schema=...,
    tier: Literal["immediate", "confirm"],
    disruptive: Callable[[dict], bool] = lambda a: False,
    target_addons: Callable[[dict], set[str] | Literal["ALL"]] = lambda a: set(),
    snapshot_targets: Callable[[dict], list[SnapshotTarget]] | None = None,
    safety_class: Literal["read_only", "low_risk", "medium_risk", "high_risk"] = "low_risk",
)
```

Routing:
- `tier=immediate` AND `disruptive(args) == False` → apply + notify.
- `tier=immediate` AND `disruptive(args) == True` → downgrade to confirm flow.
- `tier=confirm` → always Telegram `[Apply] [No]` + ask_user.

After user confirmation, at execution time: re-evaluate `disruptive(args)` ONCE. If newly True → second confirmation "Player state changed since you confirmed. Apply anyway? [Force] [Cancel]". No further re-eval after (documented residual microsecond race accepted).

### 1.10 Streaming LLM with chunk abort

All OpenRouter LLM calls use `stream=True`, iterate via `response.iter_lines()`, check `abort_event.is_set()` between chunks. Mid-stream cancel via `r.raw.close(); r.close()` (in that order — guarantees socket FIN before pool release).

Telegram long-poll uses `timeout=(3, 10)` directly; accept 10 s worst-case shutdown delay (documented).

### 1.11 Bare `xbmc.Monitor`

We use only `monitor = xbmc.Monitor()` (no subclass, no overridden callbacks). Methods used: `monitor.waitForAbort(t)`, `monitor.abortRequested()`. Subclassing would introduce Kodi-event-thread callbacks that would race with our worker threads.

### 1.12 Single-flight by construction

T4 is single-threaded → reasoner serialization is intrinsic. Multiple PAUSED sessions coexist (they're suspended, not executing). Shared-state conflicts between two PAUSED sessions touching the same setting are handled by snapshot staleness validation on undo (§ 1.13). PriorityQueue ensures ResumeWork (0) > UserMsg (5) > LogIncident (10); fairness counter forces 1 LogIncident per 10 ResumeWorks if queued.

### 1.13 Snapshot staleness validation

```python
@dataclass
class SnapshotTarget:
    kind: Literal["kodi_setting", "addon_setting", "file", "file_keys", "addon_state"]
    identifier: str
    read_back: Callable[[], Any]  # 2s deadline
    equality: Callable[[Any, Any], bool]
    extract_keys: Callable[[bytes], dict] | None  # required for kind="file_keys"
```

Each tool capped at ≤10 `snapshot_targets`. On undo, `snapshot_manager` calls `read_back()` with 2 s deadline. Timeout OR `equality(current, snapshotted) == False` → STALE → refuse auto-restore → Telegram `[Show diff] [Force restore] [Cancel]`.

`kind="file_keys"` (preferred over `kind="file"` for structured files): declares `extract_keys` (parses XML/JSON, extracts only the keys we modified). Whole-file byte-equality reserved for truly opaque files.

### 1.14 Shutdown protocol

On `monitor.abortRequested()`:
1. Main sets `abort_event`.
2. T4 abort handler writes `last_clean_shutdown_ts = time.time()` to `health.json` (atomic).
3. Main pushes `None` sentinels to `work_queue`.
4. Main joins T2 (3 s), T3 (15 s = 13 s worst-case + 2 s buffer), T4 (5 s).
5. Workers exit:
   - T2: each loop tick checks `abort_event.wait(0.75/2.5)` (interruptible sleep).
   - T3: long-poll has 10 s read timeout + 3 s connect; checks `abort_event` between polls.
   - T4: blocks on `work_queue.get(timeout=1.0)`; receives `None` → exits. Mid-LLM-call: streaming loop's per-chunk abort check exits in <1 s.
6. Kodi force-kills the process if joins fail (safety net).

### 1.15 State location

All persistent state under `special://profile/addon_data/service.kodi.ai/` (POSIX-backed, atomic-rename verified):

```
addon_data/service.kodi.ai/
├── secrets.json                # 0600 best-effort (Android limitation documented)
├── chat_allowlist.json         # Telegram authorized chat_ids
├── budget_counters.json        # daily/monthly counters, per-incident reset on session
├── health.json                 # last_alive_ts, crash_free_since, telegram_last_rt_ok_ts,
                                 #   allowlist_populated_at, last_clean_shutdown_ts
├── sessions/<id>.json          # paused-session state (atomic .tmp + rename)
├── audit/audit.jsonl           # rotation at 10 MB × 5 files
├── setup_secret.txt            # 0600, exists only before first /start; deleted after
├── .smoke/probe.tmp            # atomic-rename smoke test
└── recovery/
    └── last_known_good-<v>.zip # LKG; rotated every 24h crash-free
```

Snapshots stored separately at `special://userdata/Kodi-AI-snapshots/` (outside addon dir; reinstall-safe):
```
Kodi-AI-snapshots/
├── <snapshot_id>/
│   ├── manifest.json           # SnapshotTarget list + values
│   ├── metadata.json           # session_id, tool_name, created_at, label
│   └── files/                  # file copies
├── .undone/<snapshot_id>/      # 24h redo window
└── .orphaned/<snapshot_id>/    # boot-recovery quarantine
```

---

## § 2 — Components

```
service.kodi.ai/                            # Kodi add-on root (id: service.kodi.ai)
├── addon.xml                               # manifest: xbmc.service + xbmc.python.script
├── icon.png, fanart.jpg
├── resources/
│   ├── settings.xml                        # Kodi-native settings UI
│   ├── language/.../strings.po             # i18n (en_GB seed; V2 i18n)
│   └── data/
│       ├── recommended_models.json
│       ├── known_secret_keys.json
│       ├── redaction_allowlist.json
│       └── compat.json
├── service.py                              # 4-thread orchestrator, runs Monitor loop
├── default.py                              # status panel + setup wizard launcher
└── lib/
    ├── settings.py                         # xbmcaddon settings wrapper
    ├── state_paths.py                      # special:// path resolution + mkdirs
    ├── audit_log.py                        # append-only JSONL, rotation at 10 MB × 5
    ├── secrets.py                          # in-memory secret cache, get_secret()
    ├── redactor.py                         # pattern + heuristic + allow_list redaction,
                                            #   canary self-test every 100 redactions
    ├── health.py                           # heartbeat (5 min); crash detection on boot
    ├── recovery.py                         # LKG ZIP (DEFLATE) management
    │
    ├── concurrency.py                      # ActiveCalls, AtomicCounter, MonotonicBudget,
    │                                       #   BudgetStateError, abort_event,
    │                                       #   startup_complete_event, work_queue,
    │                                       #   enqueue() helper, coalesce_lock,
    │                                       #   paused_sessions registry
    │
    ├── log_capture.py                      # logging.Handler with origin metadata
    │                                       #   (thread.ident); stderr/stdout wrappers;
    │                                       #   thread-local recursion guard
    ├── log_watcher.py                      # T2 body: adaptive poll, 1MB cap, burst-mode,
    │                                       #   3-signal rotation, post-window evaluation,
    │                                       #   trace-continuation quiescence, boot
    │                                       #   post-mortem
    ├── log_sentinels.py                    # LOGINFO audit sentinels
    ├── prefilter.py                        # benign-pattern allowlist, signature
    │                                       #   normalization
    │
    ├── triage.py                           # T4 invocation: token bucket (6/min, burst 3),
    │                                       #   cheap LLM call → CRITICAL|ADVISORY|IGNORE
    ├── reasoner.py                         # T4 main: agent loop, MonotonicBudget,
    │                                       #   pause/resume, notifier-before-cleanup,
    │                                       #   re-eval disruptive at execution time
    ├── reasoner_state.py                   # SessionState dataclass; atomic .tmp+rename
    │                                       #   write; in-memory primary, disk fallback
    ├── verifier.py                         # per-cluster-category strategies (playback_fail,
    │                                       #   dep_import_fail, repo_unreachable, default);
    │                                       #   subscribes to log_watcher event stream
    ├── notifier.py                         # synchronous, called inline by T4;
    │                                       #   abort-aware interruptible retry;
    │                                       #   shutdown short-path; toast fallback
    │
    ├── llm/
    │   ├── client.py                       # OpenRouter HTTP (OpenAI-compat),
    │   │                                   #   stream=True, chunk-level abort,
    │   │                                   #   DEFAULT_PREFLIGHT_MODEL constant
    │   ├── router.py                       # TaskModelRouter (auto / manual)
    │   ├── budget.py                       # BudgetGuard: per-incident hard cap (3-point),
    │   │                                   #   per-day, per-month; cost from response
    │   │                                   #   payload; rolls over on user TZ
    │   └── prompts/
    │       ├── triage_system.md            # frontmatter prompt_version + prompt_hash
    │       ├── reasoner_system.md
    │       └── chat_system.md
    │
    ├── tools/
    │   ├── __init__.py                     # @tool decorator + registry
    │   ├── schema.py                       # tool → OpenAI-format function spec
    │   ├── kodi_addons.py                  # install/uninstall/enable/disable/restart/
    │   │                                   #   update/clear_cache; executebuiltin verify
    │   ├── kodi_settings.py                # get/set Kodi + per-addon settings (enabled
    │   │                                   #   via xbmcaddon API; disabled via direct
    │   │                                   #   xmlparse + V1 type-coercion)
    │   ├── kodi_files.py                   # read/write under data dirs only
    │   ├── kodi_jsonrpc.py                 # raw JSON-RPC (allowlist-only enforcement)
    │   ├── http.py                         # http_get HTTPS-only (loopback exception),
    │   │                                   #   15s timeout, 1MB size cap
    │   ├── verify.py                       # verify_fix per-strategy
    │   ├── telegram_ask.py                 # ask_user → triggers pause sequence
    │   └── extract_keys.py                 # flat-id, path-flatten with [N] indexing, JSON
    │
    ├── snapshot_manager.py                 # snapshot/undo with read_back+equality
    │                                       #   staleness validation; orphan recovery on
    │                                       #   boot; LRU 100/200MB
    │
    ├── qr.py                               # pure-Python QR encoder + PNG writer
    │                                       #   (stdlib zlib only)
    │
    └── telegram/
        ├── bot.py                          # T3 body: long-poll timeout=(3,10), dispatch
        ├── auth.py                         # setup_secret first-/start, chat_allowlist
        │                                   #   persistence, reset path via Kodi UI only
        ├── commands.py                     # /help /status /undo /pause /resume /disable
        │                                   #   /enable /panic /budget /mode /secret
        │                                   #   /audit /retry-notify /invite
        ├── callbacks.py                    # callback_query routing (reply_to_message_id
        │                                   #   first; fallback most-recent paused session
        │                                   #   for chat_id, 1h TTL)
        └── formatters.py                   # HTML (parse_mode=HTML, not MarkdownV2),
                                            #   4000-char truncate + multi-part split
```

### 2.1 Key interfaces

```python
@dataclass(frozen=True, order=False)
class LogIncident:
    cluster_id: str
    first_seen: datetime
    last_seen: datetime
    occurrences: int
    raw_lines: list[str]
    severity_hint: str           # "ERROR" | "WARNING" | "CRITICAL"
    likely_addon: str | None
    likely_action: str | None
    backdated: bool              # True if from kodi.old.log post-mortem
    from_previous_session: bool
    triage_deferred: bool

@dataclass(frozen=True, order=False)
class UserMsg:
    chat_id: int
    text: str
    message_id: int
    reply_to_message_id: int | None

@dataclass(frozen=True, order=False)
class ResumeWork:
    session_id: str
    user_reply: str | bool       # bool for keyboard callbacks, str for text

WorkItem = LogIncident | UserMsg | ResumeWork

@dataclass(frozen=True)
class ToolResult:
    success: bool
    requested: str
    output: Any | None
    actual_state_after: dict | str | None  # verification readback
    error: str | None
    snapshot_id: str | None
    cost_seconds: float
    warning: str | None = None
```

### 2.2 V1 hard dependencies

- Telegram for `tier=confirm` tools (fail with "Telegram offline" message if Bot API unreachable >2 min).
- OpenRouter for any LLM call (degraded mode if OpenRouter down: see § 7.7).
- `script.module.requests` from Kodi 21 Omega repo (pin to verified version at release time).
- No vendored deps beyond Kodi's bundled `script.module.requests`. No `Pillow`/`qrcode`/`anthropic`/`openai` SDK.

---

## § 3 — Data Flows

### 3.1 Flow 1 — Proactive (Seren playback fails)

```
T=0       User taps Play (Seren). Seren logs ERROR 404.

T+0–0.75s T2 polls (file growing → 750ms cadence):
          • xbmcvfs.Stat → size grew (≤1MB), seek+read new bytes
          • parse, normalize signature → cluster_id="seren_404_v2"
          • per-addon context = "[plugin.video.seren]"
          • ActiveCalls.is_active() = False → not suppressed
          • not [service.kodi.ai] prefix
          • coalesce_lock → cluster_id not in active_cluster_ids
          • start quiescence (trace-continuation aware)

T+0.5–2s  Stack trace continuation lines. Each attached to most-recent ERROR (Seren's)
          per global-stream rule (within 200ms, no different-prefix intervening).
          Window resets per continuation.

T+5s      Quiescence closes (no continuation 3s OR 10s cap from first cluster line).
          enqueue(LogIncident(triage_deferred=True)). active_cluster_ids += cluster_id.

T+5.5s    T4 dequeues. drop_counter check: 0. Triage token bucket: tokens available.
          Triage LLM call (streaming, t0 model). ~$0.0001.
T+6s      Triage → CRITICAL.

T+6s      Reasoner. session_id = secrets.token_hex(8) (unique-asserted vs paused_sessions
          + sessions/* filenames; regenerate on collision).
          ActiveCalls.add_session(session_id).
          MonotonicBudget(60s).start(). State: RUNNING.
          (Sentinel "reason-start" LOGINFO for audit only.)

T+6–11s   Reasoner agent loop (streaming LLM, chunk-level abort + mid-stream budget check):
          • read_log → ActiveCalls.add_tool("t1", target_addons=set()) → execute →
              schedule_remove_tool("t1", 1s)
          • get_addon_setting "plugin.video.seren:default_resolver" →
              add_tool("t2", target_addons={"plugin.video.seren"}) → "real_debrid"
          • http_get RD API → add_tool("t3", target_addons=set()) → 401
          • DECISION: set_addon_setting (tier=confirm).
            Pause (round-7 order):
              1. paused_sessions[sid] = state (memory)
              2. MonotonicBudget.pause() (memory; elapsed_baseline updated)
              3. Atomic disk write under special://profile/.../sessions/
              4. Send Telegram inline keyboard "Switch Seren resolver to Premiumize?
                 RD auth expired (401). [Apply] [No]"
            Reasoner returns from T4. ActiveCalls.add_session linger continues.

T+9.5s    User taps [Apply] in Telegram.
T+10s     T3 → ResumeWork (priority=0) → enqueue().
T+10.05s  T4 dequeues ResumeWork. paused_sessions_lock → lookup [sid] → in-memory hit.
          MonotonicBudget.resume(). State: RUNNING.
          
          RE-EVAL DISRUPTIVE: set_addon_setting's disruptive(args)=False (doesn't
          depend on player state) → proceed directly.

T+10.1s   snapshot_create:
            snapshot_targets = [SnapshotTarget(
                kind="addon_setting",
                identifier="plugin.video.seren:default_resolver",
                read_back=lambda: get_addon_setting("plugin.video.seren", "default_resolver"),
                equality=lambda c, s: c == s)]
            Capture current value "real_debrid" → store as snapshot "snap_T+10.1".
T+10.2s   add_tool("t_setting", target_addons={"plugin.video.seren"})
T+10.3s   set_addon_setting (xbmcaddon.Addon path since Seren is enabled):
            xbmcaddon.Addon("plugin.video.seren").setSetting("default_resolver", "premiumize")
T+10.4s   Verify: read_back == "premiumize" → ok.
          ToolResult(success=True, actual_state_after={"default_resolver":"premiumize"},
                    snapshot_id="snap_T+10.1"). schedule_remove_tool("t_setting", 1s).

T+10.5s   (Seren's own log "settings changed: default_resolver=premiumize" appears in
           kodi.log between T+10.2 and T+10.5s. T2 polls, parses, sees
           ActiveCalls.is_active()=True with target_addons including "plugin.video.seren"
           → BUFFERS line. Will be discarded when t_setting's linger expires.)

T+10.6s   Reasoner final_message.
          Set state "fix_complete_notify_pending" (memory + atomic disk).
          Notifier call (interruptible retry):
            • Try Telegram with timeout=(3,10) → success on attempt 1.
          Set state "fix_complete" → delete paused_sessions[sid] + unlink sessions/<sid>.json.
          Sentinel "reason-end" LOGINFO.
          ActiveCalls.schedule_remove_session(sid, 2s).

T+11.4s   ActiveCalls truly idle (linger expired). T2 post-window evaluation:
          • Buffered "plugin.video.seren" lines → discarded (target match).
          • No foreign-addon lines buffered.

T+10.6s+  Verifier (cluster_category="playback_fail"):
            Wait for Player.OnPlay on plugin.video.seren AND no cluster_id recurrence
            in next 10s, OR recurrence, OR 5min, OR abort_event.
            Edit Telegram message on verdict: "✅ Confirmed working" or "❌ Same error
            recurred — try different fix?"

Total: ~11s active reason + 30s background verify. Cost: ~$0.003.
```

### 3.2 Flow 1b — Disruptive re-eval (worked example)

AI proposes `restart_addon("plugin.video.bigbuck")` at T=0. `restart_addon.disruptive(args) = lambda a: addon_owns_active_player(a["addon_id"])` → at proposal time → `True` (addon owns active player).

Tool routed to confirm flow → pause → Telegram "Restart BBB? It owns the active player; may interrupt playback. [Apply] [No]" → user thinks → taps [Apply] at T=30s.

T4 resumes. Re-eval `disruptive(args)`:
- Still True → second confirmation "Player state changed since you confirmed. Apply anyway? [Force] [Cancel]" — or in this case: "Confirming you still want to restart the addon currently owning playback?"
- Now False (user stopped playback in meantime) → proceed without second confirmation; audit "disruptive→non-disruptive at execution" entry.

Either way, no TOCTOU silent disruption.

### 3.3 Flow 2 — Reactive (user DM)

```
T=0     User DMs "Why is Kodi slow?"
T+0.5s  T3 long-poll returns. auth.py → chat_id allowlisted.
        UserMsg → enqueue() (priority=5).
T+0.6s  T4 dequeues. No triage (user-initiated). session_id="b8c2e1d9".
        ActiveCalls.add_session. MonotonicBudget(60s).start().
T+0.6–4.5s  Reasoner runs (t1 model):
            • read_log (read-only, target_addons=set())
            • list_addons(type="xbmc.service", enabled=True)
            • get_setting "video.cachemembuffersize"
            • final message with inline keyboard suggesting "Disable service.subtitles.X
              + bump cache. [Disable + bump] [Just bump] [Just disable] [No]"
            All proposed tools are tier=confirm → pause + serialize + Telegram.
            Reasoner returns from T4. MonotonicBudget.pause().
T+30s   User taps "Disable + bump cache".
T+30.5s ResumeWork → T4 → rehydrate. Re-eval disruptive (False for both) → execute.
        snapshot_create → disable_addon → set_setting → ToolResults →
        final_message → sentinel reason-end. Notifier confirms.
Cost: ~$0.002.
```

### 3.4 Failure handling (representative)

| Failure | Handling |
|---|---|
| Line during active window from non-target addon | NOT suppressed. Emitted as new incident after window closes. |
| Line during active window from target addon | Buffered, then discarded post-window. |
| Overlapping tool windows | Lines held until ALL covering windows expire; suppressed if ANY covering tool's targets include the line's addon. |
| Unprefixed continuation line | Attached to most-recent global-stream ERROR (within 200ms, no different-prefix intervening). |
| Burst skip-to-tail | Synthetic incident with per-addon ERROR counts for partial visibility. |
| Pause sequence step 1-2 crash | No disk record → user re-prompted on next reasoner trigger. |
| Pause sequence step 3-4 crash | On restart, boot pass sees `paused` state → re-sends Telegram. MonotonicBudget rehydrates correctly. |
| Notifier mid-shutdown | `abort_event.wait(b)` returns True → bail; mark `notify_failed`; T4 exits within window. |
| Disruptive re-eval flips True at execution | Second confirmation prompt with [Force]/[Cancel]. |
| Snapshot stale on undo | Refuse auto-restore. Telegram diff prompt. |
| Orphan snapshots on boot | Moved to `snapshots/.orphaned/` for manual review. |
| Continuation never stops | 10s hard cap from first cluster line. |
| Boot pass corrupt sessions/*.json + corrupt-write fails | Log ERROR loudly; skip; continue startup. |
| BudgetStateError during reasoner | Caught → "internal state error" Telegram message; T4 stays alive. |
| OpenRouter 4xx (model not found) | Swap to next in fallback list; do NOT retry same. |
| OpenRouter 429 | Honor Retry-After; retry same model 3× with backoff; then swap. |
| OpenRouter 5xx / network | 3 retries exponential backoff same model; then swap; all interruptible. |
| All fallbacks exhausted | ToolResult(success=False, error="all LLM providers unavailable"); escalate to user. |
| Telegram 429 | Honor Retry-After; exp backoff with jitter; 60s cap; all interruptible. |
| Per-incident budget hit mid-stream | Cancel stream → synthetic envelope `{"error":"budget_truncated"}` → reasoner pauses + notifies. |
| Daily budget hit | Refuse new LLM calls; chat falls back to advisory-only (read-only tools). |
| Tool call fails | ToolResult.success=False with error; reasoner sees in next turn, re-plans. |
| Snapshot fails (disk, perms) | HARD RULE: no snapshot, no mutation. Refuse tool. |
| Kodi shutting down mid-reason | abort_event.set() → adapter aborts streaming → T4 writes session_aborted audit → joins within 5s. Snapshot preserved. |
| User taps Undo | Snapshot staleness check → restore or prompt force. Mark incident user-rejected so reasoner doesn't retry same fix for this cluster. |

### 3.5 UX policies

- **Notify-before-verify** for `tier=immediate` non-confirmed fixes. Verifier edits the same Telegram message on verdict.
- `tier=confirm` fixes: user already opted in, so notify on apply is just confirmation.
- **No "is Kodi in use" gate in V1** for `tier=immediate` non-disruptive. `disruptive(args)` callable handles per-tool playback-aware downgrade to confirm.

---

## § 4 — Tool Catalog

### 4.1 Registration + dispatch

`@tool` decorator (locked in § 1.9). `ToolResult` dataclass (locked in § 2.1).

**Dispatch flow** (T4 invoking a tool):
1. Reasoner emits tool_call → `tools_registry.get(name)`.
2. Validate args against `schema`; on invalid → `ToolResult(success=False, error="schema validation: ...")`.
3. Compute `target_addons(args)` (deferred via `update_tool_target` if mid-execution resolution needed). Call `ActiveCalls.add_tool(call_id, target_addons)`.
4. If `tier == "confirm"` OR (`tier == "immediate"` AND `disruptive(args) == True`):
   - Trigger pause sequence (§ 1.7). Wait for ResumeWork.
   - On resume, re-eval `disruptive(args)` once. If newly True AND not already confirmed-as-disruptive, second confirmation.
5. If `snapshot_targets(args)` is not None:
   - Compute target list; assert `len ≤ 10`.
   - For each target: `read_back()` with 2 s deadline → store snapshotted value.
   - Persist bundle under `Kodi-AI-snapshots/<snapshot_id>/`.
   - Set `ToolResult.snapshot_id`.
6. Execute tool body within `try/finally` (finally → `ActiveCalls.schedule_remove_tool(call_id, after=1s)`).
7. If tool uses `xbmc.executebuiltin`: builtin_with_verify wrapper (§ 4.2).
8. Return `ToolResult`.

### 4.2 `builtin_with_verify` wrapper

```python
def builtin_with_verify(builtin: str, verify: Callable[[], bool],
                        timeout_s: float = 10.0) -> bool:
    xbmc.executebuiltin(builtin)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if abort_event.wait(0.25):  # interruptible — NOT time.sleep
            return False
        if verify():
            return True
    return False
```

**Per-tool timeouts**:
- `enable_addon` / `disable_addon` → 10 s.
- `restart_addon` → 15 s (disable + enable).
- `install_addon` / `update_addon` → 60 s (dep-tree downloads can be slow on Shield over weak Wi-Fi).

**`update_addon` verify logic** (round-3 corrected — no `refresh=True`):
1. Pre-call: `Addons.GetAddonDetails(addon_id, properties=["version"])` → capture `old_version`.
2. `xbmc.executebuiltin('UpdateAddon(<addon_id>)')`.
3. `builtin_with_verify(verify=lambda: get_addon_details(addon_id)["version"] != old_version, timeout_s=60)`.
4. Verdict mapping:
   - Version changed within 60s → `success=True, output="updated {old}→{new}"`.
   - 60s timeout AND no cluster_id recurrence → `success=True, output="already at latest or repo unreachable", warning="cannot distinguish"`.
   - 60s timeout AND cluster_id recurrence → `success=False, error="update failed; error recurrence in log"`.

### 4.3 JSON-RPC allowlist (enforcement: allowlist-only)

**Allowlisted (read-only):**
- `Addons.GetAddons`, `Addons.GetAddonDetails`.
- `Settings.GetSettings`, `Settings.GetSettingValue`, `Settings.GetCategories`.
- `System.GetProperties`, `Application.GetProperties`.
- `Player.GetActivePlayers`, `Player.GetItem`, `Player.GetProperties`, `Player.GetPlayers`.
- `JSONRPC.Introspect`, `JSONRPC.Permission`, `JSONRPC.Version`, `JSONRPC.Ping`.
- `Files.GetDirectory`, `Files.GetFileDetails`, `Files.GetSources`, `Files.PrepareDownload`.
- `GUI.GetProperties`.
- `Profiles.GetCurrentProfile`, `Profiles.GetProfiles`.
- `Textures.GetTextures`.
- `PVR.GetProperties`, `PVR.GetChannels`, `PVR.GetClients`.

**Documented forbidden methods** (enforcement is allowlist-only; listed for clarity):
- `Settings.Set*`/`Reset*`, `Addons.SetAddonEnabled`/`ExecuteAddon`.
- `Application.Quit`/`SetVolume`/`SetMute`.
- `System.Hibernate`/`Shutdown`/`Reboot`/`Suspend`/`EjectOpticalDrive`.
- `Player.Open`/`Stop`/`Move`/`Seek`/`Set*`/`PlayPause`/`GoTo`.
- `GUI.ActivateWindow`/`ShowNotification`/`Set*`.
- `Input.*` (all Up/Down/Select/etc.).
- `Favourites.AddFavourite`.
- `Files.SetFileDetails`/`Download`.
- `VideoLibrary.Clean`/`Export`/`Scan`/`Remove*`/`Set*`.
- `AudioLibrary.Clean`/`Export`/`Scan`/`Set*`.
- `PVR.Record`/`Scan`/`AddTimer`/`DeleteTimer`/`ToggleTimer`.
- `Profiles.LoadProfile`.
- `Textures.RemoveTexture`.

Method not on allowlist → `ToolResult(success=False, error="method '<name>' not allowlisted; use typed tool or request §4 allowlist extension")`.

### 4.4 Verifier subscription pattern

`log_watcher` exposes `subscribe(filter_fn, timeout_s, on_match)`. Verifier subscribes to T2's parsed event stream (no second tail). Single LogWatcher; multiple subscribers via thread-safe queues.

**Per-cluster-category strategies:**

| Category | Strategy |
|---|---|
| `playback_fail` | Wait for `Player.OnPlay` JSON-RPC notification on same addon AND no recurrence of `cluster_id` in next 10 s, OR recurrence, OR 5 min, OR `abort_event`. JSON-RPC notifications polled via 1 s `Player.GetActivePlayers` ticks (TCP socket listener at 9090 deferred to V2). |
| `dep_import_fail` | `restart_addon` + observe log for clean import (no recurrence in next 30 s) OR same error. |
| `repo_unreachable` | Poll repo URL via `http_get` every 1 min for up to 30 min. On 200 → re-run `update_addon` for each affected addon. On timeout → final notification "still down; check manually." |
| `default` | 30 s log-quiet window for cluster_id. |

All verifier loops use `abort_event.wait(0.25)` instead of `time.sleep` (interruptible).

### 4.5 Cross-cutting infrastructure

**LLM model fallback (TaskModelRouter)**:

Lists from `resources/data/recommended_models.json`; user-overridable via addon setting `models_override` (JSON). Per task class, ordered fallback list:

```json
{
  "t0_triage":  ["google/gemini-2.0-flash-001", "meta-llama/llama-3.3-8b-instruct", "anthropic/claude-haiku-4.5"],
  "t1_simple":  ["deepseek/deepseek-chat-v3", "google/gemini-2.5-flash", "openai/gpt-4o-mini", "anthropic/claude-haiku-4.5"],
  "t2_reason":  ["anthropic/claude-haiku-4.5", "deepseek/deepseek-r1", "google/gemini-2.5-pro", "openai/gpt-4o"],
  "t3_heroic":  ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "deepseek/deepseek-r1", "anthropic/claude-haiku-4.5"]
}
```

`DEFAULT_PREFLIGHT_MODEL = "google/gemini-2.0-flash-001"` (constant in `lib/llm/client.py`; documented "verify on each release"; used by Screen 1 preflight when models cache is empty).

**Slug validation on startup**: T4 calls OpenRouter `/api/v1/models` with 10 s timeout + 1 retry (20 s worst case). Does NOT block startup. On any miss → deferred Telegram notification (post-`/start`) "Some models unavailable: [list]. Active fallbacks: [list]." Also surfaced via `/status`.

**Per-call HTTP error handling** (already specified above): 4xx swap; 429 honor Retry-After + retries; 5xx/network retries + swap; all interruptible.

**Telegram backoff**: Retry-After honored; exp with jitter; 60 s cap; all interruptible.

**Telegram formatting**:
- `parse_mode=HTML`.
- All dynamic content via `html.escape(text)`.
- URLs in hrefs: `html.escape(url, quote=True)`.
- Log content / stack traces always in `<pre>` after escape.
- **4000-char limit** (96-char safety margin under Telegram's 4096): truncate with `... (truncated — full in /status)`. Truncation after HTML construction. Long messages split into multi-part with `(part N/M)` headers.

### 4.6 V1 tool catalog

**Inspection tools (read-only, no snapshot):**

| Tool | Description (LLM-facing, abbreviated) |
|---|---|
| `read_log(lines=200, level="ERROR", addon=None, since_seconds=None)` | Recent kodi.log lines. |
| `read_log_old(lines=200, level="ERROR")` | kodi.old.log tail for boot-time diagnosis. |
| `list_addons(type=None, enabled=None, broken=None)` | List addons. **`enabled=None` returns ALL** including disabled (use for dep diagnosis). Same for `broken=None`. |
| `get_addon_details(addon_id)` | Full info: id, name, version, enabled, broken, path, dependencies (recursive). |
| `get_addon_setting(addon_id, key)` | Read addon-specific setting. For disabled addons, merges user values from `addon_data/<id>/settings.xml` with schema/defaults from `<install_path>/resources/settings.xml`; returns value + schema metadata in `actual_state_after`. |
| `get_kodi_setting(setting_id)` | `Settings.GetSettingValue`. |
| `list_repositories()` | Filters `list_addons` for type="xbmc.addon.repository". |
| `get_active_player()` | `Player.GetActivePlayers`. |
| `get_player_item()` | `Player.GetItem` for active player. |
| `kodi_jsonrpc(method, params={})` | Raw JSON-RPC; allowlist-only enforcement (§ 4.3). |
| `http_get(url, timeout_s=15, max_bytes=1_048_576)` | HTTPS-only unless `127.0.0.1`/`localhost`; size/timeout cap. |
| `list_snapshots(session_id=None, limit=20)` | Recent snapshots. |

**Addon mutation:**

| Tool | Tier | Disruptive | Target Addons | Snapshot Targets | Verify timeout |
|---|---|---|---|---|---|
| `install_addon(addon_id)` | confirm | False | `{addon_id} ∪ dep_closure(addon_id)` (deferred refinement via update_tool_target after `GetAddonDetails` recursion) | `[addon_state(addon_id)]` | 60 s |
| `uninstall_addon(addon_id)` | confirm | `addon_owns_active_player(addon_id)` | `{addon_id}` | `[addon_state]` | 10 s |
| `enable_addon(addon_id)` | immediate | False | `{addon_id}` | `[addon_state]` | 10 s |
| `disable_addon(addon_id)` | confirm | `addon_owns_active_player(addon_id)` | `{addon_id}` | `[addon_state]` | 10 s |
| `restart_addon(addon_id)` | immediate | `addon_owns_active_player(addon_id)` | `{addon_id}` | `[addon_state]` | 15 s |
| `update_addon(addon_id)` | confirm | False | `{addon_id}` | `[addon_state]` | 60 s |
| `clear_addon_cache(addon_id)` | immediate | `addon_owns_active_player(addon_id)` | `{addon_id}` | None (cache disposable) | n/a |

**`clear_addon_cache` semantics**: deletes BOTH `special://profile/addon_data/<id>/cache/` AND `<install_path>/__pycache__/` (path from `get_addon_details`'s `path` field). On `PermissionError` (system-installed addon) → `ToolResult(success=False, error="cannot purge pycache: addon install path read-only")`. Then internally calls `restart_addon(addon_id)` to invalidate already-loaded modules.

**Settings mutation:**

| Tool | Tier | Disruptive | Target Addons | Snapshot Targets |
|---|---|---|---|---|
| `set_addon_setting(addon_id, key, value)` | confirm | False | `{addon_id}` | `[addon_setting(addon_id:key)]` |
| `set_kodi_setting(setting_id, value)` | confirm | `setting_id in DISRUPTIVE_KODI_SETTINGS` | `"ALL"` if `setting_id in CROSS_ADDON_SETTINGS` else `set()` | `[kodi_setting(setting_id)]` |

`DISRUPTIVE_KODI_SETTINGS` = `videoplayer.*, audiooutput.*, videoscreen.*, lookandfeel.skin, general.cache*`.
`CROSS_ADDON_SETTINGS` = `services.*, general.*, lookandfeel.*`.

**`set_addon_setting` enabled-vs-disabled path:**
- If `is_addon_enabled(addon_id)`: `xbmcaddon.Addon(addon_id).setSetting(key, value)`. Verify via `getSetting`. Force restart only if change requires it (LLM hint).
- If disabled: parse `<install_path>/resources/settings.xml` for `<setting id="key" .../>`. If not found → reject "addon has no setting `key`". Type-specific V1 validation:
  - `bool` → coerce to "true"/"false".
  - `number`/`integer` → numeric coerce; range-validate if `range="lo,hi[,step]"`.
  - `string`/`text` → pass through.
  - `enum` → V1 SKIPS enum validation; accepts user value with WARNING in `ToolResult.warning`. (LLM SHOULD pre-inspect enum values via `get_addon_setting` schema before writing.)
  - `slider`/`action`/other → reject "type X not supported for disabled addons in V1".
- Direct xbmcvfs write to `addon_data/<id>/settings.xml` (XML round-trip preserves other settings). Verify via re-parse.

**File mutation:**

| Tool | Tier | Disruptive | Target Addons | Snapshot Targets |
|---|---|---|---|---|
| `write_file(path, content)` | confirm | False | inferred from path (`addon_data/<addon>/...` → `{addon}`; else `"ALL"`) | `[file_keys(path)]` if XML/JSON, else `[file]` byte-equality |
| `delete_file(path)` | confirm | False | as above | `[file_keys or file]` |

Path restrictions: only under `special://profile/`, `special://userdata/`, `special://temp/`. Other → reject.

**`extract_keys` parsers** (V1):
- Flat-id (`settings.xml`, `addon.xml`): walk `<setting id="X" value="Y"/>` → `{X: Y}`.
- Path-flatten (`advancedsettings.xml`, `sources.xml`, `mediasources.xml`): walk tree, emit `"network/buffermode" → "1"`. **Repeated sibling elements at same path** → `path[N]` zero-indexed in document order: `sources/video/source[0]/name → "Movies"`, etc.
- JSON: parse, key-walk → `{flat.key.path: value}`.
- Other paths → byte-equality fallback (`kind="file"`).

Parsers handle XML comments (ignored), namespaces (stripped), CDATA (text content preserved), whitespace (preserved within values, normalized in keys).

**User interaction:**

| Tool | Description |
|---|---|
| `notify_user(message, urgency="medium")` | Telegram message + Kodi toast fallback. `urgency ∈ {low, medium, high}` → Telegram silent/sound/disable_notification controls. |
| `ask_user(question, options)` | Inline keyboard. Triggers pause sequence. MonotonicBudget paused during user think-time. On resume returns selected option. |

**Snapshot / Verify:**

| Tool | Description |
|---|---|
| `snapshot_create(label, targets)` | Explicit snapshot (rare — most tools auto-snapshot via `snapshot_targets`). |
| `snapshot_restore(snapshot_id)` | Restore. Runs staleness validation; on stale → `success=False` with detail; caller decides whether to ask user [Force restore]. |
| `verify_fix(strategy, args)` | Run verifier with named strategy. Returns ToolResult on verdict. |

### 4.7 Repo-unreachable V1 policy (notify-only)

V1 has **NO** `install_repository_from_zip` tool (sideload requires user-side action: enable Unknown sources + ZIP install + add as source — outside automated scope for V1).

When AI detects `repo_unreachable`:
1. Diagnose: `list_repositories()` + `http_get(repo_url)` → confirm unreachable.
2. Notify: `notify_user(message=..., urgency=high)` with actionable instructions (community alternatives + manual install steps).
3. `verify_fix(repo_unreachable)`: poll http_get every 1 min for 30 min; on recovery → `update_addon` for each affected; notify success. On timeout → final "still down."

V2 may add guided "install from zip" tool with explicit per-step user confirmation.

### 4.8 Defense-in-depth summary

- Schema validation + tier/disruptive gating + mandatory snapshot.
- `executebuiltin` always paired with `builtin_with_verify` readback.
- JSON-RPC raw is allowlist-only.
- LLM model fallback prevents single-provider outage from deadlocking.
- Telegram backoff prevents 429 storms.
- Verifier strategies per cluster category.

---

## § 5 — Safety

### 5.1 Secrets storage

`secrets.json` under `special://profile/addon_data/service.kodi.ai/` (POSIX, `0600` best-effort; Android scoped storage may not honor — documented; same trust model as Trakt/Real-Debrid/AllDebrid keys in their respective addons).

In-memory cache loaded at startup. Settings UI renders secret fields as `type="password"`.

Access via `lib/secrets.py::get_secret(name)`. Module-level guard: T4 + T3 read; T2 does not.

### 5.2 Telegram authentication (setup secret + chat_allowlist + reset)

**First-run setup:**
1. Generate `setup_secret = secrets.token_urlsafe(8)` (≈11 URL-safe chars).
2. Display via primary path: in-Kodi `default.py` modal dialog launchable from "Add-ons → Kodi-AI → Show setup secret". Renders **both** plain text (selectable with remote, readable on TV) AND a **QR code** encoding `https://t.me/<bot_username>?start=<setup_secret>` (browser-compatible — works with any phone camera). QR rendered at ≥40% screen width, error-correction level H, high-contrast. Pure-Python QR + PNG writer in `lib/qr.py` using stdlib `zlib` only (~600 LoC, no PIL/Pillow/qrcode deps). PNG file deleted from `addon_data/` on dialog close (`WindowXML` `onUnload` hook). QR rendering gated on `bot_username` presence; if missing → plain-text only + "Set bot_username in addon settings to enable QR."
3. Fallback display paths: Kodi toast (high priority, 30 s), LOGERROR in `kodi.log`, `setup_secret.txt` in addon_data (0600).
4. Bot only accepts `/start <secret>` until allowlist populated. Other messages → "Please send `/start <secret>` from your Kodi log/addon dir."
5. On valid `/start <secret>`: chat_id added to `chat_allowlist`; `setup_secret.txt` deleted; bot sends "Welcome — Kodi-AI ready."
6. Subsequent `/start` from other chats → rejected "This bot is owned by another chat."

**Reset path**: Kodi addon settings UI button "Reset bot owner" calls `default.py` → regenerates setup_secret, clears chat_allowlist, recreates `setup_secret.txt`. **Not callable from Telegram** (would defeat the purpose).

**Multi-chat (V2)**: chat_allowlist is already a list; `/invite <secret>` command added in V2.

### 5.3 Audit log

**JSONL schema** (one event per line):
```python
{
  "ts": "2026-05-26T18:04:11.123Z",
  "event": "tool_call" | "llm_call" | "incident_received" | "session_start" |
           "session_end" | "resume_work" | "snapshot_create" | "snapshot_restore" |
           "notify_send" | "notify_fail" | "user_message" | "user_callback" |
           "startup" | "shutdown",
  "session_id": str | None,
  "details": dict,                # event-specific
  "redacted": list[str]           # JSONPath-style keys redacted in this record
                                  # (empty list = nothing redacted;
                                  #  bool(redacted_list) preserves truthiness)
}
```

Per-event `details`:
- `tool_call`: tool_name, args (with secret redactions applied per § 5.8), result_summary, duration_ms, cost_seconds, snapshot_id.
- `llm_call`: task_class, model_used, tokens_in, tokens_out, cost_usd, latency_ms, prompt_hash, prompt_version.
- `incident_received`: cluster_id, severity_hint, likely_addon, occurrences.
- `session_start`/`session_end`: terminal_state, total_cost_usd, total_tokens.
- `resume_work`: session_id, user_reply (redacted), latency_since_pause_seconds.
- `snapshot_*`: snapshot_id, targets (redacted), success.
- `notify_*`: chat_id_hash, message_hash, retries, success.
- `user_message`: chat_id_hash, message_hash (NOT content — privacy).

**Audit redaction policy**:
- Single-key tools (`set_addon_setting` / `get_addon_setting` single key): pair-level redaction `{addon_id, key, value}` → `{addon_id: "<redacted-secret-addon>", key: "<known-secret-key>", value: "<redacted>"}` if key matches `known_secret_keys ∪ heuristic`.
- Bulk-read tools (`get_addon_details` with settings, `list_addon_settings`): value-level per-key redaction; skeleton `{addon_id, settings: {key1: val1_or_redacted, key2: ...}}` retained for debuggability.
- `redacted` field lists JSONPath keys redacted.

**Rotation**: at 10 MB → `audit.jsonl` → `audit.1.jsonl`, ..., `audit.5.jsonl` (oldest dropped). Total disk budget ~60 MB.

**Querying**: `/audit [count=20] [event_type=...]` Telegram command. `default.py` status panel shows recent entries with filter UI.

### 5.4 Snapshot system

**Location**: `special://userdata/Kodi-AI-snapshots/` (outside addon dir → survives addon reinstall).

Each snapshot: directory `<snapshot_id>/`:
- `manifest.json` — SnapshotTarget list with kind/identifier/snapshotted_value/equality_fn_name/read_back_fn_name (function names re-resolved on undo).
- `files/` — copies of file targets.
- `metadata.json` — session_id, tool_name, created_at, label.

**Retention**: LRU max 100 snapshots OR 200 MB whichever first. Oldest deleted.

**Undo**: snapshot moved to `Kodi-AI-snapshots/.undone/` (kept 24 h for redo).

**Boot recovery**: orphan snapshots (no matching session in `sessions/*.json` and no audit entry within 7 days) → `Kodi-AI-snapshots/.orphaned/` for manual review.

**Staleness validation** (§ 1.13): on restore, each target's `read_back()` (2 s deadline) compared via `equality(current, snapshotted)`. Timeout OR mismatch → STALE → refuse auto-restore → Telegram `[Show diff] [Force restore] [Cancel]`.

GC runs on T4 boot pass + every 24 h during idle.

### 5.5 Budget management

**Three caps (V1 defaults, user-configurable):**

| Cap | Default | Reset |
|---|---|---|
| Per-incident hard cap | $0.50 | At session start (per reasoner run) |
| Daily cap | $5 | User-configured wall-clock (default 00:00 UTC; user can set IANA timezone) |
| Monthly cap | $30 | Calendar month boundary |

**Per-incident enforcement (3 points)**:
1. **Pre-call**: estimate `tokens_in_estimate * input_price + max_tokens * output_price`. If `current + estimate > cap` → refuse `ToolResult(error="per-incident budget would be exceeded")`.
2. **Mid-stream**: in streaming `iter_lines()` loop, check `current + (tokens_streamed_so_far * output_price) > cap`. If exceeded → `r.raw.close(); r.close()`; discard partial JSON; emit synthetic well-formed envelope `{"role": "tool", "tool_call_id": current_id, "content": {"error": "budget_truncated", "tokens_streamed": N, "estimated_cost_so_far": "$X.XX"}}`. Reasoner processes as clean tool error → routes to pause-and-notify.
3. **Post-call**: safety-net check.

NO 10% headroom — trip exactly at 100% of `per_incident_hard_cap`.

**Daily/monthly enforcement**: counters persisted to `addon_data/budget_counters.json` after every LLM call. On cap hit → refuse new tool-using reasoner runs; chat falls back to advisory-only (read-only tools allowed).

**Cost source**: `cost_usd = (tokens_in * input_price + tokens_out * output_price) / 1_000_000`. Prices from `recommended_models.json` per model. User-overridable.

**Telegram commands**: `/budget` (show counters), `/budget raise daily 10` (temporary daily raise), `/budget reset incident`.

### 5.6 Prompt versioning

Each prompt file (`lib/llm/prompts/*.md`) has frontmatter:
```markdown
---
prompt_name: triage_system
prompt_version: 1.0.0
---
[body]
```

`prompt_hash = sha256(file_contents_with_prompt_hash_line_stripped_if_present)`. Computed once at startup, cached.

Audit log `llm_call` entries record both `prompt_version` and `prompt_hash`. Behavior regression after prompt update → grep audit log for prompt_hash diff.

### 5.7 Kill switches + recovery

| Command | Behavior |
|---|---|
| `/pause [minutes=60]` | Pauses background log monitoring. T2 still polls (no gap on resume) but doesn't enqueue LogIncidents. ResumeWork + UserMsg still process. Confirmation: "Paused N min. /resume to unpause early." |
| `/resume` | Undoes /pause immediately. |
| `/disable` | Disables ALL auto-fix (immediate AND confirm). Reasoner enters advisory-only mode: read-only tools + notify_user, no `tier ∈ {immediate, confirm}` execution. Persisted to `addon_data/disabled.flag`. |
| `/enable` | Re-enables auto-fix. |
| **`/panic`** | Emergency stop. Sequence: (1) abort any in-flight reasoner. (2) Set `abort_event` for current session only. (3) Validate ALL session snapshots via `read_back + equality`: fresh → auto-restore; stale → list with per-snapshot `[Force restore <fix_id>] [Skip <fix_id>]` buttons (default action on 5-min inactivity = SKIP). (4) On `pause_notify_failed` during stale-snapshot confirmation: fail-safe = SKIP ALL stale + log LOGERROR + persist `addon_data/panic_state.json` + surface via `/status` on next Telegram-up. (5) Persist `disabled.flag` (auto-fix off until manual `/enable`). (6) Telegram "Panic stop applied. Session aborted. Fresh snapshots restored; stale skipped (review via /status). Auto-fix DISABLED until /enable." |
| `/status` | Full status: budget remaining, recent fixes, paused sessions, model availability, last 10 audit entries, /pause /disable state, pending notify_failed sessions, panic_state.json contents if present. |
| `/undo <fix_id>` or `/undo` | Restore from snapshot. Staleness validation. |

**Kodi addon settings UI** also exposes: Reset bot owner, View setup secret, View status, Disable/Enable auto-fix. (Escape hatch if Telegram broken.)

/panic Telegram-only in V1 (no filesystem trigger).

### 5.8 Data redaction policy

**Sent to LLM (after redaction)**: redacted log lines, redacted tool outputs, redacted user Telegram messages, static system prompts, recent audit entries when explicitly requested.

**NEVER sent to LLM**: raw bot_token or openrouter_key (filtered by redactor); other addons' secret-key VALUES (per `known_secret_keys.json` ∪ heuristic); auth headers from HTTP responses; user's raw chat_id (only `chat_id_hash`); filesystem paths outside `special://profile/`/`userdata/`/`temp/`.

**Redactor patterns** (`lib/redactor.py`):
- Telegram bot token: `^[0-9]{8,12}:[A-Za-z0-9_-]{30,}$`.
- OpenAI/Anthropic key: `^sk-[A-Za-z0-9-]{20,}$`.
- OpenRouter key: `^sk-or-[A-Za-z0-9-]{20,}$`.
- `(?i)Authorization:.*` → `Authorization: <redacted>`.
- `(?i)Set-Cookie:.*` → `Set-Cookie: <redacted>`.
- Basic-auth URLs: `https?://[^:/]+:[^@/]+@` → `https?://<redacted-creds>@`.
- JWT: `eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` → `<redacted-jwt>`.
- `Bearer\s+[A-Za-z0-9._-]{20,}` → `Bearer <redacted>`.
- URL token query patterns (`token=...`, `apikey=...`, `key=...`).
- Real-Debrid / AllDebrid / Premiumize known patterns.

**Known-secret-key heuristic** (default-deny): in addition to `known_secret_keys.json`, any addon setting key matching `(?i).*(token|secret|password|api_?key|cookie|auth).*` is treated as known-secret. Heuristic only redacts **string-typed** values (booleans/integers matching the regex are NOT redacted — e.g., `cookie_consent_shown=true`, `password_min_length=8`).

Use `type(v) is bool` BEFORE `isinstance(v, int)` for type gate (bool is int subclass).

**`allow_list`** (explicit non-secret keys): `resources/data/redaction_allowlist.json` + user-extensible via Kodi setting `redaction_allowlist_extra` (CSV) under Safety category. Semantics: `effective = builtin ∪ user_extra`. V1 seeds: `auth_method, cookie_consent_*, password_min_length, api_key_required, *_url`.

**Canary self-test**: every 100 redactions, run on test string with known patterns. On any leak → disable LLM calls + notify user via Telegram + Kodi toast.

**On redactor regex failure** (pattern detected but redaction failed): drop the field entirely from LLM input rather than send raw.

### 5.9 log_capture stderr wrapper

At addon startup: install Python `logging.Handler` on root logger; install `sys.stderr` and `sys.stdout` wrappers that prepend `[service.kodi.ai] ` and forward to `xbmc.log`. Origin metadata (`record._kodi_ai_origin = threading.get_ident()`) attached.

Thread-local `_in_handler = threading.local()` prevents recursion: handler bypasses if already inside itself.

Captures stdlib `logging` from `requests`/`urllib3`/etc. Buffer stderr until newline, then emit one `xbmc.log` call. Filters duplicate messages within 1 s (dedupe library retry loops).

**T3-vs-T4 distinguishing**: T2's suppression rules check origin metadata for T4-thread-only suppression during active windows. T3's network errors during reasoner sessions are NOT suppressed.

**Limitation documented**: native C/C++ extensions writing directly to `fd 2` syscall (e.g. `lxml`, `cryptography`) bypass our `sys.stderr` wrapper. Optional `os.dup2` redirect of fd 2 → pipe → reader-thread-with-prefix deferred to V2 unless concrete miss observed.

### 5.10 Defense-in-depth summary

Secrets redacted at every boundary (LLM input + audit log). Setup-secret prevents bot hijack. Budget caps at 3 levels (per-incident hard, daily, monthly). Kill switches give user immediate control. Snapshot retention LRU + orphan recovery + reinstall-safe location. Audit log with rotation + per-event redaction. Prompt versioning enables behavior regression debugging. Redactor self-test detects silent regression.

---

## § 6 — Testing & Acceptance

### 6.1 Strategy

Three test surfaces (ordered by speed + frequency):
1. **Unit tests** (pure modules, dev machine) — `pytest`. Coverage target: 80% on pure modules. No coverage target for Kodi-touching code (manual acceptance is source of truth).
2. **Integration tests** (kodistubs + fakes for `xbmc`/`xbmcgui`/`xbmcvfs`/`xbmcaddon`/`Monitor`/JSON-RPC).
3. **Live Kodi acceptance** on Shield Pro. Manual + scripted-input harness.

V1 personal use: no CI required. Pre-commit hook runs `pytest tests/unit tests/integration` (15 min total). Acceptance scenarios run pre-release.

V2: GitHub Actions for #1+#2 in container with kodistubs; manual acceptance still on real device.

### 6.2 Unit tests (pure modules)

Pure modules from § 2:
- `lib/prefilter.py`, `lib/triage.py`, `lib/reasoner.py`, `lib/reasoner_state.py`, `lib/concurrency.py`, `lib/llm/{client,router,budget}.py`, `lib/redactor.py`, `lib/telegram/{bot,formatters}.py`, `lib/tools/extract_keys.py`, `lib/qr.py`, `lib/health.py`, `lib/audit_log.py`.

**Mocks**:
- `requests.Session` via `responses` library.
- LLM API fixtures: JSON in `tests/fixtures/llm_responses/`.
- Telegram fixtures similarly.
- Time mocked via `freezegun` for budget rollover + MonotonicBudget state transitions.
- `threading.Event`/`queue.PriorityQueue` exercised in real Python.

**Specific test plans (parked items folded in):**
- **Confirm-prompt FSM**: state transitions `pending→confirmed→executing→verified→complete`, `pending→rejected`, `executing→failed→complete`, `confirmed→aborted` (budget exhausted). TTL expiry. Callback routing. MonotonicBudget pause/resume integration.
- **Audit log writer**: JSONL serialization with `redacted: list[str]`, rotation at 10 MB × 5 files, atomic writes.
- **verify_fix polling**: per-strategy cadence, abort_event interruptibility, max-attempt limits, cleanup.
- **Tool dispatcher**: schema validation, JSON-RPC allowlist enforcement, arg validation, tier/disruptive classification.
- **Cost attribution**: BudgetGuard cost math matches OpenRouter response payload shape.

**Fixture layout:**
```
tests/
├── unit/test_*.py
├── integration/test_*.py
└── fixtures/
    ├── kodi_log_samples/                 # synthetic kodi.log lines
    │   ├── dep_import_error.log
    │   ├── repo_404.log
    │   ├── playback_fail_seren.log
    │   ├── benign_warnings.log           # noise → IGNORE
    │   ├── trace_continuation.log
    │   ├── mixed_addon_interleaving.log
    │   ├── burst_spam.log
    │   ├── sentinel_bracketed.log
    │   └── dangling_sentinels.log
    ├── llm_responses/
    │   ├── triage_critical.json / advisory.json / ignore.json
    │   ├── reasoner_set_setting.json
    │   ├── streaming_chunks.txt
    │   └── ...
    ├── telegram/ (callback_query, message_text, reply_to_message payloads)
    ├── snapshots/ (settings_xml_flat.xml, advancedsettings_nested.xml, sources_xml_multiple.xml)
    ├── addon_data_state/ (addons.xml, settings.xml, sources.xml)
    └── LICENSES.md
```

### 6.3 Integration tests (kodistubs)

`kodistubs` as dev dep (community-maintained Python stubs for `xbmc`/`xbmcgui`/`xbmcvfs`/`xbmcaddon`).

```
tests/integration/
├── conftest.py                  # kodistubs setup, fake registries via sys.modules['xbmc']=...
└── fakes/
    ├── fake_xbmcvfs.py          # in-memory FS with growable files, simulated rotation
    ├── fake_xbmc.py             # fake log + executebuiltin + Monitor (with abort signal)
    ├── fake_addon.py            # fake xbmcaddon.Addon(...) returning strings always
    └── fake_jsonrpc.py          # JSON-RPC backend with addon state
```

**Specific surfaces tested:**
- `lib/log_watcher.py` (T2): synthetic file growth, polling cadence, 3-signal rotation, burst-mode, post-mortem boot pass, per-tool-boundary buffer evaluation.
- `lib/log_capture.py`: prefix injection + thread-local recursion guard + origin metadata distinguishing T3 vs T4.
- `lib/snapshot_manager.py`: file copies + read_back + equality + staleness detection + orphan recovery on boot.
- `lib/tools/kodi_addons.py`: executebuiltin call format + JSON-RPC verification readback.
- `lib/tools/kodi_settings.py`: enabled vs disabled path for `set_addon_setting`.
- `lib/tools/kodi_jsonrpc.py`: allowlist enforcement (assert non-allowlisted → blocked).
- **Telegram 429 + Retry-After**: mock Telegram returns 429+header; verify backoff + abort_event interruptibility.
- **Session resume mid-write recovery**: simulate truncated `.tmp` (`{"id":"abc","steps":[`); T4 boot pass discards, falls back to last clean `.json`.
- **xbmc.Monitor abort-signal**: fake Monitor returns `abortRequested=True` after N ticks; verify each long-running loop (T2 poll, T3 long-poll, T4 work_queue.get, reasoner agent loop, verifier polling, notifier retry, slug-validation HTTP) exits within documented join window.
- **Slug validation**: mock `/api/v1/models` with missing slugs; verify deferred Telegram notification + `/status` surfacing.

### 6.4 Live acceptance scenarios (Shield Pro)

**Release gate: all 8 scenarios pass over 3 consecutive runs.**

Each scenario:
1. Reset to known-good state via `tests/acceptance/snapshot_kodi.sh restore` (with safety gates).
2. Inject failure condition manually.
3. Trigger user action.
4. Observe AI response (Telegram + audit log + Kodi log).
5. Verify expected outcome.
6. Restore.

**(a) Add-on dep/import errors:**
- **A1** Missing module reinstall — delete `__pycache__` + uninstall `script.module.requests`, trigger Seren. Expect: AI detects ImportError → `install_addon("script.module.requests")` → verifies → notifies.
- **A2** Disabled-dep re-enable — disable a script.module dep, trigger dependent addon. Expect: AI detects via `list_addons(enabled=None)` → `enable_addon` from confirm → verifies → notifies.
- **A3** Stale `.pyc` after addon update — replace addon `.py` with known-incompatible version, keep `.pyc` cache. Expect: AI detects ImportError → `clear_addon_cache(addon_id)` (purges __pycache__ + restarts) → verifies clean import → notifies.

**(b) Repo unreachable / update failures:**
- **B1** Repo URL returns 404 — dev-controlled HTTP server (`tests/acceptance/dev_server.py`) with `/dead/addons.xml → 404`. Test addon points at this URL. Trigger `update_addon`. Expect: AI detects → `http_get` confirms dead → Telegram with manual install instructions → `verify_fix(repo_unreachable)` polling. After 5 min, restore URL; verify_fix detects recovery → retries update → notifies success.
- **B2** Partial repo (missing addon in manifest) — test repo with manifest missing one expected addon. Expect: AI detects "addon not in repo" → notifies user with alternative suggestions.

**(c) Stream playback failures:**
- **C1** Source dead — Seren-like addon with configured source returning 404. Tap Play. Expect: AI detects playback fail → `get_addon_setting` resolvers → swaps default resolver via confirm → verifies via `Player.OnPlay` polling.
- **C2** Codec issue — toggle `videoplayer.usemediacodec=false` via Kodi UI (Settings → Player → Videos → Allow Hardware Acceleration → MediaCodec). Play HEVC video (bundled fixture `tests/acceptance/fixtures/hevc_hw_required.mkv`, ~10 MB CC-BY clip). Expect: AI detects decode error → suggests re-enabling via confirm.
- **C3** Stream addon hangs — 30 s timeout after Play attempt for `Player.OnPlay`. No event + no log progress → categorized as hang → AI triggers `restart_addon` (disruptive=True since playback attempt active → confirm flow).
- **C4** Geo-block — dev server returns HTTP 403 with `Content-Region: US` header. Test addon hits this endpoint. Expect: AI detects 403/region → notifies advisory-only "Source geo-restricted (US-only). VPN or alternate source needed." NO auto-fix.

**Out of V1**: C5 auth-token-expired (Trakt/RD/AllDebrid) — V2.

### 6.5 Smoke tests at startup

Before T2/T3 begin polling:
- **State directory existence**: ensure `addon_data/`, `sessions/`, `snapshots/` (under userdata), `audit/` all exist + writable. Create if missing. Fail → log ERROR + halt addon startup (cannot proceed). **Hard fatal**.
- **Atomic-rename probe**: write to `.smoke/probe.tmp`, fsync, rename to `.smoke/probe`. Verify content. Fail → log ERROR + Telegram toast "Atomic-rename test failed; state persistence may be unsafe." Continue with degraded mode.
- **Redactor canary** (§ 5.8): run on test string with known secrets. Fail → disable LLM calls + notify. **Hard fatal**.
- **log_capture canary**: emit test through stderr wrapper, verify appears in `kodi.log` with prefix. Fail → log ERROR + fallback to direct `xbmc.log` only.
- **OpenRouter slug validation** (§ 4.5): ping `/api/v1/models` with 10 s + 1 retry. On miss → deferred Telegram notification post-/start.
- **Telegram bot_token validity**: `getMe` call at startup with 5 s timeout. Bad → log ERROR + Kodi toast + halt T3 startup. **Run BEFORE T3 sets `startup_complete_event`**.
- **Telegram chat_id reachability**: once allowlist established, send hidden "startup OK" `sendMessage(disable_notification=true)`. On 400/403 → log ERROR + Kodi toast. **Run BEFORE startup_complete_event**.
- **Disk-space check**: `<50 MB free → log WARNING + Kodi toast.
- **Clock-skew check**: compare `time.time()` against HTTPS Date from openrouter.ai. `>1h skew → log WARNING.

Probe failures and ordering: probes run inside T3 init, **before** `startup_complete_event.set()`. Probe fail → event never set → supervisor sees T3 dead → graceful shutdown.

### 6.6 Manual acceptance on Shield Pro

User-driven protocol:
1. **First install**: end-to-end QR-code setup (scan QR with phone, Telegram opens, `/start` fires, bot welcomes).
2. **Baseline 24 h**: run with defaults during normal Kodi usage. Audit log: minimal idle LLM calls, triage fires only on real ERROR clusters, no spurious fixes.
3. **Acceptance scenarios (§ 6.4)**: all 8 pass over a weekend.
4. **Stress test**: dummy addon that calls `xbmc.log` in a tight loop (synthetic log burst). Verify burst-mode skip-to-tail fires, drop_counter increments, user notified.
5. **Shutdown discipline**: `adb shell am force-stop org.xbmc.kodi` mid-reasoner-run. Verify session_id appears in `sessions/*.json` on next start, "Resumed after restart" Telegram arrives, MonotonicBudget rehydrates.
6. **Budget cap**: set per-incident cap to $0.01, trigger complex incident. Verify mid-stream truncation fires with clean envelope + user notification.
7. **/panic**: trigger /panic mid-reasoner-run. Verify session aborts + snapshots restored (fresh) or skipped (stale, default action) + Telegram confirmation + addon disabled state.

### 6.7 Test infrastructure

`tests/acceptance/snapshot_kodi.sh` with safety gate:
- Requires `KODI_AI_TEST_DEVICE=1` env var OR `--i-understand-this-wipes-userdata` flag.
- Restore auto-creates `pre_restore_<timestamp>.tar.gz` first.
- README header: bold "TEST DEVICES ONLY".
- Commands: `adb shell tar czf /sdcard/Download/clean.tar.gz -C /sdcard/Android/data/org.xbmc.kodi/files/.kodi userdata/`; restore: `adb shell am force-stop org.xbmc.kodi` then extract.

`tests/acceptance/dev_server.py`: tiny Flask/`http.server` with routes for B1 (`/dead/addons.xml`) + C4 (`/geo/blocked`).

### 6.8 Regression approach

V1 personal: pre-commit hook → `pytest tests/unit tests/integration`. Acceptance pre-release.

V2: GitHub Actions (unit+integration in kodistubs container); manual acceptance on real device.

---

## § 7 — Setup, Configuration, Distribution

### 7.1 V1 distribution model

GitHub-Pages-hosted non-official repo (user-controlled) from day 1, even though V1 is personal use — keeps install flow native and primes for V2 expansion.

```
kodi-ai-repo/                            # GitHub Pages repo root
├── .nojekyll                            # disable Jekyll, expose dirs
├── index.html                           # explicit listing (belt-and-braces)
├── repository.kodi-ai-1.0.0.zip
├── addons.xml
├── addons.xml.md5
└── zips/
    ├── repository.kodi-ai/
    │   ├── repository.kodi-ai-1.0.0.zip
    │   ├── icon.png, fanart.jpg
    │   └── changelog-1.0.0.txt
    └── service.kodi.ai/
        ├── service.kodi.ai-0.1.0.zip    # current
        ├── service.kodi.ai-0.0.9.zip    # one prior (rollback)
        ├── icon.png, fanart.jpg
        └── changelog-0.1.0.txt
```

**`repository.kodi-ai` manifest** (installer add-on):
```xml
<addon id="repository.kodi-ai" name="Kodi-AI Repository" version="1.0.0" provider-name="ivan">
  <extension point="xbmc.addon.repository">
    <dir>
      <info compressed="false">https://<user>.github.io/kodi-ai-repo/addons.xml</info>
      <checksum>https://<user>.github.io/kodi-ai-repo/addons.xml.md5</checksum>
      <datadir zip="true">https://<user>.github.io/kodi-ai-repo/zips/</datadir>
      <hashes>sha256</hashes>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary>Kodi-AI repository</summary>
    <platform>all</platform>
  </extension>
</addon>
```

**`service.kodi.ai` manifest:**
```xml
<addon id="service.kodi.ai" name="Kodi-AI" version="0.1.0" provider-name="ivan">
  <requires>
    <import addon="xbmc.python" version="3.0.1"/>
    <import addon="script.module.requests" version="<VERIFY_AT_RELEASE>"/>
  </requires>
  <extension point="xbmc.service" library="service.py" start="login"/>
  <extension point="xbmc.python.script" library="default.py">
    <provides>executable</provides>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">AI-assisted Kodi diagnostics + auto-fix</summary>
    <description lang="en_GB">...</description>
    <platform>all</platform>
    <news>0.1.0: initial V1 release.</news>
  </extension>
</addon>
```

`script.module.requests` version pinned to whatever Kodi 21 Omega official repo ships at release time. CI step in V2 re-verifies on each addon release.

### 7.2 First-run installation flow

Total time ~10 min including BotFather + OpenRouter signups.

**Step 0 prerequisites:**
- (a) Install Kore (Android) / Official Kodi Remote (iOS) on phone; pair with Kodi via "Allow remote control via HTTP" (Kodi → Settings → Services → Control). Phone keyboard mandatory for pasting 50-char keys.
- (b) Install Telegram on phone (or modern browser for t.me web fallback).
- (c) Toggle "Unknown sources" ON in Kodi (Settings → System → Add-ons).
- (d) Enable "Allow remote control via HTTP".

**Step 1 — Add the repo source:** Settings → File manager → Add source. URL: `https://<user>.github.io/kodi-ai-repo/zips/repository.kodi-ai/`. Name: "kodi-ai". (Browse directly into the dir containing the repo ZIP — `.nojekyll` ensures Pages serves it.)

**Step 2 — Install repository ZIP:** Settings → Add-ons → Install from zip file → "kodi-ai" source → `repository.kodi-ai-1.0.0.zip`. Wait for "installed" toast.

**Step 3 — Install the add-on:** Settings → Add-ons → Install from repository → "Kodi-AI Repository" → Services → "Kodi-AI" → Install. Service starts automatically.

**Step 4 — First-run wizard** (`default.py`, multi-screen Kodi dialog):

- **Screen 1 — OpenRouter key.** Explanation + sign-up link. Input field for `openrouter_key`. Pre-flight validation: HTTP request to `/api/v1/models` with key → reject 401 with "Invalid key, check + re-paste"; on success, tiny test call to `DEFAULT_PREFLIGHT_MODEL` (cheapest paid, ~$0.0001) with progress message "Verifying key with $0.0001 test call to <model_id>..." On 402 "OpenRouter account has no credit. Add ~$5 at openrouter.ai/account/credits, then retry." On 5xx/network "OpenRouter unreachable. Check network/proxy; setup continues but key cannot be verified."
- **Screen 2 — Telegram bot setup.** Instructions: "Open Telegram → @BotFather → `/newbot` → name + username → copy bot token. Then `/setprivacy → Disable` (fine for DM-only)." Input fields `bot_token`, `bot_username`. Validate via `getMe`.
- **Screen 3 — Owner linking via QR code.** Display QR (≥40% screen width, error-correction H, high-contrast) encoding `https://t.me/<bot_username>?start=<setup_secret>`. "Scan with phone camera or open Telegram and DM the bot `/start <secret>`." Wizard polls `health.json::allowlist_populated_at` every 1 s with 60 s total timeout. Status text: "Waiting for `/start` from your bot... (X s elapsed)." On flag set: enable Screen 5. On timeout: "Didn't receive `/start`. [Re-show QR] [Show plain-text fallback] [Cancel]." Fallback button shows plain-text secret + bot URL.
- **Screen 4 — Mode selection.** Default = Automatic. "Automatic (recommended): system picks the model per task. Cheap for triage, stronger for hard fixes. ~$1-5/month typical." "Manual: you pick one model for everything."
- **Screen 5 — Test fire + done.** Once allowlist populated: "Send a test message to your bot to verify reachability." User DMs anything; bot replies "✅ Test received — Kodi-AI ready." On success → declare setup complete.

### 7.3 Settings UI (`resources/settings.xml`)

**Categories:**
- **General**: master `enabled` toggle (kill switch), `openrouter_key` (password), `mode` (auto/manual), `manual_model` (dropdown when mode=manual).
- **Telegram**: `bot_token` (password), `bot_username`, [Reset bot owner] action, [Show setup secret] action, allowlist viewer (with remove buttons), `/invite <secret>` Telegram command shape (V2-prepped).
- **Budget**: `per_incident_cap` ($), `daily_cap` ($), `monthly_cap` ($), `reset_time_local` (HH:MM), `timezone` (IANA dropdown, auto-detected with manual override), `models_override` (JSON blob — advanced).
- **Safety**: `redaction_allowlist_extra` (CSV).
- **Advanced**: `triage_rate_per_min` override, `t2_poll_cadence_ms` override, snapshot retention overrides (max count, max MB), HTTP proxy host/port (no creds), `diagnostic_logging` toggle (DEBUG-level capture + more audit detail), `/pause` quick action (Pause monitoring for 1h/4h/8h/until tomorrow + Apply), Export config (ZIP, no secrets), Import config.
- **Status** (read-only): budget remaining, last fix timestamp, active sessions count, audit log size, model availability summary.

### 7.4 Self-update fallback (LKG)

**`lib/recovery.py`**: writes `last_known_good-<version>.zip` (real ZIP, DEFLATE compression, NOT tarball) to `special://userdata/Kodi-AI-recovery/`. zinfo paths prefixed with `service.kodi.ai/` (top-level addon dir required by Kodi's installer). Keep last 2 versions.

**Rotation gate** (`lib/recovery.py`): rotate only after `(time.time() - crash_free_since) >= 86400 AND telegram_last_rt_ok_ts > 0`. Both required.

**Crash detection** (`lib/health.py`):
- T4 main loop writes `last_alive_ts = time.time()` to `addon_data/health.json` every 5 min between `work_queue.get` calls.
- `health.json` schema:
  ```json
  {
    "last_alive_ts": float,
    "crash_free_since": float,
    "telegram_last_rt_ok_ts": float,
    "allowlist_populated_at": float | null,
    "last_clean_shutdown_ts": float | null
  }
  ```
- `last_clean_shutdown_ts` written by T4's abort-handler in `service.py` (synchronously, BEFORE pushing `None` sentinels + joins).
- Boot pass: compare `last_clean_shutdown_ts` vs previous `last_alive_ts`. **Clean if delta ≤ heartbeat_interval (5 min) + 30 s grace** (handles long power-off correctly). Else → crash inferred → `crash_free_since = time.time()`.

**Recovery flow** (if a future update bricks the add-on):
1. User boots Kodi.
2. Service silently fails or logs ImportError.
3. User opens File manager → kodi-ai source → "Install from zip file" pointing at LKG `.zip`.
4. Service restarts on prior good version.

LKG path documented in `addon_data/recovery/manual_reinstall_instructions.txt` for users to find via ADB.

### 7.5 Kodi-version compat probe

On startup (T4 boot pass before `startup_complete_event`):
1. Read `xbmc.getInfoLabel('System.BuildVersion')` → e.g. `"21.3 (21.3.0) Git:..."`.
2. Parse `major.minor` (tolerate non-numeric suffixes like `"22.0-ALPHA1"`).
3. Compat table (`resources/data/compat.json`):
   - 21.x → SUPPORTED.
   - 20.x → WARN ("Kodi 20 Nexus not officially supported").
   - <20 → REFUSE (log ERROR + halt startup + Kodi toast "Kodi-AI requires Kodi 21+").
   - 22.x → WARN ("Kodi 22 Piers in development; please report issues") + load anyway.
4. Additionally on Android: query `System.Platform.Android`; check Android API level (≥24 required) via system reflection if accessible; warn if older.
5. On WARN: addon proceeds + surfaces warning via `/status`.

### 7.6 V1 → V2 distribution path

**V1 user updates**: push new version to GitHub Pages → Kodi auto-checks daily → user sees "update available" notification → installs.

**V1 → V2 expansion**:
- Add tester users by sharing repo URL. Each tester repeats § 7.2.
- Eventually: switch per-user OpenRouter keys to **hosted relay** (Approach B from initial brainstorming). Single OpenRouter account, per-user auth tokens. Requires own design pass.
- If "Kodi-AI" name is taken in official repo, ship under user's namespace (`service.<user>.kodi.ai`).

**V2 → official Kodi repo (optional)**: requires open source, passes Team Kodi review (manual). Adds trust signal but Team Kodi may reject "general LLM agent" pattern as too risky.

**Hosted relay V2 liability**: you become OpenRouter spend bearer + GDPR data-processor for testers' data. Requires own design pass, ToS, privacy policy, possibly LLC formation. Not part of V1.

### 7.7 Recovery / disaster scenarios

| Scenario | Response |
|---|---|
| Add-on won't start (import error after update) | LKG `.zip` recovery (§ 7.4). |
| OpenRouter key revoked (401) | Detect → Kodi toast + `/status` shows error; Telegram still works for `/budget`, `/disable`; user enters new key via Kodi settings. |
| OpenRouter outage (5xx) | Degraded mode (no LLM calls); chat falls back to "AI unreachable, retry 5 min" toast; resume on health check. |
| Telegram bot deleted in BotFather | Detect 404 on `getMe` next startup; halt T3; `/status` surfaces error; user creates new bot, pastes new token, re-links via QR. |
| Telegram network blocked | Repeated `getUpdates` timeout/connect-refused → Kodi-toast-only fallback; user alerted to check network/proxy. |
| Clock skew | NTP-presence check at startup via HTTPS Date header from openrouter.ai; `>1h skew → Kodi toast "System clock skewed; TLS may fail." |
| Storage full | Pre-check before snapshot/audit/sessions write; <50 MB free → refuse mutations + Telegram alert. |
| All snapshots lost | Existing tools warn user that undo is unavailable for affected sessions; no auto-fixes applied without snapshot (HARD RULE). |
| Repo URL hijacked | `addons.xml.md5` mismatch (Kodi built-in) prevents tampered installs; user alerted via `/status`. |
| User uninstalls add-on then reinstalls | `addon_data/` persists. Snapshots under `Kodi-AI-snapshots/` persist (outside addon dir). Setup wizard re-runs if `secrets.json` missing. Documented. |

**ADB-level recovery (first-class doc)**: if add-on bricks Kodi, `adb shell rm -rf /sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/service.kodi.ai/`, restart Kodi. State in `addon_data/` survives for reinstall.

### 7.8 Documentation deliverables

- **README.md** (repo root + `service.kodi.ai/resources/README.md`): install steps, setup wizard description, Telegram commands reference, troubleshooting.
- **CHANGELOG.md**: per-version changes (manual).
- **PRIVACY.md**: what's sent to OpenRouter (redacted log lines, settings keys but not values for secrets); what's local (audit log, snapshots); retention; **explicit mention that Telegram chat history persists on Telegram servers indefinitely — out of our control**.
- **SECURITY.md**: trust model (Unknown sources, no signing), recovery scenarios, snapshot integrity.
- **UNINSTALL.md**: manual purge of `addon_data/` + `Kodi-AI-snapshots/` for clean removal.
- **LICENSE**: MIT or Apache 2.0 (user picks).
- **THIRD_PARTY_NOTICES**: `requests`, `kodistubs`, any other bundled module.

---

## Appendix A — Locked Product Decisions

| Decision | Value |
|---|---|
| V1 audience | Personal (project owner) only |
| Primary device | Nvidia Shield Pro (Android TV) |
| Distribution model | Standard Kodi non-official repo (GitHub Pages) |
| AI provider | OpenRouter (Auto + Manual modes, Auto default) |
| Primary interface | Telegram bot (long-poll, no webhooks) |
| Agent style | General LLM tool-use with custom tool catalog |
| Trigger model | Proactive continuous log monitoring with triage |
| V1 acceptance scope | dep/import errors, repo unreachable, playback failures |

## Appendix B — Parked for V2

| Item | Why deferred |
|---|---|
| Auth-token expiry (Trakt/RD/AllDebrid) | User explicitly excluded from V1 acceptance |
| Config automation (skins/menus/widgets/builds) | "Interesting but not the main fundamental goal" — V2 |
| Hosted relay for OpenRouter | Requires ToS + privacy policy + spend bearer — separate design pass |
| Multi-chat `/invite` for Telegram | V1 single-user; settings UI already V2-shaped |
| TCP socket listener for JSON-RPC notifications (Player.OnPlay etc.) | V1 polls every 1 s instead |
| `os.dup2` fd 2 redirect for native C extension stderr | Documented limitation; defer unless concrete miss observed |
| Real `install_repository_from_zip` tool | Requires Unknown sources toggle + per-step user confirmation flow |
| GitHub Actions CI with kodistubs container | V1 pre-commit local; V2 server |
| i18n (currently `en_GB` only) | V1 personal use |
| `models_override` per-task class advanced UI | V1 has JSON blob; V2 dedicated UI |

## Appendix C — Verified Kodi Facts (2026)

- **Kodi 21 Omega** stable, `xbmc.python` 3.0.1. Kodi 22 "Piers" in dev.
- **No reliable asyncio** in Kodi's embedded CPython.
- Canonical service pattern: `monitor = xbmc.Monitor(); while not monitor.abortRequested(): if monitor.waitForAbort(n): break`.
- Log: `special://logpath/kodi.log`; rotates to `kodi.old.log` on Kodi startup. Android: `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/`.
- `xbmcvfs.File` is SAF-backed on Android — no blocking-on-growth; poll via `xbmcvfs.Stat()`. `st_ino` may be absent on SAF.
- `special://profile/` resolves to addon's POSIX-backed app-private dir on Android.
- `xbmc.log(msg, level)` adds `[addon_id]` prefix; **buffered** — NOT safe as control channel.
- `xbmc.executebuiltin` fire-and-forget; `xbmc.executeJSONRPC` synchronous.
- `xbmc.executebuiltin('InstallAddon(<id>)')` installs from already-installed repo. **NO first-class API to add new repository URL** — user (or repo ZIP install) must drop `repository.*` add-on file in place.
- `script.module.requests` bundled (version pinned at release).
- Telegram Bot API limits: 4096-char messages; 48 h edit window on sent messages.
- JSON-RPC `System.GetProperties` with `["uptime"]` returns integer seconds.

---

**End of design spec.** Ready for `writing-plans` skill handoff.
