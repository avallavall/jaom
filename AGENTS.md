# AGENTS.md — Working agreement for this repo

Whoever works in this repo — human or agent, whatever tool — works under
these rules. The maintainer's rules. Not suggestions.

The design lives in `docs/SPECS.md`; the execution order in `docs/PLAN.md`;
the kickoff brief `docs/jaot-odoo-brief.md` is the historical record (kept
as-is, in Spanish). Unresolved questions are the OPEN items in `SPECS.md`
§3.2 — they are **never settled by inference**; ask the maintainer.

## Never

- **Never `git push` unless explicitly asked.** Commit freely — pushing is the
  maintainer's call, every single time. This applies to agents and worktrees too.
- **Never weaken a test to make it pass.** A failing test means the code is wrong
  until proven otherwise. No skipping, no loosening assertions, no disabling.
- **Never claim something works without having run it.** A green signal you did not
  verify yourself is not evidence: check the thing, not the wrapper that reports on
  it. Reporting tools lie, and the failure is silent.
- **Never add features beyond what was asked.**
- **Never invent numbers, benchmarks, citations or credentials.** If a figure is not
  measured, it does not go in.

## Always

- **Fix what you find.** If something is broken on the way past it, fix it. Do not
  ask permission for the obvious, and do not leave dead bodies behind.
- **Verify the whole thing before committing**, not only the lines you touched —
  and at the start of a session, so you know what you inherited.
- **Say what you actually verified.** "Tests pass" is worthless without which tests
  and how they were run.
- **Conventional Commits.** The message explains the mechanism and the why; the
  reader who wants detail should end up in the commit, not in a wiki.
- **Keep the changelog and the docs current in the same commit cycle** as the change
  itself. Entries are one to three lines and say what changed for someone using this
  — never internal identifiers or plan codes a reader cannot resolve from the repo.

## Design

- **Depend on Odoo, and on nothing else by accident.** Any other dependency is a
  decision the maintainer takes explicitly, never something that arrives because it
  was convenient while writing a feature.
- **A working document holds only what is open.** When something closes it leaves the
  document; the record lives in the changelog and in the commit that closed it.

## Practical

- Talk to the maintainer in plain, simple English, whatever language they write in.
  Everything committed — code, comments, docs, commit messages — is in English too.
- Split work across specialised agents when it genuinely decomposes — several with
  distinct roles beat one generalist grinding through everything in sequence. Two
  things to watch, both learned the hard way: agents inherit the session's model and
  multiply its cost by however many run at once, so size a batch with that in mind;
  and always verify what comes back — an agent that silently delivers nothing looks
  exactly like one still working.
