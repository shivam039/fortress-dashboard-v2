# Agent Instructions — app (Python)

This file supplements the base AGENTS.md with Python-specific guidance.

## Python-specific workflow

1. **Virtual Environment:** Always operate within a virtual environment (venv, poetry, pipenv, or similar).
2. **Type Hints:** Use type hints for function signatures (not required but encouraged for clarity).
3. **Testing:** Use pytest for unit tests; write tests first (TDD), then implement.
4. **Linting:** Run flake8 or ruff; fix all linting errors before committing.
5. **Dependencies:** Pin versions in requirements.txt or pyproject.toml; review security advisories.

## Language-specific principles

- **PEP 8 compliance:** Follow Python's style guide (4-space indentation, line length ≤ 79 for code).
- **Readability > Cleverness:** Prefer explicit over implicit; write code for the next human.
- **Avoid Dynamic Features:** Minimize use of `__getattr__`, `eval()`, `exec()` unless absolutely necessary.
- **Async/Await:** If using asyncio, be consistent; don't mix sync and async without clear boundaries.

## Common pitfalls

- ❌ Mixing dependency managers (e.g., pip and poetry)
- ❌ Hardcoding paths; use `pathlib.Path` instead
- ❌ Catching bare `Exception`; catch specific exceptions
- ❌ Importing * (`from module import *`)
- ✅ Always use context managers (`with` statements) for file/resource handling

## Stack detection

This room was scaffolded for Python. Detected configuration:
- **Package Manager:** pip
- **Test Command:** pytest
- **Lint Command:** flake8 .

See `.agent-room/principles.md` and `workflow-classifier.md` for the full playbook.
