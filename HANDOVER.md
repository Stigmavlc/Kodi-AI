# Kodi-AI V1 — Session Handover

**Last updated:** 2026-05-27 (end of session: design + plan + Phase 0 execution)
**Project root:** `/Users/ivan/Desktop/Web Development  Projects/Completed By Me/Kodi-AI/`
**Git branch:** `main`
**Latest commit:** `94e65a9` (test: pytest smoke test + pre-commit hook)

This document tracks **exactly what's left to implement**, by phase and by task, so any future session can pick up cleanly. It is read by the `/load-context` slash command at session start and updated by `/save-context` at session end.

---

## Section 1 — Quick start for a new session

In a fresh Claude Code session in this directory:

1. Run `/load-context` — auto-loads spec, plan, MEMORY, this HANDOVER, and CLAUDE.md.
2. Verify discipline rules are active: every code task dispatches a fresh Opus 4.7 implementer subagent + fresh Opus 4.7 spec reviewer + fresh Opus 4.7 code-quality reviewer. ALL agent dispatches use `model: "opus"` explicitly.
3. Resume execution at the **next pending task** (see Section 3 below). Use `superpowers:subagent-driven-development` (preferred for fidelity) or `superpowers:executing-plans` (faster, lower fidelity).
4. At end of session, run `/save-context` to update this HANDOVER + Project_Master_and_changelog.md.

---

## Section 2 — Locked artifacts (don't redo)

| Artifact | Path | Lines | Status |
|---|---|---|---|
| Design spec | `docs/superpowers/specs/2026-05-26-kodi-ai-design.md` | 1452 | ✅ Locked (22 Opus 4.7 reviewer rounds across 7 sections) |
| Implementation plan | `docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md` | 9854 | ✅ Locked (3 Opus 4.7 reviewer rounds; round-3 verdict CLEAN) |
| Project log | `Project_Master_and_changelog.md` | — | Updated each session |
| This handover | `HANDOVER.md` | — | Updated each session via `/save-context` |
| Project memory | `CLAUDE.md` | — | Auto-loaded by Claude in this dir |
| MEMORY index | `/Users/ivan/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/MEMORY.md` | — | Memory feedback for discipline rules |

---

## Section 3 — Task status (65 tasks across 13 phases — 3 done, 62 pending)

Status legend: `✅ done` / `🚧 in-progress` / `⏸ pending` / `⛔ blocked`.

Per task, the plan's own task ID maps to a line range in `docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md` — use Grep to find `^### Task N.M` to jump to the exact task content.

### Phase 0 — Dev environment + scaffolding (3 tasks)

| Task | Status | Commit | Notes |
|---|---|---|---|
| 0.1 Dev environment setup | ✅ done | `5c17a3f` | `requirements-dev.txt`, `pyproject.toml`, `.gitignore`. pytest 9.0.3, Python 3.14. |
| 0.2 Add-on directory scaffolding | ✅ done | `610daa4` | 14 files (addon.xml, settings.xml, strings.po, conftest.py + empty `__init__.py`/`.gitkeep`). |
| 0.3 Pre-commit hook + test smoke | ✅ done | `94e65a9` | Test smoke passes. Pre-commit installed. **Known:** integration hook has `\|\| [ $? = 5 ]` to bypass empty-collection exit-5 — remove this guard when first `@pytest.mark.integration` test lands in Phase 11. |

### Phase 1 — Foundations (6 tasks: 5 base + Task 1.3b FairnessTracker fix)

