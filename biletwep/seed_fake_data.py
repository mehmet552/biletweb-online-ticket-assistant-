import sqlite3
import json
import random
from datetime import datetime

# DB Path
DB_NAME = 'biletwep.db'
TARGET_EMAIL = 'salmanmehmetsiyar@gmail.com'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def seed_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Searching for user: {TARGET_EMAIL}...")
    
    # 1. Kullanıcıyı Bul
    user = cursor.execute("SELECT * FROM users WHERE email = ?", (TARGET_EMAIL,)).fetchone()
    
    if not user:
        print(f"❌ User not found! Please register with {TARGET_EMAIL} first.")
        conn.close()
        return

    user_id = user['id']
    print(f"✅ User found: ID {user_id}, Name: {user['name']}")

    # 2. İlgi Alanlarını Güncelle (Zengin Profil)
    new_interests = [
        "Konser", "Rock", "Caz", "Tiyatro", "Sinema", 
        "Aksiyon", "Macera", "Festival", "Teknoloji", 
        "Sergi", "Fotoğraf", "Yeme İçme", "Stand-up"
    ]
    
    cursor.execute("UPDATE users SET interests = ? WHERE id = ?", (json.dumps(new_interests), user_id))
    print(f"✅ Updated interests: {new_interests}")

    # 3. Mevcut Etkileşimleri Temizle (İsteğe bağlı, temiz sayfa için)
    # cursor.execute("DELETE FROM interactions WHERE user_id = ?", (user_id,))
    # print("🧹 Cleared old interactions.")

    # 4. Rastgele Etkinlikler Çek ve Etkileşim Ekle
    events = cursor.execute("SELECT id, name, category_id, venue_name FROM events LIMIT 100").fetchall()
    
    if not events:
        print("❌ No events found in DB to interact with.")
        conn.close()
        return

    print("🎲 Generating fake interactions...")
    
    actions = ['like', 'click', 'like', 'like', 'click'] # Ağırlıklı olarak 'like'
    
    # Simüle edilecek etkileşim sayısı
    count = 0
    for event in events:
        # %40 şansla bu etkinlikle etkileşime girsin
        if random.random() < 0.4:
            action = random.choice(actions)
            try:
                cursor.execute('''
                    INSERT INTO interactions (user_id, event_id, action, timestamp) 
                    VALUES (?, ?, ?, ?)
                ''', (user_id, event['id'], action, datetime.now()))
                count += 1
            except Exception as e:
                # Muhtemelen duplicate hatası, geç
                pass
                
    conn.commit()
    conn.close()
    
    print(f"✅ Successfully added {count} new interactions to profile.")
    print("🚀 Recommendation engine should now have plenty of data to work with!")

if __name__ == '__main__':
    seed_data()
