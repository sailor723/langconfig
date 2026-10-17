# Contributing to LangConfig

Thank you for your interest in contributing to LangConfig! We welcome contributions from everyone.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Style Guidelines](#style-guidelines)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up the development environment (see [Development Setup](#development-setup))
4. Create a branch for your changes
5. Make your changes
6. Test your changes
7. Submit a pull request

## How to Contribute

There are many ways to contribute to LangConfig:

- **Report bugs** - If you find a bug, please report it by opening an issue
- **Suggest features** - Have an idea? Open an issue to discuss it
- **Improve documentation** - Help us improve our docs
- **Write code** - Fix bugs or implement new features
- **Review pull requests** - Help review other contributors' work
- **Add agent templates** - Create new pre-built agent configurations
- **Create tool integrations** - Add new MCP server integrations

## Development Setup

### Prerequisites

- Node.js 24+
- Python 3.13 (managed with [`uv`](https://docs.astral.sh/uv/) — see `backend/.python-version`)
- PostgreSQL 16 + pgvector (Docker Desktop is the easy path: `docker compose up -d postgres`)
- Git

### Installation

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/langconfig.git
cd langconfig

# Install frontend dependencies
npm install

# Install backend dependencies (creates backend/.venv from uv.lock)
cd backend
uv sync
cd ..

# Start PostgreSQL (pgvector/pg16 on the port set by POSTGRES_PORT)
docker compose up -d postgres

# Configure environment — infrastructure only (DB, ports, workspace, tracing)
cp env_example .env

# Initialize database + load seed data (idempotent, safe to re-run)
cd backend
.venv/bin/python scripts/seeds/in/seed_all.py
cd ..
```

### Running in Development

```bash
# Terminal 1 - Backend
cd backend
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8765
# (or: bash start.sh, which also starts Postgres and the frontend)

# Terminal 2 - Frontend
npm run dev
```

## Pull Request Process

1. **Create a branch** from `main` with a descriptive name:
   - `feature/add-new-agent-template`
   - `fix/workflow-execution-bug`
   - `docs/update-readme`

2. **Make your changes** following our style guidelines

3. **Test your changes**:
   ```bash
   # Backend tests — 591 passing, 18 skipped
   cd backend
   .venv/bin/python -m pytest \
     --ignore=tests/test_neo4j_document_enrichment.py \
     --ignore=tests/test_pageindex_full_content_loader.py

   # Frontend (ensure it builds)
   npm run build
   ```

4. **Commit your changes** with clear, descriptive messages:
   ```
   Add new SQL analysis agent template

   - Added SQLAnalysisAgent with query optimization capabilities
   - Includes support for PostgreSQL and MySQL dialects
   - Added unit tests for query parsing
   ```

5. **Push to your fork** and create a pull request

6. **Fill out the PR template** describing:
   - What changes you made
   - Why you made them
   - How to test them

7. **Address review feedback** if requested

### PR Requirements

- All tests must pass
- Code should follow the style guidelines
- Documentation should be updated if needed
- Commits should be atomic and well-described

## Style Guidelines

### Python (Backend)

- Follow PEP 8
- Use type hints
- Maximum line length: 100 characters
- Use docstrings for functions and classes

```python
def process_workflow(
    workflow_id: str,
    config: WorkflowConfig,
    timeout: int = 300
) -> WorkflowResult:
    """
    Process a workflow execution.

    Args:
        workflow_id: Unique identifier for the workflow
        config: Workflow configuration object
        timeout: Maximum execution time in seconds

    Returns:
        WorkflowResult containing execution output and metrics
    """
    ...
```

### TypeScript (Frontend)

- Use TypeScript strict mode
- Prefer functional components with hooks
- Use descriptive variable names
- Export types/interfaces

```typescript
interface WorkflowNodeProps {
  id: string;
  data: NodeData;
  onUpdate: (id: string, data: Partial<NodeData>) => void;
}

export const WorkflowNode: React.FC<WorkflowNodeProps> = ({
  id,
  data,
  onUpdate
}) => {
  // ...
};
```

### Git Commits

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Keep first line under 72 characters
- Reference issues when applicable: `Fix #123`

## Reporting Bugs

When reporting bugs, please include:

1. **Description** - Clear description of the bug
2. **Steps to reproduce** - How to trigger the bug
3. **Expected behavior** - What should happen
4. **Actual behavior** - What actually happens
5. **Environment** - OS, browser, Node/Python versions
6. **Screenshots/logs** - If applicable

Use the bug report issue template when available.

## Suggesting Features

When suggesting features:

1. **Check existing issues** - Your idea may already be proposed
2. **Describe the problem** - What problem does this solve?
3. **Describe the solution** - How should it work?
4. **Consider alternatives** - What other approaches exist?
5. **Additional context** - Mockups, examples, etc.

Use the feature request issue template when available.

## Questions?

If you have questions, feel free to:
- Open a GitHub Discussion
- Check existing issues and discussions
- Review the documentation

Thank you for contributing to LangConfig!

