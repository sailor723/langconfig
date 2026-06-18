# LangConfig Development Rules

## Settings & Configuration

### Rule 1: All settings in PostgreSQL
All application settings — including API keys, default model, local model configs, temperature, token limits, etc. — **must** be stored in the `settings` table in PostgreSQL. No hardcoded defaults in Python code, no `.env` values should override DB settings at runtime.

### Rule 2: No .env or Python enums for settings
- `.env` file is **only** for local development bootstrapping (database connection, initial setup).
- Do **not** define Python enums or constants for settings values (model names, API keys, etc.).
- The `config.py` `BaseSettings` class should not contain settings that belong in the DB (models, defaults, etc.).
- The source of truth is always the `settings` table row (id=1).

### Rule 3: Settings Panel is the single entry point
The **only** way to update settings in the database is through the **Settings Panel** UI or its corresponding API endpoints (`/api/system/settings/*`). No code should programmatically write to the `settings` table outside of the settings API.

### Rule 4: Read from DB at runtime
Any component that needs a setting value (e.g., default model for new agents) must query the DB at runtime. Caching is acceptable for performance, but the DB is the authoritative source.

## Code Implementation Workflow

### Step 1: Write a test script first with mock data
Always start with a test script that uses mock data to verify the core logic works before touching any existing backend code.

### Step 2: Implement backend changes step by step
Make small, incremental changes to the backend code, one piece at a time.

### Step 3: Test each step after code is done
After each small implementation step, run the test script to verify the step works. If it fails, go back to Step 2 and fix the code before proceeding further.

### Step 4: Run full backend tests
Once all implementation steps are complete, run all backend tests to ensure everything works together.

### Step 5: Implement UI changes
Only after the backend is fully tested and working, proceed to implement the corresponding UI changes.

## Code Quality
(Add other project rules as needed)
