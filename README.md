# Course Collaboration Platform

Phase 1 provides the Django modular-monolith foundation, PostgreSQL schema,
custom user model, administration, base templates, and deterministic demo data.

## Local setup (WSL)

```bash
cp .env.example .env
# Replace DJANGO_SECRET_KEY in .env before using the application.
uv sync
docker compose up -d db
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

The application is available at <http://127.0.0.1:8000/>. Demo accounts use
the password printed by `seed_demo`; change it before sharing any environment.

## Quality checks

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test
```
