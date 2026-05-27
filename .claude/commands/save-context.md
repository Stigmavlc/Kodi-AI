---
description: Save session progress comprehensively into HANDOVER.md + Project_Master_and_changelog.md
---

You are ending (or pausing) a session on the **Kodi-AI** project. Capture all progress so the next session can pick up cleanly via `/load-context`.

## Step 1 — Audit what changed this session

Run:

```bash
cd "/Users/ivan/Desktop/Web Development  Projects/Completed By Me/Kodi-AI"
git log --oneline <since-last-/save-context-or-session-start>..HEAD
git status
```

If you don't know the start point, default to commits since the last `Project_Master_and_changelog.md` changelog entry, OR ask the user.

For each commit since the last save:
- Note the SHA, message, and which plan task (if any) it implements.
- Note any deviations from the plan (compromises, follow-up TODOs, reviewer notes).

## Step 2 — Update `HANDOVER.md`

Edit `HANDOVER.md`:

1. **Top of file:** Update `Last updated`, `Latest commit` SHA + message.
2. **Section 3 (Task status table):** For each task you executed this session, change status from `⏸ pending` (or `🚧 in-progress`) to `✅ done` and fill in the Commit column. If a task was started but not finished, leave it `🚧 in-progress` and add a brief "Resume here:" note to the right column.
3. **Section 4 (Forward-looking concerns):** Add any new concerns reviewers raised during this session that were not fixed inline.

Use the Edit tool to make targeted changes; do NOT rewrite the entire file.

## Step 3 — Update `Project_Master_and_changelog.md`

Append today's session entry under `## 5. Changelog` with bullets covering:

- Which tasks completed (with SHAs).
- Any plan revisions or follow-up TODOs raised.
- Any blockers or decisions worth recording.

Use the Edit tool to insert under the date heading; create today's heading if not present.

## Step 4 — Dispatch fresh Opus 4.7 reviewer on the updates

Per the project's discipline rule, the updates to `HANDOVER.md` + `Project_Master_and_changelog.md` are design-tracking artifacts; review them with a fresh agent.

Use the **Agent tool** (Claude Code's `Agent` tool) with these parameters:
- `description`: "Review HANDOVER + changelog updates"
- `subagent_type`: "general-purpose"
- `model`: "opus" (REQUIRED per project discipline rule — never default or inherit)
- `prompt`: a self-contained prompt covering (a) the diff to `HANDOVER.md` (e.g., paste `git diff HEAD -- HANDOVER.md`), (b) the new entry appended to `Project_Master_and_changelog.md`, (c) the commit log since session start, and asking the reviewer to verify:
  1. Factual correctness vs `git log` (every claimed commit exists with the stated message).
  2. Coverage: every task executed this session is reflected in HANDOVER.md Section 3 status.
  3. Accuracy of forward-looking concerns in HANDOVER.md Section 4.
  4. Any missing handoff info that would block `/load-context` in the next session.
  5. Section 3 task counts still add up (Phase totals + overall total).

Apply any findings; loop until reviewer signs off clean. Each reviewer dispatch must be a **fresh** invocation (no SendMessage continuation) so the discipline of independent judgment is preserved.

## Step 5 — Stage + commit the handover updates

```bash
git add HANDOVER.md Project_Master_and_changelog.md
git commit -m "$(cat <<'EOF'
docs: session handover — <brief summary>

- Tasks completed: <list with SHAs>
- HANDOVER.md updated: <which sections>
- Carry-forward concerns: <count> (see HANDOVER.md §4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Step 6 — Report

Output to user:

```
✅ Context saved.

Session summary:
  • Commits this session: <count>
  • Tasks completed: <list>
  • New forward-looking concerns: <count>
  • Handover commit: <SHA>

HANDOVER.md is up to date. /load-context in a new session will pick up
at the next pending task.
```

## Step 7 — Optional: print suggested resume command

If the user is genuinely ending the session, suggest:

```
To resume in a new session:
  1. cd into the project dir.
  2. Open Claude Code.
  3. /load-context

Resume target: Task N.M — <name>
```
