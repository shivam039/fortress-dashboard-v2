---
name: python-testing
description: "Python testing best practices: pytest patterns, fixtures, mocking, and TDD workflows"
---

# Python Testing Best Practices

## Test discovery and structure

- Store tests in `tests/` or adjacent to source files as `*_test.py` or `test_*.py`
- Use pytest fixtures for setup/teardown
- Group related tests in test classes with a `Test` prefix

## Pytest essentials

```python
import pytest

@pytest.fixture
def example_resource():
    resource = setup()
    yield resource
    teardown(resource)

def test_with_fixture(example_resource):
    result = example_resource.do_work()
    assert result == expected
```

## Mocking and isolation

Use `unittest.mock` or `pytest-mock`:

```python
from unittest.mock import Mock, patch

def test_with_mock(mocker):
    mock_service = mocker.patch('module.Service')
    mock_service.return_value = Mock(status='ok')
    assert your_code_using_service()
```

## Red-Green-Refactor cycle

1. **Red:** Write a failing test; ensure it fails for the right reason
2. **Green:** Implement the minimal code to pass the test
3. **Refactor:** Improve code quality without changing behavior

```bash
pytest tests/ --tb=short
```

## Coverage

```bash
pytest --cov=src tests/
```

Aim for >80% coverage, but prioritize testing critical paths.
