# biletweb-online-ticket-assistant-
BiletWep: Yapay zeka destekli, kişiselleştirilmiş etkinlik keşif ve topluluk platformu. Şehrindeki en iyi konser, tiyatro ve filmleri keşfet, yapay zeka küratörü ile sana özel "Şanslı İkili" önerileri al! 🚀🎬🎭

# BiletWep Teknik Dokümantasyonu

**BiletWep**, kullanıcıların şehirdeki etkinlikleri keşfetmesini, ilgi alanlarına göre kişiselleştirilmiş öneriler almasını ve toplulukla etkileşime geçmesini sağlayan yapay zeka destekli bir web platformudur.

---

## 1. Teknoloji Yığını (Tech Stack)

### Backend
- **Dil**: Python 3.x
- **Framework**: Flask (Web Sunucusu ve Routing)
- **Veritabanı**: SQLite (Yerel ilişkisel veritabanı)
- **ORM/Sorgulama**: Standart SQL (`sqlite3` kütüphanesi ile)
- **Konfigürasyon**: `python-dotenv` (Çevresel değişken yönetimi)
- **AI Entegrasyonu**: Google Gemini API (`google-generativeai`)

### Frontend
- **Şablon Motoru**: Jinja2 (Flask entegreli)
- **Stil Kütüphanesi**: Tailwind CSS (CDN üzerinden kullanım)
- **Scripting**: Vanilla JavaScript (AJAX, DOM manipülasyonu)

### Veri Bilimi ve Makine Öğrenmesi
- **Kütüphaneler**: scikit-learn, pandas, numpy
- **Algoritmalar**: TF-IDF Vektörizasyonu, Cosine Similarity (Kosinüs Benzerliği)

### Dış Servisler (APIs)
- **Etkinlik.io**: Genel etkinlik verileri (Konser, Tiyatro, Festival vb.)
- **TMDB (The Movie DB)**: Vizyondaki filmler ve sinema verileri.
- **Google Gemini**: "Şanslı İkili" (Smart Pair) analizi ve yorumlama.

---

## 2. Proje Mimarisi

Proje, MVC (Model-View-Controller) benzeri bir yapıda kurgulanmıştır:

- **View (Frontend)**: `templates/` klasöründeki HTML dosyaları. Kullanıcı arayüzünü oluşturur.
- **Controller (Backend)**: `app.py` içerisindeki route fonksiyonları. İstekleri karşılar, veritabanından veri çeker ve şablonları render eder.
- **Services (Mantık Katmanı)**: `recommendations.py`, `sync_service.py` ve `ai_services.py` dosyaları iş mantığını (Business Logic) barındırır.

### Dosya Yapısı
```
biletwep/
├── app.py                  # Ana uygulama dosyası (Routes, DB Bağlantısı)
├── recommendations.py      # Öneri motoru algoritmaları
├── sync_service.py         # Dış API'lerden veri çekme ve kaydetme servisi
├── ai_services.py          # Google Gemini AI entegrasyonu
├── services.py             # Yardımcı servisler (örn: TMDB istekleri)
├── biletwep.db             # SQLite veritabanı dosyası
├── templates/              # HTML şablonları (Login, Dashboard, Community vb.)
└── static/                 # CSS, JS, Resimler ve Uploads klasörü
```

---

## 3. Temel Bileşenler ve İşleyiş

### A. Veri Senkronizasyonu (`sync_service.py`)
Platformun verileri canlı ve güncel tutması için harici kaynaklardan veri çeken bir servistir.
- **Görev**: Etkinlik.io ve TMDB API'lerine bağlanarak etkinlikleri çeker.
- **İşleyiş**: Çekilen veriler `raw_data` (JSON) formatında ve ayrıştırılmış sütunlar (tarih, mekan, kategori) halinde `events` tablosuna kaydedilir.
- **Tetiklenme**: Yönetici paneli veya uygulama başlangıcında (`app.py` -> `admin_sync` veya otomatik kontrol) çalışır.

