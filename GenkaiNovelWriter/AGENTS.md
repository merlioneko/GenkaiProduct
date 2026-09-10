# AGENTS.md

## Project Overview

GenkaiNovelWriter is a Python application for generating novels through a staged LLM pipeline.

The current pipeline conceptually consists of:

```text
user idea
→ improving
→ structuring
→ writing
→ elaboration / borders
```

The application also supports resuming selected stages from saved intermediate artifacts.

The project is intended to remain understandable and maintainable by a human developer. Do not optimize only for compactness, abstraction, or agent convenience.

---

## Sources of Truth

Before making non-trivial changes, inspect the relevant existing code and project documentation.

Use the following roles for project information:

* `AGENTS.md`: persistent engineering rules for coding agents.
* `SPEC.md`: intended product behavior, pipeline semantics, inputs, outputs, and externally visible requirements.
* Tests: executable verification of expected behavior.
* Source code: current implementation.

When `SPEC.md` exists, treat it as the primary source for intended product behavior.

If `SPEC.md`, tests, and the current implementation disagree, do not silently choose one or rewrite behavior to make them agree. Identify the conflict and preserve existing behavior unless the task explicitly authorizes a behavior change.

Do not place detailed product specifications in this file. Put them in `SPEC.md` or other appropriate documentation and reference them from here.

---

## Engineering Priorities

Use the following priority order when making implementation decisions:

1. Correct behavior.
2. Human readability and traceable control flow.
3. Maintainability.
4. Type safety and explicit interfaces.
5. Robust error handling and recoverability.
6. Simplicity.
7. Extensibility only when there is a concrete current requirement.

Do not introduce complexity solely because it may be useful in the future.

Prefer the simplest design that satisfies the current requirements without making expected near-term changes unnecessarily difficult.

---

## Human Readability

Code generated for this repository must be understandable by a human maintainer.

For orchestration and application-level control flow in particular, a reader should be able to understand the major execution sequence without opening every helper function.

Prefer explicit code over compressed or clever code.

Avoid:

* deeply nested control flow;
* large functions containing unrelated responsibilities;
* non-trivial nested local functions;
* nested ternary expressions;
* complex lambdas that contain business logic;
* implicit state shared through closures when explicit state would be clearer;
* abstractions whose purpose is not visible from their interface;
* unnecessary indirection.

A function should normally have a responsibility that can be explained in one or two sentences.

Do not mechanically split every operation into tiny functions. Extract functions when doing so creates a meaningful conceptual boundary.

---

## Pipeline Orchestration

The pipeline orchestration layer should describe **what happens and in what order**.

Individual stage implementations should describe **how that stage works**.

Keep these concerns separate.

For example, a high-level pipeline function should preferably resemble:

```python
def run_pipeline(...):
    context = prepare_context(...)

    if stage == "all":
        result = run_all(...)
    elif stage == "writing":
        result = run_writing(...)
    elif stage == "borders":
        result = load_writing_result(...)

    run_borders(...)
    return result
```

This is an architectural example, not a required literal implementation.

Do not hide the major pipeline sequence behind excessive generic dispatch, dynamic registration, decorators, callbacks, or framework machinery unless the project specification explicitly requires such behavior.

Do not introduce a workflow/orchestration framework solely to replace a simple explicit pipeline.

---

## `main.py`

Keep `main.py` focused on application entry and high-level orchestration.

It may coordinate:

* CLI argument handling;
* pipeline initialization;
* stage selection;
* calls to pipeline operations;
* final user-facing success or failure reporting.

Move substantial stage-specific implementation, persistence mechanics, status calculation, or reusable infrastructure into appropriately named functions or modules when this improves clarity.

`run_pipeline()` must remain readable as a high-level description of the execution flow.

Do not accumulate numerous substantial nested functions inside `run_pipeline()`.

---

## Architecture Boundaries

Respect the responsibilities already represented by the project structure.

In general:

* `main.py` coordinates application execution.
* `novel.engine` contains novel-generation stage operations.
* `novel` domain modules contain the structured models used by the pipeline.
* `util.file` handles file persistence and loading concerns.
* `util.gateway` handles external LLM/API connectivity.
* `util.settings` handles model and application configuration.

Before moving responsibilities between modules, check whether the change genuinely improves the architecture.

Do not create new layers, manager classes, service classes, factories, repositories, or other abstractions merely to make the architecture appear more formal.

---

## Pipeline Compatibility

Treat the following as compatibility-sensitive behavior unless the task explicitly changes the specification:

* pipeline stage names and semantics;
* the ability to run the full pipeline;
* resuming writing from a saved `Plot`;
* resuming borders/elaboration from a saved `WritingResult`;
* intermediate artifact formats;
* output artifact naming;
* scene-level persistence;
* run/event logging;
* success, partial, and failed states;
* CLI arguments and exit-code behavior.

When refactoring, preserve these behaviors unless a change is explicitly requested.

A structural refactor must not silently become a behavioral redesign.

---

## State and Data Flow

Prefer explicit data flow.

When several functions need the same execution state, either:

* pass the required values explicitly; or
* introduce a small typed context object when that clearly reduces repetition and improves readability.

Do not introduce a context object simply to avoid passing two or three understandable arguments.

If a context object is introduced, it should contain execution context such as identifiers, configuration, clients, and output locations. It should not become a general-purpose container for unrelated mutable state.

Avoid hidden mutable global state.

---

## Type Safety and Pylance

This project is developed with VS Code and Pylance.

Write code that is friendly to static analysis.

Requirements:

