"""
Backup de la tabla corpus_chunks a un archivo CSV restaurable.

Vuelca TODA la tabla (todas las corpus_version, incluido el embedding) vía
COPY ... TO STDOUT WITH CSV HEADER. El archivo queda en backend/backups/ con
timestamp. Read-only sobre la DB: no muta nada.

Restore (manual, cuando haga falta):
    COPY corpus_chunks FROM '<archivo>' WITH CSV HEADER;
    -- previo TRUNCATE corpus_chunks; si querés reemplazo total.

Uso:
    python -m scripts.backup_corpus
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
BACKUP_DIR = Path("backups")


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurada en .env")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = BACKUP_DIR / f"corpus_chunks_{ts}.csv"

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM corpus_chunks")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT corpus_version, COUNT(*) FROM corpus_chunks "
                "GROUP BY corpus_version ORDER BY corpus_version"
            )
            by_version = cur.fetchall()

        print(f"Tabla corpus_chunks: {total} filas")
        for ver, n in by_version:
            print(f"  {ver}: {n}")

        with conn.cursor() as cur, open(out_path, "w", encoding="utf-8", newline="") as f:
            cur.copy_expert("COPY corpus_chunks TO STDOUT WITH CSV HEADER", f)
    finally:
        conn.close()

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\nBackup OK -> {out_path} ({size_mb:.1f} MB, {total} filas)")


if __name__ == "__main__":
    main()
