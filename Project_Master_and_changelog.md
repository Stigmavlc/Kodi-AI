# Project Master & Changelog

## 1. Project Overview

**Project Name:** Kodi-AI
**Created:** 2026-05-26
**Description:** [Brief description of what this project does]

## 2. Current Status

- [ ] Project setup
- [ ] Core functionality
- [ ] Testing
- [ ] Documentation

## 3. Architecture & Key Files

[Document key files and their purposes as the project develops]

## 4. Development Notes

### Mandatory Implementer + Reviewer Loop (applies to BOTH code and design)

**Rule:** Every code implementation AND every design decision must be reviewed by a fresh independent subagent before being presented as final.

**For code implementation:**
1. **Implementer Agent** — Writes/modifies the code for the assigned task.
2. **Reviewer Agent** — Reviews the implementer's code for correctness, bugs, quality, and adherence to project conventions.

**For design / planning work (architecture sections, data flows, component layouts, tool catalogs, schemas, plans, etc.):**
1. The assistant drafts the design section.
2. Before presenting to the user, a fresh **Reviewer Agent** is dispatched to scrutinize the design for: logic flaws, architectural problems, hidden assumptions, edge cases, security issues, scalability concerns, Kodi-specific constraints, and anything that could cause problems later.
3. Only after the Reviewer signs off clean is the design presented to the user.

**Loop Logic (both cases):**
- If the reviewer finds **no issues** → present to user / mark task completed.
- If the reviewer finds **any issues** → a brand-new agent is dispatched to fix them, followed by a brand-new Reviewer agent to re-check.
- This loop continues indefinitely until a Reviewer agent returns a clean review with zero issues.

**Every reviewer must be FRESH** — a new instance, no carried context from prior reviews. This guarantees independent judgment.

**Every Agent dispatch must use Claude Opus 4.7 with max reasoning** — `model: "opus"` must be passed explicitly to every `Agent` tool call (reviewer or implementer). Defaulting to Sonnet or inheriting parent model is not acceptable for this project's review loop.

**No task is considered complete, and no design decision is presented to the user as final, until a Reviewer agent (running on Opus 4.7) has signed off without findings.**

---

[Add additional notes, decisions, and context below]

## 5. Changelog

### 2026-05-26
- Project initialized
- Added mandatory Implementer + Reviewer subagent workflow rule (see Development Notes §4)
- Extended the workflow rule to cover design/planning decisions, not just code implementation — every design section now requires a fresh Reviewer Agent sign-off before being presented to the user
- Required all Agent dispatches in this project to use Claude Opus 4.7 (`model: "opus"` explicit) with max reasoning, for both reviewer and implementer agents

## 6. Session Context

*This section is used for context handoff between Claude Code sessions. Auto-saved entries will appear here.*

