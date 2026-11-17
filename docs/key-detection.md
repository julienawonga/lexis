<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Key detection against a known schema

Ingestion reads primary and foreign keys from the source database
(`get_pks` / `get_fks` in `auto_ontology/connectors/`). This check pins what
those functions must return for the fixture databases, so a connector change
that loses or invents a key fails CI by name.

## What is compared

Three sources, which must agree:

1. **The fixture SQL.** `dev_tools/fixtures/declared_keys.py` reads the declared
   `PRIMARY KEY` and `FOREIGN KEY` constraints from `pagila.sql` +
   `pagila_analytics.sql`, `chinook.sql` and `rentals.sql` as text.
2. **The golden**, `dev_tools/fixtures/golden/declared_keys.json`. A test fails
   when it differs from (1), so a fixture edited without its golden is caught.
   Counts (pagila 17 primary and 24 foreign keys, chinook 11 and 11, rentals 12
   and 16) were also read off the SQL by hand and are asserted separately, so a
   parser bug cannot hide in both.
3. **The connectors**, on a live database: Postgres (`pagila`, in the CI service;
   `rentals`, loaded into a throwaway database) and SQLite (`chinook`,
   `rentals`).

Tests: `dev_tools/fixtures/tests/test_declared_keys.py`. The failure message
lists each key as `MISSING foreign key public.rental.staff_id -> public.staff.staff_id`,
`EXTRA primary key ...` or `DIFFERENT primary key ...`. The Postgres cases run
in the existing CI Postgres job and skip without a server (locally); the SQLite
cases and the SQL-versus-golden cases run everywhere.

Keys on partitioned tables are reported under the partitioned root (the only
name the catalog lists): Pagila's `payment` declares its keys on its partitions,
and `payment_p2022_07` declares no foreign key at all.

After an intentional fixture change:
`python -m dev_tools.fixtures.declared_keys --write`, then review the diff.

## What is not declared

The golden says what is declared. Its `undeclared_relations` section records,
per database, what the semantic foreign-key inference should and should not
conclude where no constraint exists. It is a documented expectation only: it
needs a model and is not tested.

- **Pagila and Chinook:** every relation is declared; nothing is expected to be
  inferred.
- **Rentals:** all 16 relations are declared, so there is no undeclared relation
  to find (the fixture is messy in other ways). Its traps are look-alike coded
  columns with no lookup table (`invoice.pay_stat`, `payment.method_cd`,
  `staff.role_cd`): an inference must not tie them to `rental_status.stat_cd`,
  whose codes (A, C, X) are not theirs. `legacy_export_log` is deliberately
  unrelated to everything.

Chinook is a SQLite fixture on the stack; Postgres-specific parts (partition
roots, the `analytics` schema, cross-schema keys) are only exercised by Pagila.