* Add useful type annotations to public and non-obvious interfaces.
* Preserve concrete domain types such as `Plot`, `WritingResult`, and configuration models where available.
* Prefer precise types over `Any`.
* Do not use `cast()` only to silence a type error caused by an unclear design.
* Do not add `# type: ignore` without a specific reason.
* Do not suppress Pylance diagnostics instead of fixing the underlying type issue.
* Avoid unnecessary unions when a more precise interface is practical.
* Ensure callback and generic types describe their actual inputs and outputs.

Follow the Python version declared by the repository configuration. Do not raise the minimum Python version implicitly by introducing newer syntax without checking project compatibility.

Do not claim that Pylance validation passed unless it was actually performed through an appropriate configured type-checking environment.

---

## Pydantic and Structured Data

Use existing Pydantic/domain models for structured application data when an appropriate model already exists.

Do not replace typed domain models with unstructured dictionaries for convenience.

When changing serialized models, consider compatibility with artifacts already written to disk.

Do not change serialized field names, required fields, or schemas as part of an unrelated refactor.

---

## Error Handling

Errors should remain observable and diagnosable.

Do not catch broad exceptions merely to continue execution or hide failures.

A broad `except Exception` is acceptable at an application boundary or execution wrapper when it:

1. records useful failure information; and
2. re-raises the original exception or converts it into a clearly defined application-level result.

Preserve the original exception context where practical.

Do not use exceptions for ordinary expected branching when a clear result/status value is more appropriate.

---

## Persistence and Recoverability

Intermediate artifacts exist partly to make long-running LLM work inspectable and resumable.

Do not remove intermediate persistence solely to simplify code.

When changing pipeline stages, consider:

* what artifact is available if the stage succeeds;
* what remains if the stage fails;
* whether execution can be resumed;
* whether previously generated artifacts remain readable.

Write operations should occur at intentional stage boundaries.

Do not silently overwrite unrelated existing artifacts.

---

## LLM and Provider Integration

Keep provider-specific connection details behind the existing gateway/configuration boundary where practical.

Do not hardcode:

* API keys;
* credentials;
* user-specific paths;
* provider secrets;
* model identifiers that should come from configuration.

Do not commit secrets to the repository.

Secrets should be supplied through the project's configured environment or secret-management mechanism.

Do not introduce a new LLM provider abstraction unless there is an actual requirement for one.

---

## Dependencies

Do not add a third-party dependency when the Python standard library or an existing project dependency provides a clear and maintainable solution.

Before adding a dependency:

1. verify that the requirement cannot reasonably be met with existing dependencies;
2. explain why the dependency is needed;
3. keep the dependency scoped to the actual requirement.

Do not introduce large frameworks for small orchestration or utility problems.

---

## Change Discipline

Before editing:

1. inspect the relevant implementation;
2. trace its callers and returned data where practical;
3. identify compatibility-sensitive behavior;
4. make the smallest coherent change that satisfies the task.

Do not perform unrelated cleanup during a focused task.

Do not rename public functions, files, serialized fields, CLI options, or output artifacts as incidental cleanup.

Do not rewrite working modules merely to apply a preferred architectural pattern.

If a broader refactor is genuinely necessary, explain the reason before or alongside the implementation.

---

## Comments and Documentation

Prefer code that explains itself through structure and naming.

Use comments and docstrings for:

* non-obvious design intent;
* important invariants;
* compatibility constraints;
* reasons for unusual behavior;
* resume/recovery semantics that are not obvious from the code.

Do not add comments that merely translate straightforward Python into natural language.

When externally visible behavior changes, update `SPEC.md` and other relevant documentation.

---

## Testing and Verification

Use the repository's existing test and validation configuration.

Before choosing commands, inspect relevant files such as:

* `pyproject.toml`;
* `pytest.ini`;
* `requirements*.txt`;
* existing test directories;
* CI configuration.

Do not invent a new test framework when one is already configured.

For changes to Python modules, perform syntax/import validation appropriate to the changed scope.

For the current project layout, a lightweight syntax check may include:

```bash
python -m compileall main.py novel util
```

If pytest is configured, run the relevant tests, and preferably the complete suite when practical:

```bash
python -m pytest
```

If Pyright, basedpyright, or another command-line type checker is configured by the repository, run the configured command after type-relevant changes.

For LLM-dependent code, do not require a real paid API request for every test if the behavior can be meaningfully verified with dependency injection, mocks, fixtures, or deterministic test doubles.

Tests should verify behavior rather than mirror implementation details.

Do not add trivial tests solely to increase test count.

---

## Refactoring Rules

When asked to refactor without changing behavior:

* preserve external interfaces;
* preserve serialized formats;
* preserve CLI behavior;
* preserve persistence and recovery semantics;
* preserve error visibility;
* keep changes focused;
* improve readability measurably.

After a refactor, verify that the new structure is actually easier to explain.

If the refactored implementation requires a longer explanation than the original to describe its control flow, reconsider the design.

---

## Completion Checklist

Before considering a coding task complete:

* Confirm the requested behavior is implemented.
* Check that no unrelated behavior was changed.
* Ensure the main control flow remains understandable.
* Check relevant type diagnostics.
* Run applicable tests and validation commands.
* Verify persisted formats when the change touches stored models.
* Check that no credentials or local-only data were introduced.
* Review the diff for unnecessary abstraction or unrelated edits.

In the final response, summarize:

1. what changed;
2. why it changed;
3. what validation was performed;
4. any remaining uncertainty or unverified behavior.

Do not claim tests, type checks, or runtime behavior were verified if they were not actually executed.
