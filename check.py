import sqlite3

# Подключаемся к нашей базе
conn = sqlite3.connect('football.db')
cursor = conn.cursor()

# Берем 10 любых матчей из базы
cursor.execute('''
    SELECT t1.name, t2.name, m.home_goals, m.away_goals 
    FROM matches m
    JOIN teams t1 ON m.home_id = t1.id
    JOIN teams t2 ON m.away_id = t2.id
    LIMIT 10
''')

print("\n--- 10 СЛУЧАЙНЫХ МАТЧЕЙ ИЗ БАЗЫ ---")
for row in cursor.fetchall():
    home, away, hg, ag = row
    print(f"{home} {hg} : {ag} {away}")

conn.close()