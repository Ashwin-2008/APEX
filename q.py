import sqlite3 
conn = sqlite3.connect(\"mistiq.db\") 
cur = conn.cursor() 
cur.execute(\"SELECT COUNT(*) FROM reviewed_projects\") 
print(\"projects:\", cur.fetchone()[0]) 
