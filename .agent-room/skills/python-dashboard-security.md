---
description: Python Dashboard Security & Patterns
name: python-dashboard-security
---
# Skill: Python Dashboard Security & Patterns

This skill applies when developing features for the Streamlit dashboard or FastAPI backend, with a focus on security, robustness, and common pitfalls.

## Context

The repository contains a Python-based dashboard primarily utilizing Streamlit for the frontend and FastAPI for the backend, along with data visualization and database integrations.

## Best Practices & Patterns

### 1. Secrets Management
*   **Never hardcode secrets:** API keys, database credentials, passwords, and tokens must always be read from environment variables or secure configuration management.
*   **Use `.env` for local development:** Ensure `.env` files are in `.gitignore` and never committed.
*   **Streamlit Secrets:** In Streamlit, access secrets using `st.secrets` when deployed, or environment variables locally. Ensure `st.secrets` usage is graceful if keys are missing during local development.

### 2. Streamlit Best Practices
*   **State Management:** Avoid directly mutating `st.session_state` during render. Use callbacks or dedicated functions for state updates to prevent unexpected reruns or infinite loops.
*   **Caching:** Liberally use `@st.cache_data` for data transformations and `@st.cache_resource` for database connections or ML models to ensure UI responsiveness.
*   **Avoid Global State:** Do not use global python variables to store user-specific data; always use `st.session_state`.
*   **Programmatic Navigation:** Avoid programmatic tab switching via `st.session_state` and `st.rerun()`. Prefer instructing the user or using standard Streamlit navigation mechanisms.

### 3. FastAPI & Backend Security
*   **Input Validation:** Use Pydantic models for all incoming request payloads to validate and sanitize data automatically.
*   **Rate Limiting & Authentication:** Ensure sensitive endpoints are protected via dependency injection (e.g., OAuth2 with Password (and hashing), Bearer with JWT).
*   **Asynchronous Tasks:** For heavy data processing, delegate to background tasks (e.g., `BackgroundTasks` in FastAPI) or dedicated task queues to maintain API responsiveness.

### 4. Database Interactions
*   **Parameter Binding:** Always use parameterized queries or an ORM (like SQLAlchemy) to prevent SQL Injection.
*   **Connection Management:** Ensure database connections are pooled, kept alive, and properly closed. Use tools like `tenacity` for transient error retries on connection.

### 5. Logging and Raw Data
*   **No Sensitive Data in Logs:** Never log PII, passwords, or raw session tokens.
*   **Git Hygiene:** Raw data (CSV, DB files) or log files must not be committed to the repository.

## Pre-commit Verification

Before concluding a task involving UI or Backend changes, ensure:
1.  All inputs are validated.
2.  No secrets are introduced in the source code.
3.  The UI remains responsive and free of state-management loops.
