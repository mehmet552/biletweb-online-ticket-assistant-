import sqlite3
import json

DB_NAME = 'biletwep.db'
TARGET_EMAIL = 'salmanmehmetsiyar@gmail.com'

def check_user():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print(f"🔍 Checking data for: {TARGET_EMAIL}")
    
    user = cursor.execute("SELECT * FROM users WHERE email = ?", (TARGET_EMAIL,)).fetchone()
    
    if not user:
        print("❌ User NOT found!")
        return
        
    print(f"✅ User ID: {user['id']}")
    print(f"📋 Interests: {user['interests']}")
    
    count = cursor.execute("SELECT COUNT(*) as c FROM interactions WHERE user_id = ?", (user['id'],)).fetchone()['c']
    print(f"❤️ Interaction Count: {count}")
    
    # Show last 5 interactions
    rows = cursor.execute('''
        SELECT i.action, e.name, i.timestamp 
        FROM interactions i 
        JOIN events e ON i.event_id = e.id 
        WHERE i.user_id = ? 
        ORDER BY i.timestamp DESC 
        LIMIT 5
    ''', (user['id'],)).fetchall()
    
    print("\n🕒 Last 5 Interactions:")
    for row in rows:
        print(f" - {row['action']} on '{row['name']}' at {row['timestamp']}")
        
    conn.close()

if __name__ == '__main__':
    check_user()
