---
description: Auto-load all context for the Kodi-AI project at session start
---

You are starting (or resuming) a session on the **Kodi-AI** project. Perform these steps in order, then report back with a concise status summary so the user knows where execution should resume.

## Step 1 — Read project memory + discipline rules

Read these files in order and internalize their content:

1. `CLAUDE.md` — project memory (also auto-loaded by Claude Code, but read explicitly to be sure).
2. `~/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/MEMORY.md` — the memory index.
3. `~/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/feedback_implementer_reviewer_loop.md` — implementer + reviewer loop discipline (applies to BOTH code AND design).
4. `~/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/feedback_agent_model_opus.md` — every `Agent` dispatch MUST pass `model: "opus"` explicitly.

## Step 2 — Read the handover

Read `HANDOVER.md` in full. This is the **source of truth for what's left to do**. Pay particular attention to:

- Section 2: locked artifacts (don't redo).
- Section 3: task status table (find the next `⏸ pending` task).
- Section 4: forward-looking concerns from completed tasks.
- Section 5: discipline rules summary.
- Section 6: resume execution checklist.

## Step 3 — Read project history

Read `Project_Master_and_changelog.md` for project context and the running changelog. The Development Notes section codifies the implementer+reviewer rule.

## Step 4 — Skim the locked spec + plan (do NOT read in full)

- `docs/superpowers/specs/2026-05-26-kodi-ai-design.md` — the 1452-line design spec (locked after 22 Opus 4.7 reviewer rounds). Don't read end-to-end; jump to relevant sections via Grep `^## § N` when a task references them.
- `docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md` — the 9854-line implementation plan (locked after 3 Opus 4.7 reviewer rounds). Don't read end-to-end; jump to the next pending task via Grep `^### Task N.M`.

## Step 5 — Verify environment

Run these checks. **Each numbered block must execute as ONE Bash invocation** (state like activated venv does not persist between Bash tool calls — chain with `&&`).

Block 1 (git state):

```bash
cd "/Users/ivan/Desktop/Web Development  Projects/Completed By Me/Kodi-AI" && git log --oneline -5 && echo "---" && git status
```

Block 2 (Python + tests; single chained invocation so the venv activation persists):

```bash
cd "/Users/ivan/Desktop/Web Development  Projects/Completed By Me/Kodi-AI" && source .venv/bin/activate && python --version && pytest --version && pytest tests/unit -v --no-cov && pytest tests/integration -v --no-cov -m integration
```

(The previous exit-5 mask `|| [ $? = 5 ]` was removed in Task 11.1 once integration tests landed — now exit-5 means no tests collected, which is a real failure and should bubble up.)

Report any unexpected results.

## Step 6 — Identify next pending task

From `HANDOVER.md` Section 3, find the first row marked `⏸ pending`. That's the next task. Grep the plan file for its `### Task N.M` heading to load the full task content.

## Step 7 — Brief the user

Output a concise status summary:

```
✅ Context loaded.

Project: Kodi-AI V1 (Kodi xbmc.service add-on; OpenRouter + Telegram bot; Nvidia Shield Pro Android TV).
Branch: main
Latest commit: <SHA> <message>
Phases done: <N>/13
Tasks done: <X>/65
Next pending task: Task N.M — <name> (Phase N)
Plan path: docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md (Grep `^### Task N.M`)
Spec sections referenced: §X, §Y
Forward-looking concerns active: <count> (see HANDOVER.md §4)
Discipline rules confirmed active: implementer + reviewer loop (BOTH code AND design); model="opus" on EVERY Agent dispatch.

Ready to dispatch implementer for Task N.M when you say "go".
```

## Step 8 — Wait for go-ahead

Do NOT auto-start the next task. Wait for the user to confirm before dispatching the implementer subagent. (Reason: they may want to re-prioritize, fix something first, or switch execution mode.)