| Task | Status | Notes |
|---|---|---|
| 1.1 `lib/state_paths.py` (special:// resolution + atomic write + smoke probe) | ⏸ pending | Spec §1.15, §5.1. **First Phase 1 task to execute.** Creates `tests/integration/fakes/fake_xbmcvfs.py` too. |
| 1.2 `lib/settings.py` (xbmcaddon wrapper + typed accessors + cache) | ⏸ pending | Spec §2, §5.1, §7.3 |
| 1.3 `lib/concurrency.py` part 1: AtomicCounter, abort_event, work_queue, payload dataclasses, enqueue helper | ⏸ pending | Spec §1.2, §1.6, §1.7, §1.12 |
| 1.3b **FairnessTracker** (round-1 plan-review fix C2) | ⏸ pending | Spec §1.12. Apply after 1.3. |
| 1.4 `MonotonicBudget` + `BudgetStateError` + `BudgetState` | ⏸ pending | Spec §1.8. Append to `lib/concurrency.py`. |
| 1.5 `ActiveCalls` (multi-target + 'ALL' + linger + `last_window_targets`) | ⏸ pending | Spec §1.2, §1.3, §1.7. `last_window_targets()` is required for Task 4.6-REVISED. |

### Phase 2 — Audit log + secrets + redactor (4 tasks)

| Task | Status | Notes |
|---|---|---|
| 2.1 `lib/audit_log.py` (JSONL append + 10MB×5 rotation) | ⏸ pending | Spec §5.3 |
| 2.2 `lib/secrets.py` (in-memory cache + 0600 best-effort + atomic write) | ⏸ pending | Spec §5.1 |
| 2.3 `lib/redactor.py` (patterns + heuristic + allow_list + canary) | ⏸ pending | Spec §5.8. Creates `redaction_allowlist.json` + `known_secret_keys.json` data files. |
| 2.4 Wire `redact()` into `audit_log.write_tool_call` (pair-level redaction) | ⏸ pending | Spec §5.3, §5.8 |

### Phase 3 — LLM client + router + budget + prompts (5 tasks)

| Task | Status | Notes |
|---|---|---|
| 3.1 `lib/llm/client.py` (OpenRouter non-streaming chat + typed errors) | ⏸ pending | Spec §1.10, §4.5. `DEFAULT_PREFLIGHT_MODEL` constant. |
| 3.2 `recommended_models.json` + `lib/llm/router.py` (TaskModelRouter) | ⏸ pending | Spec §4.5 |
| 3.3 `lib/llm/budget.py` (BudgetGuard with 3-point enforcement) | ⏸ pending | Spec §5.5 |
| 3.4 Streaming chat + slug validation (extend client.py with `chat_stream`, `validate_slugs`) | ⏸ pending | Spec §1.10, §4.5. **chat_stream yields 4-tuple** (chunk_text, finish_reason, usage, tool_calls) per round-2 plan fix. |
| 3.5 System prompts (`triage_system.md`, `reasoner_system.md`, `chat_system.md`) + `lib/llm/prompts.py` loader | ⏸ pending | Spec §5.6, §2 |

### Phase 4 — Log infrastructure (7 tasks total: 5 base + REVISED 4.6 + REVISED 4.7, where the REVISED versions REPLACE originals)

| Task | Status | Notes |
|---|---|---|
| 4.1 `lib/log_capture.py` (logging.Handler + stderr wrapper + recursion guard + 1s dedup) | ⏸ pending | Spec §5.9 |
| 4.2 `lib/log_sentinels.py` (LOGINFO audit sentinels + parse_sentinel) | ⏸ pending | Spec §1.3, §5.6 |
| 4.3 `lib/prefilter.py` (signature normalization + benign allowlist) | ⏸ pending | Spec §1.4 |
| 4.4 `lib/log_watcher.py` core (poll/parse/cluster/enqueue) | ⏸ pending | Spec §1.4, §3.1 |
| 4.5 log_watcher 3-signal rotation + 1MB cap + adaptive cadence | ⏸ pending | Spec §1.4 |
| **4.6-REVISED** log_watcher buffer-and-evaluate per-tool-boundary | ⏸ pending | Spec §1.3, §1.5. **Round-1 plan-review fix C5.** Supersedes original 4.6. Requires `ActiveCalls.last_window_targets()` from Task 1.5. |
| **4.7-REVISED** log_watcher boot post-mortem per-session state machine + tool-history-match | ⏸ pending | Spec §1.4. **Round-1 plan-review fix H7 + round-2 fix.** Requires `tool_history[].output_signature` from Task 5.4-AMENDMENT. |

### Phase 5 — Triage + reasoner state + reasoner + amendments (7 tasks: 5 base + REVISED 5.4 + AMENDMENT 5.4 + new 5.6)

| Task | Status | Notes |
|---|---|---|
| 5.1 `lib/triage.py` (TokenBucket + cheap-LLM classify) | ⏸ pending | Spec §1.6 |
| 5.2 `lib/reasoner_state.py` (SessionState dataclass + atomic write + load + list_all) | ⏸ pending | Spec §1.7, §5.7. **SessionState.tool_history schema** documented in Task 5.4-AMENDMENT. |
| 5.3 `lib/reasoner.py` skeleton (Reasoner class + run_simple) | ⏸ pending | Spec §1.6, §1.7, §3.1, §3.3 |
| **5.4-REVISED** Reasoner uses `chat_stream` + per-chunk mid-stream budget check | ⏸ pending | Spec §1.10, §5.5. **Round-1 plan-review fix C3.** Synthetic envelope on mid-stream trip. |
| **5.4-AMENDMENT** Populate `tool_history[].output_signature` | ⏸ pending | Spec §1.4. **Round-2 plan-review fix.** Required for 4.7-REVISED tool-history-match suppression. |
| 5.5 Reasoner pause/resume + abort_event check + `resume_from` | ⏸ pending | Spec §1.7, §1.8, §1.10 |
| **5.6** `lib/pause_sequence.py` (explicit 4-step pause sequence) | ⏸ pending | Spec §1.7. **Round-1 plan-review fix C4.** pause_and_persist enforces memory → MonotonicBudget.pause → atomic disk → Telegram 15s → pause_notify_failed terminal. |

### Phase 6 — Tool framework + snapshots (4 tasks)

| Task | Status | Notes |
|---|---|---|
| 6.1 `lib/tools/__init__.py` (@tool decorator + registry + ToolResult + tool_routing_decision) | ⏸ pending | Spec §1.9, §4.1 |
| 6.2 `lib/snapshot_manager.py` (create/restore with read_back+equality staleness; runtime resolver/applier registry) | ⏸ pending | Spec §1.13, §5.4. LRU 100/200MB. |
| 6.3 `lib/tools/extract_keys.py` (flat-id + path-flatten with `[N]` + JSON walker + parser_for_path) | ⏸ pending | Spec §4.6 |
| 6.4 `lib/tools/schema.py` (get_tool_schemas → OpenAI function spec) | ⏸ pending | Spec §4.1 |

### Phase 7 — Individual tools (10 tasks; tasks 7.4-7.7 are EXPANDED meta-tasks per round-1 plan-review fix H1)

| Task | Status | Notes |
|---|---|---|
| 7.1 `lib/tools/kodi_jsonrpc.py` (allowlist + `call()` helper) | ⏸ pending | Spec §4.3 |
| 7.2 `lib/tools/http.py` (http_get HTTPS-only + size/timeout caps) | ⏸ pending | Spec §4.6 |
| 7.3 `lib/tools/kodi_addons.py` part 1 (list/get_details/enable/disable/restart/install + builtin_with_verify wrapper) | ⏸ pending | Spec §4.2, §4.6 |
| **7.4-EXPANDED** kodi_addons part 2 (uninstall + update + clear_cache) | ⏸ pending | Spec §4.6 round-3 verify logic for update_addon. clear_cache folds restart. |
| **7.5-EXPANDED** `lib/tools/kodi_settings.py` (get/set Kodi + per-addon enabled/disabled paths) | ⏸ pending | Spec §4.6. Disabled-addon V1 type validation rules per spec. |
| **7.6-EXPANDED** `lib/tools/kodi_files.py` (read_log/read_log_old + write/delete with path lock) | ⏸ pending | Spec §4.6 |
| **7.7-EXPANDED** `lib/tools/verify.py` + log_watcher.subscribe API (per-cluster-category strategies) | ⏸ pending | Spec §4.4 |
| 7.8 `lib/tools/telegram_ask.py` (ask_user pause-signal tool) | ⏸ pending | Spec §1.7 |
| 7.9 Autoload all tool modules in `lib/tools/__init__.py::_autoload()` | ⏸ pending | — |
| 7.10 Wire snapshot_targets + tool_routing into reasoner agent loop | ⏸ pending | Spec §4.1 dispatch flow |

### Phase 8 — Telegram + QR (7 tasks)

| Task | Status | Notes |
|---|---|---|
| 8.1 `lib/qr.py` (pure-Python QR encoder + PNG writer, stdlib zlib only) | ⏸ pending | Spec §5.2, §7.2. ~600 LoC. No PIL/Pillow/qrcode. |
| 8.2 `lib/telegram/formatters.py` (HTML + 4000-char truncate + multi-part split) | ⏸ pending | Spec §4.5, §4.6 |
| 8.3 `lib/telegram/auth.py` (setup_secret + chat_allowlist + reset path) | ⏸ pending | Spec §5.2 |
| 8.4 `lib/telegram/bot.py` (T3 long-poll dispatcher with timeout=(3,10), backoff) | ⏸ pending | Spec §1.2, §1.10, §4.5 |
| 8.5 `lib/telegram/commands.py` (all V1 commands /help /status /undo /pause /resume /disable /enable /panic /budget /mode /secret /audit /invite /retry-notify) | ⏸ pending | Spec §5.7 |
| 8.6 `lib/telegram/callbacks.py` (callback_query routing + reply_to_message_id matching + 1h TTL fallback) | ⏸ pending | Spec §5.7 |
| 8.7 `lib/notifier.py` (synchronous notifier + interruptible retry + shutdown short-path + toast fallback) | ⏸ pending | Spec §1.7, §3.4, §5.7 |

### Phase 9 — Verifier + health + recovery (4 tasks)

| Task | Status | Notes |
|---|---|---|
| 9.1 `lib/verifier.py` + `log_watcher.subscribe` API + per-cluster strategies | ⏸ pending | Spec §4.4. Some overlap with Task 7.7-EXPANDED — consolidate the subscribe API there. |
| 9.2 `lib/health.py` (heartbeat + crash detection + crash_free_since) | ⏸ pending | Spec §7.4. Boot detection: clean if `last_clean_shutdown_ts - last_alive_ts ≤ 5min + 30s grace`. |
| 9.3 `lib/recovery.py` (LKG real ZIP + boot terminal-state recovery + orphan snapshot quarantine) | ⏸ pending | Spec §5.4, §7.4, §7.7. LKG with `service.kodi.ai/` top-level prefix in zinfo. |
| 9.4 Wire `health.heartbeat()` into T4 main loop + `health.record_telegram_rt_ok()` into T3 | ⏸ pending | — |

### Phase 10 — Service entry + setup wizard (3 tasks)

| Task | Status | Notes |
|---|---|---|
| 10.1 `service.kodi.ai/default.py` (status panel + setup wizard 5 screens + show_secret + reset_bot actions) | ⏸ pending | Spec §7.2, §7.3, §5.7 |
| 10.2 `service.kodi.ai/service.py` (4-thread orchestrator + boot + shutdown protocol) | ⏸ pending | Spec §1.1, §1.2, §1.14, §2 |
| 10.3 Wire T4 handlers (`_handle_incident`, `_handle_user_msg`, `_handle_resume_work`) | ⏸ pending | Spec §3.1, §3.3. Uses `pause_sequence.pause_and_persist` from Task 5.6. |

### Phase 11 — Smoke tests integration (2 tasks)

| Task | Status | Notes |
|---|---|---|
| 11.1 Wire all startup smoke tests into service.py boot pass (state-dir + redactor canary HARD FATAL; atomic-rename + log_capture + slug + Telegram bot_token + chat_id + disk-space + clock-skew = WARN-and-continue) | ⏸ pending | Spec §6.5. Telegram probes BEFORE `startup_complete_event.set()`. **Also: remove `\|\| [ $? = 5 ]` from `.pre-commit-config.yaml` integration hook now that integration tests exist.** |
| 11.2 Integration smoke test for full startup sequence | ⏸ pending | Spec §6.5, §6.6 |

### Phase 12 — Distribution + acceptance (3 tasks)

| Task | Status | Notes |
|---|---|---|
| 12.1 `tools/build_repo.py` + GitHub Pages layout (`.nojekyll`, `index.html`, repo manifests, addons.xml + md5) | ⏸ pending | Spec §7.1, §7.4. Real ZIP with `service.kodi.ai/` top-level. |
| 12.2 User-facing docs (README, CHANGELOG, PRIVACY explicit-Telegram-retention, SECURITY, UNINSTALL, LICENSE, THIRD_PARTY_NOTICES) | ⏸ pending | Spec §7.8 |
| 12.3 Acceptance tests on Shield Pro (snapshot_kodi.sh with `KODI_AI_TEST_DEVICE=1` gate + dev_server.py for B1/C4 + scenarios doc) | ⏸ pending | Spec §6.4, §6.6, §6.7 |

---

## Section 4 — Forward-looking concerns from completed tasks

These are issues caught by reviewers during Phase 0 that are NOT yet fixed and should be addressed during execution of later tasks:

1. **Pre-commit integration hook exit-5 mask** (caught + mitigated in Task 0.3): `.pre-commit-config.yaml` has `|| [ $? = 5 ]` on the integration entry. **REMOVE this guard at Task 11.1** when integration tests start landing.

2. **Python 3.14 venv vs Kodi's Python 3.11** (Task 0.1): documented divergence. Doesn't matter for pure-module unit tests; integration tests use kodistubs anyway. If anything breaks during Phase 4+ due to Python version mismatch, switch venv to Python 3.11 via `python3.11 -m venv .venv`.

3. **`settings.xml` v1 schema** (caught in Task 0.2 code review): uses Kodi-21-Omega legacy `<category label>` schema. Functional but pre-v2. Acceptable for V1; flag for V2 migration.

4. **`settings.xml` labels not localized** (Task 0.2): English strings hardcoded vs `$LOCALIZE[30001]`. Acceptable for V1 (single locale).

5. **`conftest.py` unused `import sys`** (Task 0.2): placeholder for later fakes registration. Acceptable until Task 1.1 wires fakes.

---

## Section 5 — Discipline rules (NEVER SKIP)

These rules come from `MEMORY.md` and are mandatory for this project:

1. **Every code task** (and every design decision) must be reviewed by a fresh independent subagent before being presented to the user as final. See `feedback_implementer_reviewer_loop.md`.
2. **Every `Agent` tool dispatch** in this project must pass `model: "opus"` explicitly. Sonnet (or inherited parent model) is not acceptable. See `feedback_agent_model_opus.md`.
3. **Per task execution** (subagent-driven-development):
   - Implementer subagent (Opus 4.7) writes failing test → implementation → tests pass → commit.
   - Spec reviewer subagent (Opus 4.7) verifies implementation matches plan spec.
   - Code-quality reviewer subagent (Opus 4.7) approves implementation.
   - Fix loops if either reviewer finds blockers.
   - Mark task complete ONLY after both reviewers approve clean.

---

## Section 6 — Resume execution checklist

Before starting the next task:

- [ ] `git log --oneline -5` — verify expected commit history.
- [ ] `git status` — verify clean working tree.
- [ ] `source .venv/bin/activate` — activate Python env.
- [ ] `pytest tests/unit -v --no-cov` — verify all unit tests still pass.
- [ ] `pytest tests/integration -v -m integration --no-cov` — verify all integration tests pass (will pass trivially while no integration tests exist).
- [ ] Read the spec section(s) referenced by the next task (use Grep `^## § N` in the spec).
- [ ] Read the plan task (use Grep `^### Task N.M` in the plan).
- [ ] Dispatch implementer subagent (Opus 4.7) with **full task text pasted into the prompt** (do NOT make subagent read the plan file).
