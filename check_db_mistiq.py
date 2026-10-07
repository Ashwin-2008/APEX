import sqlite3

conn = sqlite3.connect("mistiq.db")
tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
print("tables:", tables)
for table in ("reviewed_projects", "project_reviews", "project_findings"):
    if table in tables:
        print(table, conn.execute(f"select count(*) from {table}").fetchone()[0])
        for row in conn.execute(f"select * from {table} limit 5"):
            print("  ", row)