### B. Öneri Motoru (`recommendations.py`)
Kullanıcıya özel etkinlikler sunan çekirdek modüldür.
- **Filtreleme**: Kullanıcının seçtiği ilgi alanlarına (Sinema, Konser vb.) göre `events` tablosunu sorgular. Geçmiş etkinlikler (`start_date < today`) otomatik olarak filtrelenir.
- **Şanslı İkili (Smart Pair)**: Rastgele ancak birbiriyle uyumlu olabilecek iki farklı etkinliği seçer (Örn: Bir konser ve ardından bir film).
- **Yedekleme**: Eğer yerel veritabanında yeterli etkinlik yoksa, anlık olarak API'lerden veri çekmeye çalışır.

### C. Yapay Zeka Küratörü (`ai_services.py`)
Önerilen "Şanslı İkili"nin neden iyi bir eşleşme olduğunu kullanıcılara açıklar.
- **Girdi**: Seçilen iki etkinliğin adı, türü ve zamanı.
- **İşlem**: Google Gemini modeline bir prompt gönderir ("Bu iki etkinlik neden iyi bir plan olur?").
- **Çıktı**: Eğlenceli ve ikna edici bir açıklama metni.

### D. Topluluk ve Etkileşim (`app.py` & `community.html`)
Kullanıcıların sosyalleşmesini sağlar.
- **Paylaşım**: Kullanıcılar gittikleri etkinlikler hakkında post paylaşabilir.
- **Etkileşim**: Diğer kullanıcılar bu postları beğenebilir (`likes` tablosu) veya yorum yapabilir (`comments` tablosu).
- **Entegrasyon**: Paylaşılan etkinlik isimleri, arka planda `events` tablosuyla eşleştirilir ve tıklanabilir bilet linklerine dönüştürülür.
76: 
77: ### E. Bildirim Sistemi
78: Kullanıcıları önemli gelişmelerden haberdar eder.
79: - **Türler**:
80:   - **Etkileşim**: Gönderiniz beğenildiğinde veya yorum yapıldığında bildirim gelir.
81:   - **Hatırlatma**: Takvime eklenen etkinliklerin günü geldiğinde ("Bugün yaklaşıyor") otomatik hatırlatma oluşturulur.
82: - **İşleyiş**: Backend'de tetikleyiciler (`like_post`, `comment_post`, `dashboard`) aracılığıyla `notifications` tablosuna kayıt atılır.
83: - **Arayüz**: Sidebar ve Mobil menüde okuma durumu (okundu/okunmadı) takibi yapan, kırmızı rozetli (badge) bir bildirim alanı bulunur.

---

## 4. Veritabanı Şeması (SQLite)

Ana tablolar ve görevleri:

1.  **users**: Kullanıcı bilgileri (email, şifre hash'i, ilgi alanları `JSON`).
2.  **events**: Tüm etkinliklerin tutulduğu havuz (`raw_data` tüm API yanıtını saklar).
3.  **interactions**: Kullanıcı-etkinlik etkileşimleri (beğeni, görüntüleme, "ilgilenmiyorum"). Öneri algoritmasını besler.
4.  **user_calendar**: Kullanıcının takvime eklediği etkinlikler.
5.  **posts**: Topluluk gönderileri.
6.  **comments**: Gönderilere yapılan yorumlar.
7.  **likes**: Gönderi beğenileri.
8.  **notifications**: Kullanıcı bildirimleri (mesaj, link, okundu durumu).

---

## 5. Kurulum ve Çalıştırma

Geliştirme ortamında projeyi ayağa kaldırmak için:

1.  **Bağımlılıkları Yükle**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Ortam Değişkenlerini Ayarla (.env)**:
    - `.env.example` dosyasının adını `.env` olarak değiştirin.
    - İçerisindeki API anahtarlarını (Etkinlik.io, TMDB, Gemini) kendi anahtarlarınızla güncelleyin.

3.  **Uygulamayı Başlat**:
    ```bash
    python app.py
    ```
3.  **Veritabanı**: Uygulama ilk açılışta `init_db()` fonksiyonu ile `biletwep.db` dosyasını otomatik oluşturur.

---

## 6. Güvenlik Notları
- Şifreler `werkzeug.security` kullanılarak hashlenmiş şekilde saklanır.
- Oturum yönetimi Flask `session` mekanizması ile sağlanır.
- Şifreler `werkzeug.security` kullanılarak hashlenmiş şekilde saklanır.
- Oturum yönetimi Flask `session` mekanizması ile sağlanır.
- Hassas bilgiler (API anahtarları, Secret Key) `.env` dosyasında saklanır ve `.gitignore` ile korunur.
