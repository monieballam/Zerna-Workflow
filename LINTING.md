# Linting and Formatting Guide

This document describes the linting and formatting setup for the Zerna Platform monorepo.

## Overview

The project uses different tools for Python and TypeScript/JavaScript code:

- **Python**: Ruff (linting + formatting)
- **TypeScript/JavaScript**: ESLint + Prettier
- **Pre-commit hooks**: Husky + lint-staged

## Python Linting (Ruff)

### Configuration

Ruff is configured in the root `pyproject.toml` file and applies to all Python code in:

- `apps/api/`
- `services/`
- `methods/`
- `workflows/`
- `packages/contracts/`

### Rules

The configuration enables:

- `E`, `W`: pycodestyle errors and warnings
- `F`: pyflakes
- `I`: isort (import sorting)
- `B`: flake8-bugbear
- `C4`: flake8-comprehensions
- `UP`: pyupgrade
- `ARG`: flake8-unused-arguments
- `SIM`: flake8-simplify

### Commands

```bash
# Check all Python files
pnpm lint:py
# or
uv run ruff check .

# Auto-fix issues
uv run ruff check . --fix

# Format Python code
pnpm format:py
# or
uv run ruff format .
```

## TypeScript/JavaScript Linting (ESLint + Prettier)

### Configuration

- **ESLint**: `eslint.config.mjs` (flat config format)
- **Prettier**: `.prettierrc`

ESLint uses:

- TypeScript ESLint recommended rules
- Prettier integration for consistent formatting

### Commands

```bash
# Lint TypeScript/JavaScript files
pnpm lint:js
# or
eslint .

# Auto-fix issues
eslint . --fix

# Format with Prettier
pnpm format:js
# or
prettier --write .
```

## Pre-commit Hooks

Pre-commit hooks are configured using Husky and lint-staged to automatically lint and format code before commits.

### Setup

After cloning the repository, install dependencies:

```bash
pnpm install
```

This will automatically set up Husky hooks via the `prepare` script.

### What Gets Checked

On every commit, lint-staged will:

1. **TypeScript/JavaScript files** (`*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.mjs`):
   - Run ESLint with auto-fix
   - Format with Prettier

2. **JSON/Markdown/YAML files** (`*.json`, `*.md`, `*.yml`, `*.yaml`):
   - Format with Prettier

3. **Python files** (`*.py`):
   - Run Ruff check with auto-fix
   - Format with Ruff

### Bypassing Hooks

If you need to bypass pre-commit hooks (not recommended):

```bash
git commit --no-verify
```

## Turbo Integration

Linting and formatting tasks are integrated with Turborepo for efficient monorepo operations:

```bash
# Run lint across all workspaces
pnpm lint

# Run format across all workspaces
pnpm format
```

## CI/CD Integration

In CI/CD pipelines, run linting without auto-fix to ensure code quality:

```bash
# Python
uv run ruff check .

# TypeScript/JavaScript
eslint .
prettier --check .
```

## Editor Integration

### VS Code

Install the following extensions:

- [Ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff)
- [ESLint](https://marketplace.visualstudio.com/items?itemName=dbaeumer.vscode-eslint)
- [Prettier](https://marketplace.visualstudio.com/items?itemName=esbenp.prettier-vscode)

Add to `.vscode/settings.json`:

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll": "explicit",
      "source.organizeImports": "explicit"
    }
  },
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.eslint": "explicit"
    }
  },
  "[javascript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.eslint": "explicit"
    }
  }
}
```

### PyCharm/IntelliJ

1. Enable Ruff:
   - Settings → Tools → Ruff
   - Check "Use Ruff"
   - Set path to `uv run ruff`

2. Enable Prettier:
   - Settings → Languages & Frameworks → JavaScript → Prettier
   - Set Prettier package path
   - Check "On save"

## Troubleshooting

### Ruff not found

Ensure you have uv installed and dependencies synced:

```bash
uv sync
```

### ESLint/Prettier not found

Ensure pnpm dependencies are installed:

```bash
pnpm install
```

### Pre-commit hooks not running

Re-initialize Husky:

```bash
pnpm prepare
```

Make sure the `.husky/pre-commit` file is executable:

```bash
chmod +x .husky/pre-commit
```
