"""
Migration v2: enable 'card' as a valid source_type in corpus_chunks and
drop the unused `cards` table.

Idempotent: safe to re-run. Uses information_schema to detect the constraint
state before mutating.

What this script does:
  1. DROP the current source_type CHECK constraint (which excludes 'card').
  2. ADD a new constraint that adds 'card' to the allowed set.
  3. DROP the legacy `cards` table — created in migration 001 but never used.
"""
from dotenv import load_dotenv
load_dotenv()
import os
import sys

import psycopg2

_ALLOWED_SOURCE_TYPES = (
    "rulebook",
    "errata",
    "tournament_rules",
    "patch_notes",
    "rules_faq",
    "card",
)


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            # 1. Drop existing constraint (if present)
            cur.execute(
                "ALTER TABLE corpus_chunks DROP CONSTRAINT IF EXISTS corpus_chunks_source_type_check"
            )
            print("Dropped existing source_type CHECK constraint (if it existed).")

            # 2. Re-add with 'card' included
            placeholders = ", ".join(["%s"] * len(_ALLOWED_SOURCE_TYPES))
            cur.execute(
                f"""
                ALTER TABLE corpus_chunks
                ADD CONSTRAINT corpus_chunks_source_type_check
                CHECK (source_type IN ({placeholders}))
                """,
                _ALLOWED_SOURCE_TYPES,
            )
            print(f"Added new constraint allowing: {_ALLOWED_SOURCE_TYPES}")

            # 3. Drop unused `cards` table (D7 — see plan)
            cur.execute("DROP TABLE IF EXISTS cards")
            print("Dropped unused `cards` table.")

        conn.commit()
        print("\nMigration complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
