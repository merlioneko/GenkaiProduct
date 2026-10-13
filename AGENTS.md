# Repository Guidelines

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

Treat `GenkaiNovelWriter/SPEC.md` as authoritative and follow `MILESTONES.md` for the current milestone. Resolve specification conflicts before implementing; propose out-of-scope changes separately. Copy `config/backends.example.json` to `.env/backends.json` and configure model identifiers locally. Never expose or commit `.env/` contents or API keys.
