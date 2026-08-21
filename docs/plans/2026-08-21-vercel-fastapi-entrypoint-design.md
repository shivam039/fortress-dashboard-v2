# Vercel FastAPI Entrypoint Design

## Goal

Make Vercel recognize the repository-root FastAPI application during builds.

## Design

Add Vercel's supported configuration block to the existing `pyproject.toml`:

```toml
[tool.vercel]
entrypoint = "engine.main:app"
```

This points Vercel at the existing `app` object in `engine/main.py`. No
application code, dependency changes, or routing changes are required.

## Validation

Parse the TOML configuration and import the FastAPI application using the
project's virtual environment. The expected result is that the configuration
contains the exact `engine.main:app` entrypoint and the app imports
successfully.
