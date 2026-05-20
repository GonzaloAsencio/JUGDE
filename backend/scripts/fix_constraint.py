from dotenv import load_dotenv
load_dotenv()
import os, psycopg2

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("ALTER TABLE corpus_chunks DROP CONSTRAINT corpus_chunks_source_type_check")
cur.execute("""
    ALTER TABLE corpus_chunks ADD CONSTRAINT corpus_chunks_source_type_check
    CHECK (source_type IN ('rulebook', 'errata', 'tournament_rules', 'patch_notes', 'rules_faq'))
""")
conn.commit()
print("Constraint updated")
conn.close()
