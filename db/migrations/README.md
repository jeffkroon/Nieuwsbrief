# Migraties (`mail`-schema)

- Handmatig toepassen op Supabase, op volgorde van het nummer. Een deploy (push op
  main) past niets toe: de code moet dus werken met het schema dat er al staat.
- De tests bouwen hun database uit deze bestanden (`backend/tests/conftest.py`), en
  `test_schema_migrations.py` controleert dat elke modelkolom in een migratie staat.
- **`mail_003` ontbreekt bewust.** Die migratie (`mail.images`, commit 5bd59e9) is
  destijds wel op productie gedraaid maar nooit in de repo gekomen. De tabel staat
  nu idempotent in `mail_016_ontbrekende_tabellen.sql`. Niet hernummeren.
