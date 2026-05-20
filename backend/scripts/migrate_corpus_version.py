from dotenv import load_dotenv
load_dotenv()
import os, psycopg2

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM corpus_chunks WHERE corpus_version = 'v1.2.0'")
count = cur.fetchone()[0]
print(f"Chunks en v1.2.0: {count}")

cur.execute("UPDATE corpus_chunks SET corpus_version = 'v1.3.0' WHERE corpus_version = 'v1.2.0'")
print(f"Rows actualizados: {cur.rowcount}")

conn.commit()

cur.execute("SELECT source_type, COUNT(*) FROM corpus_chunks WHERE corpus_version = 'v1.3.0' GROUP BY source_type ORDER BY source_type")
print("Corpus v1.3.0 final:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} chunks")

conn.close()
