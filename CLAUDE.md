# Kodi-AI — Project Memory (auto-loaded)

This file is loaded automatically by Claude when working in this directory. It contains the rules + pointers needed to operate on this project competently.

## Project

Kodi-AI is a `xbmc.service` add-on (V1: personal use on **Nvidia Shield Pro / Android TV**) that proactively monitors Kodi logs, classifies issues with a cheap LLM, runs a tool-using LLM agent (OpenRouter) to apply fixes, and surfaces results via a **Telegram bot** (long-poll, no webhooks).

## ⛔ Hard discipline rules (NEVER violate)

### Rule 1 — Implementer + Reviewer loop (code AND design)

Every code implementation AND every design decision must be reviewed by a **fresh independent Claude Opus 4.7 subagent** before being presented as final.

- **Code:** Implementer Agent → Reviewer Agent → loop until reviewer signs off clean.
- **Design:** Draft section yourself → fresh Reviewer Agent scrutinizes (logic, architecture, assumptions, edge cases, Kodi-specific concerns) → fix → re-review until clean.

This rule applies to ALL work in this project, no matter how small. Source: [`feedback_implementer_reviewer_loop.md`](~/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/feedback_implementer_reviewer_loop.md).

### Rule 2 — Every `Agent` dispatch must pass `model: "opus"` explicitly

Defaulting to Sonnet or inheriting parent model is NOT acceptable for this project's reviewer + implementer agents. Always pass `model: "opus"` to the Agent tool. Max reasoning is implicit in Opus 4.7. Source: [`feedback_agent_model_opus.md`](~/.claude/projects/-Users-ivan-Desktop-Web-Development--Projects-Completed-By-Me-Kodi-AI/memory/feedback_agent_model_opus.md).

### Rule 3 — Subagent-driven execution per task

When executing the implementation plan:
1. **Implementer subagent** (Opus) writes failing test → impl → tests pass → commit.
2. **Spec compliance reviewer subagent** (Opus) verifies implementation matches the plan task spec.
3. **Code quality reviewer subagent** (Opus) approves implementation (clean, tested, maintainable).
4. Fix loops if either reviewer finds blockers.
5. Mark task complete ONLY after both reviewers approve clean.

Skill: `superpowers:subagent-driven-development`.

## Key file pointers

| What | Path |
|---|---|
| **Design spec (locked)** | `docs/superpowers/specs/2026-05-26-kodi-ai-design.md` |
| **Implementation plan (locked)** | `docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md` |
| **Handover / task tracker** | `HANDOVER.md` (this is the source of truth for "what's left to do") |
| **Session changelog** | `Project_Master_and_changelog.md` |

## Custom slash commands

- `/load-context` — auto-loads all relevant files at session start. **Run this first in any new session.**
- `/save-context` — updates HANDOVER.md + Project_Master_and_changelog.md with session progress. **Run this at session end.**

Both commands live at `.claude/commands/`.

## Where we are (high-level)

- Design + plan = locked, both passed full Opus 4.7 reviewer-loop discipline.
- Phase 0 (3 dev-env/scaffolding tasks) = done.
- Phase 1-12 (62 remaining TDD tasks; 65 total including all REVISED/AMENDMENT/sub-tasks) = pending. See `HANDOVER.md` Section 3 for the exact task list with status.

## How to start a new task

1. `/load-context` (or read HANDOVER.md + the spec + the plan task manually).
2. Open `docs/superpowers/plans/2026-05-26-kodi-ai-implementation.md` and Grep `^### Task N.M` for the next pending task.
3. Dispatch implementer subagent (Opus 4.7) with **full task text pasted into the prompt** — do NOT make the subagent Read the plan file.
4. Follow the 3-stage subagent flow (implementer + spec reviewer + code-quality reviewer).
5. Update HANDOVER.md status to `✅ done` with commit SHA.
6. Move to next task.

## Forward-looking concerns

See `HANDOVER.md` Section 4. The most actionable carry-over: remove `|| [ $? = 5 ]` from `.pre-commit-config.yaml` at Task 11.1 (once integration tests land).
