"""Het schema uit db/migrations/ moet kloppen met de ORM-modellen.

De testdatabase wordt opgebouwd uit de migraties (zie conftest.py), niet uit
Base.metadata. Ontbreekt er in de migraties een tabel of kolom die een model wel
heeft, dan faalt deze test, in plaats van pas in productie.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.db.models import SCHEMA, Base
from tests.conftest import MAIL_TABLES, MIGRATIONS_DIR, migration_files


@pytest.mark.parametrize("table", sorted(Base.metadata.tables.values(), key=lambda t: t.name), ids=lambda t: t.name)
def test_elke_modelkolom_bestaat_in_de_database(pg_engine, table) -> None:
    inspector = inspect(pg_engine)
    assert inspector.has_table(table.name, schema=SCHEMA), (
        f"tabel {SCHEMA}.{table.name} staat in de modellen maar in geen enkele migratie"
    )
    in_db = {kolom["name"] for kolom in inspector.get_columns(table.name, schema=SCHEMA)}
    ontbrekend = {kolom.name for kolom in table.columns} - in_db
    assert not ontbrekend, f"{SCHEMA}.{table.name} mist kolommen uit het model: {sorted(ontbrekend)}"


def test_migraties_staan_op_volgorde_en_zijn_gevonden() -> None:
    bestanden = migration_files()
    assert bestanden, f"geen migraties gevonden in {MIGRATIONS_DIR}"
    assert [b.name for b in bestanden] == sorted(b.name for b in bestanden)
    assert bestanden[0].name == "mail_001_init.sql"


def test_truncate_lijst_dekt_alle_tabellen() -> None:
    """Een nieuwe tabel die niet in MAIL_TABLES staat, lekt data tussen tests."""
    modellen = {f"{SCHEMA}.{naam}" for naam in (t.name for t in Base.metadata.tables.values())}
    assert modellen == set(MAIL_TABLES)


def test_mail_016_is_veilig_opnieuw_te_draaien(pg_engine) -> None:
    """Productie heeft mail.images al; mail_016 moet daar zonder fout doorheen lopen."""
    sql = (MIGRATIONS_DIR / "mail_016_ontbrekende_tabellen.sql").read_text(encoding="utf-8")
    with pg_engine.begin() as conn:
        conn.exec_driver_sql(sql)
