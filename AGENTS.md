# Repository Guidelines

## Shared Instructions and Reading Order

This file is the shared working guide for Codex, Claude, and other coding agents in this repository. `GenkaiNovelWriter/CLAUDE.md` loads this guide and contains only Claude-specific instructions. Do not copy shared rules into both files.

For GenkaiNovelWriter work, read this guide, then [SPEC.md](GenkaiNovelWriter/SPEC.md), then [MILESTONES.md](GenkaiNovelWriter/MILESTONES.md). Read the relevant decisions, acceptance criteria, milestone evidence, and handoff notes before making changes. Other projects in this repository are not governed by the NovelWriter specification.

## Document Ownership and Updates

| Document | Authoritative content | Update when |
|---|---|---|
| [SPEC.md](GenkaiNovelWriter/SPEC.md) | Scope, requirements, acceptance criteria (`AC-*`), decisions and rationale (`D*`), explicitly unresolved questions (`U*`) | Requirements or decisions change |
| [MILESTONES.md](GenkaiNovelWriter/MILESTONES.md) | Current status, work sequence, entry gates, acceptance results, verification evidence, blockers, and next actions | Work or verification status changes |
| [AGENTS.md](AGENTS.md) | Shared work rules, reading order, document maintenance, and any explicitly labeled Codex-specific guidance | The working process changes |
| [CLAUDE.md](GenkaiNovelWriter/CLAUDE.md) | Loading this guide and Claude-specific guidance | Claude-specific operation changes |

- Keep acceptance criteria in SPEC only; refer to their stable IDs from MILESTONES and record whether and how they were satisfied. Do not duplicate criterion text as a separate definition. Test instructions in [test/README.md](GenkaiNovelWriter/test/README.md) describe how to verify; they do not redefine acceptance or own verification results.
- Keep current milestone names, completion dates, test counts, environment observations, and unresolved implementation issues in MILESTONES. SPEC may retain dated evidence that explains a decision, with a link to the detailed verification record. Do not put progress snapshots in agent guides.
- Record verification date, target commit (or base commit plus uncommitted changes), environment, command or procedure, result, evidence location, and unverified limitations. Mark missing historical information as unrecorded; never infer it from the current HEAD. Distinguish offline tests, local model execution, inspection of saved artifacts, and reports from prior conversations.
- A documentation update does not refresh an old test result. Preserve historical dates and completion approvals. Record unavailable artifacts and pending checks explicitly; build/import success alone does not establish milestone completion.
- When a requirement changes, update SPEC and the affected MILESTONES references/results together. Previously passing results may require re-verification; do not silently reuse them for changed criteria. When resolving a `U*`, record the decision, rationale, and original U ID in SPEC and link to evidence in MILESTONES. Keep existing IDs stable; do not reuse retired IDs.
- Treat drafts and unresolved questions as such. Do not implement code that assumes an unresolved choice is final; planned experiments to resolve it are allowed. Respect milestone entry gates and propose out-of-scope changes separately.
- If specification, implementation, or records conflict, record the discrepancy in MILESTONES and resolve it from existing decisions and user instructions before dependent implementation. If no resolution is established, ask about the unresolved choice while continuing independent work. Do not rewrite SPEC merely to match the implementation.
- Before finishing, check document links, stale references, duplicate status declarations, and consistency between changed criteria and their results. Use `git diff --check` for documentation changes. Run application tests when behavior changes, not merely to refresh historical counts after a documentation-only edit.

The documentation organization adopted on 2026-10-21 separates requirements from evidence and keeps shared agent rules in one place. The migration and its verification are recorded in [MILESTONES.md](GenkaiNovelWriter/MILESTONES.md#documentation-review). Keep concise decision rationales in SPEC; if detailed decision history becomes too large, move it to `docs/adr/` with links instead of duplicating it.

## Project Structure & Module Organization

- `GenkaiNovelWriter/` contains the primary Python CLI. `main.py` dispatches commands; `novel/` holds schemas, run artifacts, checks, and phase functions; `util/` provides backend configuration, API access, and logging.
- `GenkaiNovelWriter/prompts/` stores phase prompts and sample inputs; `config/` contains configuration examples; `test/` contains automated tests and backend verification instructions.
- `GenkaiIllustrator/util/gateway.py` contains ComfyUI workflow helpers.
- Generated text, reports, and logs belong in ignored `creations/` directories.

## Build, Test, and Development Commands

Use Python 3.10+ and Pydantic 2. Run these PowerShell commands from `GenkaiNovelWriter/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s test -t . -p "test_*.py" -v
.\.venv\Scripts\python.exe main.py baseline --input prompts/tests/concrete_01.txt
.\.venv\Scripts\python.exe main.py stage concept --input prompts/tests/concrete_01.txt
.\.venv\Scripts\python.exe main.py stage structure --run creations/<run-directory>
```

The first two commands prepare dependencies; the third runs offline tests. The remaining commands generate a baseline or run Concept and Structure through the configured backend. No separate build step is configured.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, `snake_case` functions/modules, `PascalCase` classes, and uppercase constants. Use type annotations, `pathlib.Path`, and explicit UTF-8 file I/O. Preserve Japanese prompts and domain terminology. Keep Pydantic schemas independent of gateways, prompts, and file I/O; implement transformations in phase functions. No formatter or linter is configured.

## Testing Guidelines

Use standard-library `unittest`, with `test_*.py` files and `test_*` methods. Keep `-t .` in discovery commands. Stub gateways or use in-memory HTTP transports so automated tests require no API connection. Cover changed validation, failure, and artifact-handling behavior. No numeric coverage threshold is configured. Follow `test/README.md` for live backend checks; assess output quality using the local backend only.

## Commit & Pull Request Guidelines

History uses concise Japanese descriptions, often naming the affected component and milestone, such as `Structure フェーズを実装する(M2-5)`. Keep one purpose per commit; separate refactoring from features. PRs should explain behavior changes, reference relevant issues or SPEC decisions/milestones, and report test commands and results.

## Specification & Configuration

Follow the document ownership and conflict rules above. Copy `config/backends.example.json` to `.env/backends.json` and configure model identifiers locally. Never expose or commit `.env/` contents or API keys.
