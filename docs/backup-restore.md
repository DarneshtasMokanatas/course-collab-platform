# PostgreSQL and media backup/restore

Database rows and uploaded files form one logical backup. Take both in the same
maintenance window, store them outside the repository, encrypt them at rest,
and restrict access to authorized maintainers.

## Production backup

Load `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` from the
deployment secret manager. Set `MEDIA_ROOT` to the same absolute directory used
by Django. Do not paste passwords into command arguments or shell history.

1. Stop application writes or place the site behind a maintenance page.
2. Back up the deployed PostgreSQL database and deployed media directory:

   ```bash
   install -d -m 0700 /srv/course-collab/backups
   pg_dump \
     --host "$PGHOST" \
     --port "$PGPORT" \
     --username "$PGUSER" \
     --dbname "$PGDATABASE" \
     --format custom \
     --no-owner \
     --file /srv/course-collab/backups/course_app.dump
   tar --create --gzip \
     --file /srv/course-collab/backups/media.tar.gz \
     --directory "$MEDIA_ROOT" .
   cd /srv/course-collab/backups
   sha256sum course_app.dump media.tar.gz > backup.sha256
   sha256sum --check backup.sha256
   ```

3. Copy the dump, media archive, and checksum to encrypted off-host storage.
4. Record the UTC backup time, application commit, PostgreSQL major version,
   database name, and media path, then resume writes.

## Production restore

Restore into a new empty database and empty media directory first. Point the
application at the restored targets only after verification.

```bash
cd /srv/course-collab/backups
sha256sum --check backup.sha256
createdb \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  "$RESTORE_DATABASE"
pg_restore \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  --dbname "$RESTORE_DATABASE" \
  --no-owner \
  --exit-on-error \
  course_app.dump
install -d -m 0750 "$RESTORE_MEDIA_ROOT"
tar --extract --gzip \
  --file media.tar.gz \
  --directory "$RESTORE_MEDIA_ROOT"
```

Set a temporary `DATABASE_URL` and `MEDIA_ROOT` for the restored environment,
then run:

```bash
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py showmigrations --plan
```

Verify protected material/submission downloads, row counts, dashboards,
analytics, authentication, and file ownership before scheduling a production
cutover. Keep the original production data and the backup until the restored
system has passed acceptance checks.

## Local Compose rehearsal

The following commands are only for the repository's local Compose database
and local `media/` directory:

```bash
mkdir -p backups
docker compose exec -T db pg_dump \
  --username course_app \
  --dbname course_app \
  --format custom \
  --no-owner \
  > backups/course_app.dump
tar --create --gzip --file backups/media.tar.gz --directory media .
sha256sum backups/course_app.dump backups/media.tar.gz > backups/backup.sha256
```

Restore the rehearsal into a disposable local database, not over the only
working copy. Never restore untrusted archives or commit backup files, restored
media, database dumps, or checksums to Git.
