---
name: unit-test-writer
description: >-
  Write focused unit tests for Python functions using pytest. Use when asked
  to add tests for a function, module, or class, to improve test coverage, or
  to fix a failing test. Covers test naming, arrange/act/assert structure,
  parametrized cases, fixtures, and mocking.
tags: [testing, pytest, unit-tests, python]
triggers:
  - "write unit tests"
  - "add tests for"
  - "test coverage"
  - "failing test"
  - "pytest"
author: LangConfig
---

# Unit Test Writer

Use this skill when writing or fixing unit tests for Python code.

## When to Use
- User asks to write tests for a function, class, or module
- Adding coverage for a new feature or a fixed bug
- Debugging a failing test

## Steps
1. Read the target code and identify the public functions/classes to test.
2. For each function, list the key behaviors: happy path, edge cases, and
   error paths.
3. Write one test per behavior using pytest:
   - Name: `test_<function>_<behavior>` (e.g. `test_validate_email_rejects_missing_at`)
   - Structure: arrange → act → assert
4. Use `@pytest.mark.parametrize` for input/output tables.
5. Use fixtures for shared setup and `unittest.mock` / `monkeypatch` for side
   effects (network, time, random).
6. Run the tests and iterate until green.

## Checklist
- [ ] Tests are deterministic (no sleeps, no network, no random)
- [ ] One behavior per test
- [ ] Edge cases covered (empty input, None, boundaries)
- [ ] Test names describe behavior, not implementation
- [ ] Failure messages are actionable
