import sqlite3

conn = sqlite3.connect("mistiq.db")
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM reviewed_projects")
print("projects:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM project_reviews")
print("reviews:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM project_findings")
print("findings:", cur.fetchone()[0])
for row in cur.execute("SELECT category, COUNT(*) FROM project_findings GROUP BY category ORDER BY COUNT(*) DESC"):
    print(" ", row[0], row[1])
for row in cur.execute("SELECT project_id, COUNT(*) FROM project_reviews GROUP BY project_id ORDER BY project_id"):
    print(" ", "project", row[0], row[1], "reviews")