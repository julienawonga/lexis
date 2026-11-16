<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Backup, restore and rollback

Everything Lexis knows lives in one PostgreSQL database. Back it up before every
upgrade, and on a schedule that matches how much curation work you can afford to
lose.

The commands below are for the Docker Compose stack, where the Postgres
container is named `postgres` and the database `auto_ontology`. With another
setup, use the same `pg_dump` and `pg_restore` calls against your own server.

## What to back up

| What | Where | Why |
|---|---|---|
| The Lexis database | database `auto_ontology` (`POSTGRES_DATABASE`), all schemas | `public` holds the catalog, the Terms, metrics, domains, settings and the migration revision; `vdb` holds the embeddings (the semantic index); `frontend` holds users, sessions, conversations and API tokens |
| The configuration | your `.env` file | secrets and model settings are not in the database |

Not needed: the pgAdmin volume, and the images (rebuild them or keep their tags).

Not included: **your source databases.** Lexis reads them and never stores
their rows, apart from the optional value index. Back them up with their own
tools.

Two things to know about the dump:

- **It contains credentials.** Unless Vault is configured, the passwords of the
  connected databases are stored unencrypted in the catalog (see
  [connections.md](./connections.md)), and so they are in the dump. It also
  holds password hashes and API-token hashes. Store it like a secret.
- **The embeddings can be rebuilt, the rest cannot.** If only `vdb` is lost,
  `POST /api/semantic-compilation/reindex` rebuilds it at the price of the
  embedding calls. Terms, certified definitions, domains and conversations
  exist nowhere else.

## Back up

```bash
docker exec postgres pg_dump -U postgres -Fc -d auto_ontology -f /tmp/lexis.dump
docker cp postgres:/tmp/lexis.dump ./lexis-$(date +%F).dump
docker exec postgres rm /tmp/lexis.dump
```

Replace `postgres` after `-U` with your `POSTGRES_USER` if you changed it. The
custom format (`-Fc`) is compressed and lets `pg_restore` restore selectively.
The stack can stay up: `pg_dump` takes a consistent snapshot.

Keep the dump outside the repository checkout and outside the Docker volume.

## Check a backup

A backup that was never restored is a hope, not a backup. This restores it into
a throwaway container and leaves the running stack alone:

```bash
docker run -d --name lexis-restore-test -e POSTGRES_PASSWORD=restore-test pgvector/pgvector:pg17
docker cp ./lexis-2026-11-16.dump lexis-restore-test:/tmp/lexis.dump
docker exec lexis-restore-test createdb -U postgres auto_ontology
docker exec lexis-restore-test pg_restore -U postgres -d auto_ontology --no-owner --exit-on-error /tmp/lexis.dump
docker exec lexis-restore-test psql -U postgres -d auto_ontology -Atc \
  "select version_num from alembic_version; select count(*) from term; select count(*) from vdb.semantic_layer;"
docker rm -f lexis-restore-test
```

Wait a few seconds after `docker run` for Postgres to accept connections. Use
the same image as your stack (`pgvector/pgvector:pg17`): the `vector` extension
must exist where you restore.

## Restore

This replaces the database with the dump. Everything written since the dump is
lost, so take a fresh dump first if the current state has any value.

```bash
# 1. Stop what writes to the database; leave Postgres running
docker compose stop auto-ontology ingestion-service auto-ontology-frontend

# 2. Replace the database
docker exec postgres dropdb -U postgres --if-exists auto_ontology
docker exec postgres createdb -U postgres auto_ontology
docker cp ./lexis-2026-11-16.dump postgres:/tmp/lexis.dump
docker exec postgres pg_restore -U postgres -d auto_ontology --no-owner --exit-on-error /tmp/lexis.dump
docker exec postgres rm /tmp/lexis.dump

# 3. Start again with images that match the dump's revision
docker compose up -d --no-build
curl http://localhost:3001/api/health
```

The health answer must say `"migrations": {"status": "ok"}`. If the images are
newer than the dump, the migration job upgrades the restored database on start.
If they are older, see below.

## Rolling back an upgrade

Before every upgrade:

```bash
docker tag auto-ontology:latest auto-ontology:before-upgrade
docker tag auto-ontology-frontend:latest auto-ontology-frontend:before-upgrade
# and take a dump, as above
```

An upgrade may migrate the database. **An older image then refuses to start on
the newer database**: the API checks that the database is at exactly the
revision it was built for. Its message suggests `alembic upgrade head`, which is
the wrong direction for a rollback. Two ways back:

1. **Restore the dump taken before the upgrade** (above), then start the
   `before-upgrade` images. This is the safe path: it also undoes what the web
   app's own schema step changed, which has no downgrade.
2. **Downgrade the schema from the newer image**, then start the older one:
   `docker compose run --rm --entrypoint alembic auto-ontology-migrate downgrade <revision>`
   (the image's own entrypoint only knows `upgrade head`).
   Only for the API's schema, only when you know the revision the older image
   expects, and it drops whatever the newer migrations added.

## What was tried

On 2026-11-16, on the maintainer's local stack (20 connected databases, 1,274
Terms, 7,364 index rows): the dump command produced a 34 MB file in a few
seconds with the stack running; the check above restored it in 6 seconds; all
61 tables of the three schemas had the same row counts as the live database,
except one history table that had gained a row since the dump, and the
migration revision matched.

Not tried: the in-place restore on a running stack (steps 1 to 3 above, written
from the checked commands), the Alembic downgrade path, a restore across
PostgreSQL major versions, and Kubernetes (the Helm chart ships no backup job;
use your cluster's own).
