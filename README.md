# Course Collaboration Platform

A server-rendered Django 5.2 LTS modular monolith for student/instructor course
workspaces. PostgreSQL is authoritative for academic metadata and immutable
version history; uploaded bytes live in protected file storage.

## WSL requirements

- WSL2 Ubuntu with the repository stored in the Linux filesystem
- Python 3.13 managed by `uv`
- Docker Desktop/Engine with Compose
- PostgreSQL 18 through the included Compose service

## Local setup

```bash
cp .env.example .env
# Replace DJANGO_SECRET_KEY with a long random local value.
uv sync
docker compose up -d db
docker compose ps
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

Open <http://127.0.0.1:8000/>. `seed_demo` is idempotent and prints the
non-production demo password. Never run it against production or reuse its
credentials.

## Migrations

Create forward-only migrations after model changes, inspect them, and test them
against PostgreSQL:

```bash
uv run python manage.py makemigrations
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run python manage.py showmigrations --plan
```

Do not edit a shared applied migration.

## Test and quality workflow

Start PostgreSQL, then run:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test
```

Tests use a PostgreSQL test database. They do not support a SQLite fallback.

## Production configuration

Set secrets in the deployment environment, not in tracked files:

```text
DJANGO_SECRET_KEY=<long random secret>
DJANGO_ENVIRONMENT=production
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=courses.example.edu
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
DJANGO_TIME_ZONE=Asia/Kuala_Lumpur
MEDIA_ROOT=/srv/course-collab/media
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=true
DJANGO_SECURE_HSTS_PRELOAD=false
DJANGO_TRUST_PROXY_HEADERS=true
DJANGO_CSRF_TRUSTED_ORIGINS=https://courses.example.edu
```

Only enable proxy-header trust when a controlled reverse proxy removes incoming
forwarded headers and sets `X-Forwarded-Proto`. Confirm HTTPS before enabling
HSTS; enable preload only after the whole domain is ready.

Collect static assets and run the WSGI application behind an HTTPS reverse
proxy:

```bash
uv sync --frozen --no-dev
uv run python manage.py migrate --noinput
uv run python manage.py collectstatic --noinput
uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

The reverse proxy must not expose `MEDIA_ROOT`. All academic downloads are
authorized and streamed by Django.

## Deployment verification

With the production environment loaded:

```bash
uv lock --check
uv run python manage.py check
uv run python manage.py check --deploy
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py showmigrations --plan
```

Then verify login, owner/student authorization, CSRF-protected mutations,
protected downloads, dashboard/analytics pages, static assets, UTC storage and
`Asia/Kuala_Lumpur` display, HTTPS redirects, secure cookies, and backup
restore.

## Backup and restore

Back up PostgreSQL and `MEDIA_ROOT` together. Follow the tested commands and
rehearsal checklist in [docs/backup-restore.md](docs/backup-restore.md).

## Repository hygiene

`.env`, local uploads, collected static files, test coverage, caches, database
dumps, archives, and backup checksums are ignored. Only `media/.gitkeep` may be
tracked under `media/`. Before delivery:

```bash
git status --short
git ls-files
find media -type f -not -name .gitkeep
```

Do not commit real student information, uploaded coursework, local databases,
logs, temporary files, or secrets.
