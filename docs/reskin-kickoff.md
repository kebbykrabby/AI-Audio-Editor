# Kickoff prompt for the resumed reskin session

Copy the text between the two horizontal rules and paste as your first message
in a fresh Claude Code session opened in this repo.

---

Resume the frontend reskin on `feat/reskin`. Previous session ran out mid-Step-3.

**Before writing any code**, read these three files in order and follow them:

1. `docs/reskin-handoff.md` — current commit chain, working tree state, exact next command to run, gotchas from the previous session, non-obvious contracts of the 4 new backend endpoints.
2. `docs/reskin-plan.md` — full scope, screen-by-screen mapping, decisions already locked with me.
3. `base44-harvest/` — the harvested design authority (do not modify, only read).

Then proceed exactly as the handoff's "Next-session TODO" section says. Do NOT re-ask the decisions I've already made (sonner, violet accent, split OperationPanel, merge SelectionInfo into TransportBar, Version History from `editorStore.assetHistory`, etc.). Do NOT restart the plan. Do NOT reinvent scope.

Standing rules that apply throughout:

- **Backend is frozen again** now that the 4 unfrozen endpoints have shipped. From here on, everything is a frontend restyle preserving existing wiring. If any harvested UI needs backend work not on the plan, STOP and flag it — don't build it.
- Every step ends with `tsc -b` clean, a commit, and a short status message to me. Commit messages: short one-liners; the shell hook rejects long messages that mention "password/verify/reset/auth/secret" etc.
- No merge to `main` without my explicit UI-test approval — hard rule; wait for me.
- No `Co-Authored-By` trailer on any commit.
- For `.env*` and `docker-compose*` files: use Read/Edit/Write, not Bash.

Your first turn should:
1. Confirm branch is `feat/reskin`, HEAD is `57325a1` (or later), working tree clean, `pytest -q` still 268 passing, `tsc -b` clean.
2. State what you're about to do (finish Step 3: `npm install` the queued Radix packages, port 9 primitives, add `@/` alias, mount sonner Toaster, commit).
3. Do it.

If anything in the handoff doc is unclear or looks stale against the current tree, ask me one specific question and wait. Otherwise, proceed.

---
