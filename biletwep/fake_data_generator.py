import sqlite3
import json
import random
from datetime import datetime
from faker import Faker

fake = Faker('tr_TR')  # Türkçe veri üretimi

class FakeDataGenerator:
    def __init__(self, db_name='biletwep.db'):
        self.db_name = db_name
        self.conn = None
        
    def connect(self):
        self.conn = sqlite3.connect(self.db_name)
        self.conn.row_factory = sqlite3.Row
        
    def close(self):
        if self.conn:
            self.conn.close()

    def generate_users(self, count=50):
        if not self.conn: self.connect()
        cursor = self.conn.cursor()
        
        print(f"👥 {count} adet sahte kullanıcı oluşturuluyor...")
        added = 0
        
        possible_interests = ["Konser", "Rock", "Caz", "Tiyatro", "Sinema", "Aksiyon", 
                              "Macera", "Festival", "Teknoloji", "Sergi", "Spor"]
        
        for _ in range(count):
            try:
                name = fake.name()
                email = fake.unique.email()
                password = "pbkdf2:sha256:..." # Fake hash
                interests = random.sample(possible_interests, k=random.randint(2, 5))
                
                cursor.execute('''
                    INSERT INTO users (name, email, password, interests)
                    VALUES (?, ?, ?, ?)
                ''', (name, email, password, json.dumps(interests)))
                added += 1
            except Exception as e:
                pass # Muhtemelen email duplicate
                
        self.conn.commit()
        print(f"✅ {added} kullanıcı eklendi!")

    def generate_realistic_interactions(self, interaction_count=500):
        """
        Gerçekçi etkileşim verileri üretir:
        - Kullanıcıların ilgi alanlarına uygun etkinliklere tıklama olasılığı daha yüksektir.
        - Popüler etkinlikler daha fazla etkileşim alır.
        """
        if not self.conn: self.connect()
        cursor = self.conn.cursor()
        
        print(f"🎯 {interaction_count} adet gerçekçi etkileşim oluşturuluyor...")
        
        users = cursor.execute("SELECT id, interests FROM users").fetchall()
        events = cursor.execute("SELECT id, name, category_id, venue_name FROM events").fetchall()
        
        if not users or not events:
            print("❌ Yeterli kullanıcı veya etkinlik yok!")
            return

        actions = ['like', 'click', 'like', 'dislike', 'click']
        category_map = {
            'Konser': ['Müzik', 'Konser', 'Rock', 'Pop', 'Caz'],
            'Tiyatro': ['Sahne', 'Tiyatro', 'Gösteri'],
            'Sinema': ['Film', 'Sinema'],
            'Spor': ['Maç', 'Spor', 'Futbol']
        }

        stats = {'like': 0, 'dislike': 0, 'click': 0}
        
        for _ in range(interaction_count):
            user = random.choice(users)
            user_interests = []
            try:
                user_interests = json.loads(user['interests'])
            except:
                pass
                
            # İlgi alanına uygun etkinlik seçme olasılığını artır
            candidate_event = random.choice(events)
            
            # Etkinlik kullanıcının ilgisini çekiyor mu?
            score = 0
            evt_name = candidate_event['name']
            
            for intr in user_interests:
                if intr in evt_name: 
                    score += 5
                # Kategori eşleşmesi (basit)
                if intr in category_map:
                    for keyword in category_map[intr]:
                        if keyword in evt_name:
                            score += 3
            
            # Eğer ilgi alanı eşleşiyorsa, etkileşim şansı artar
            # Rastgelelik de olsun
            if score > 0 or random.random() < 0.3:
                action = random.choice(actions)
                
                # Eğer sevmediği bir şeyse (rastgele ama düşük ihtimal)
                if score == 0 and random.random() < 0.1:
                    action = 'dislike'
                
                try:
                    cursor.execute('''
                        INSERT INTO interactions (user_id, event_id, action, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (user['id'], candidate_event['id'], action, datetime.now()))
                    stats[action] += 1
                except:
                    pass
        
        self.conn.commit()
        
        total = sum(stats.values())
        print(f"✅ {total} etkileşim eklendi!")
        print("📊 ETKİLEŞİM İSTATİSTİKLERİ:")
        if total > 0:
            print(f"  ❤️  Beğeni:    {stats['like']} (%{stats['like']/total*100:.1f})")
            print(f"  👎 Beğenmeme: {stats['dislike']} (%{stats['dislike']/total*100:.1f})")
            print(f"  👀 Görüntüleme: {stats['click']} (%{stats['click']/total*100:.1f})")

    def boost_user_profile(self, email, interaction_count=100):
        """
        Belirli bir kullanıcıyı hedef alarak ona yoğun veri ekler.
        """
        if not self.conn: self.connect()
        cursor = self.conn.cursor()
        
        print(f"🚀 Boosting profile for: {email} with {interaction_count} interactions...")
        
        user = cursor.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            print(f"❌ User {email} not found!")
            return

        user_interests = []
        try:
            user_interests = json.loads(user['interests'])
        except:
            pass
            
        events = cursor.execute("SELECT id, name, category_id, venue_name FROM events").fetchall()
        if not events:
            print("❌ No events found.")
            return
            
        actions = ['like', 'click', 'like', 'like', 'dislike']
        added = 0
        
        for _ in range(interaction_count):
            event = random.choice(events)
            
            # İlgi alanına göre ağırlık
            is_interested = any(intr in event['name'] for intr in user_interests)
            
            action = random.choice(actions)
            if is_interested and random.random() < 0.7:
                 action = 'like' # İlgi alanıysa %70 like
            
            try:
                cursor.execute('''
                    INSERT INTO interactions (user_id, event_id, action, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (user['id'], event['id'], action, datetime.now()))
                added += 1
            except:
                pass
                
        self.conn.commit()
        print(f"✅ Added {added} interactions to {email}!")

if __name__ == "__main__":
    print("🚀 SAHTE VERİ ÜRETİMİ BAŞLIYOR")
    print("===========================================")
    
    generator = FakeDataGenerator()
    try:
        # 1. Kullanıcılar (Eğer azsa ekle)
        generator.generate_users(count=10) 
        
        # 2. Genel Etkileşimler
        generator.generate_realistic_interactions(interaction_count=200)
        
        # 3. HEDEF KULLANICIYI GÜÇLENDİR
        target_email = 'salmanmehmetsiyar@gmail.com'
        generator.boost_user_profile(target_email, interaction_count=150)
        
        print("\n✅ VERİ ÜRETİMİ TAMAMLANDI!")
        
    finally:
        generator.close()
