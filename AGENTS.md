# AGENTS.md

Repository-level rules for coding agents working on Gal/VN Radar.

- Keep the architecture simple and maintainable.
- SQLite first. Do not introduce PostgreSQL without a concrete requirement.
- No frontend, authentication, user accounts, Redis, Kubernetes, microservices, or job queues unless explicitly requested.
- Prefer official APIs or RSS feeds over scraping.
- Every external information source must implement `SourceAdapter`.
- Do not leak source-specific response structures into downstream business logic.
- External API interactions require fixture- or mock-based tests.
- Never send real notifications during automated tests.
- Telegram notification rendering must use natural Taiwan Traditional Chinese (`zh-TW`).
- Source code, tests, logs, comments, and developer documentation must remain in English.
- Never silently swallow external API errors. Convert them to explicit, actionable failures or log them with context.
- Never log credentials or API tokens.
- Do not execute content received from external sources.
- Run the full tests and Ruff before completing a task.

## Development commands

```bash
uv sync
uv run pytest
uv run ruff check .
uv run python -m gal_radar.main fetch --dry-run --config config.yaml
uv run python -m gal_radar.main fetch --config config.yaml
```
