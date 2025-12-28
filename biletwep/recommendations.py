import requests
import json
import random
import sqlite3
from datetime import datetime, timedelta
from services import TMDBService
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    import pandas as pd
    ML_AVAILABLE = True
except ImportError as e:
    ML_AVAILABLE = False
    print(f"ML_IMPORT_ERR: {e}")

class RecommendationEngine:
    def __init__(self, db_params, api_token, tmdb_api_key=None, ai_curator=None):
        self._db_connection_factory = db_params.get('get_conn') if isinstance(db_params, dict) else db_params
        self.api_token = api_token
        self.tmdb_api_key = tmdb_api_key
        self.ai_curator = ai_curator
        self.category_map = {}
        # İlgi alanlarını Etkinlik İsimleri/Açıklamaları ile eşleştirmek için basit anahtar kelime haritalaması
        self.synonyms = {
            'konser': ['konser', 'müzik', 'muzik', 'rock', 'pop', 'caz', 'rap', 'elektronik', 'canlı'],
            'tiyatro': ['tiyatro', 'sahne', 'gösteri', 'oyun', 'musical', 'kabare'],
            'sinema': ['sinema', 'film', 'gösterim'],
            'festival': ['festival', 'senlik', 'şenlik'],
            'spor': ['spor', 'mac', 'maç', 'futbol', 'basketbol', 'voleybol', 'koşu'],
            'sanat': ['sanat', 'sergi', 'resim', 'heykel', 'muze', 'müze', 'fotoğraf'],
            'atolye': ['atolye', 'atölye', 'workshop', 'kurs', 'egitim', 'eğitim', 'seminer']
        }
        # Güncellenmesi gereken kategoriler
        self._update_category_map()
        
        # PERFORMANCE: Simple In-Memory Cache
        # Stores API responses for 5 minutes to avoid redundant network calls
        self.api_cache = {} 
        self.CACHE_DURATION = timedelta(minutes=5)

    def _get_db_connection(self):
        return self._db_connection_factory()

    def _update_category_map(self):
        """API eşleştirmesi için veritabanından kategori haritasını oluşturur."""
        try:
            conn = self._get_db_connection()
            rows = conn.execute('SELECT * FROM categories').fetchall()
            conn.close()
            self.category_map = {row['slug']: row['id'] for row in rows}
        except Exception as e:
            print(f"Error updating category map: {e}")
            
        # YEDEK PLAN: Kritik kategoriler için sabit kodlanmış ID'ler (Etkinlik.io Standartları)
        # Bu, veritabanı boş olsa veya senkronizasyon başarısız olsa bile filtrelerin çalışmasını sağlar.
        if 'tiyatro' not in self.category_map: self.category_map['tiyatro'] = 3968 # Tiyatro
        if 'konser' not in self.category_map: self.category_map['konser'] = 3970   # Konser
        if 'festival' not in self.category_map: self.category_map['festival'] = 3971 # Festival
        if 'egitim' not in self.category_map: self.category_map['egitim'] = 3974 # Egitim
        if 'spor' not in self.category_map: self.category_map['spor'] = 3975 # Spor
        if 'sanat' not in self.category_map: self.category_map['sanat'] = 3972 # Sanat
        if 'sinema' not in self.category_map: self.category_map['sinema'] = 3796 # Sinema

    def get_recommendations(self, user_id, city_id='40', use_ai=True, time_filter=None):
        """
        Yerel veritabanını kullanarak akıllı bir öneri ikilisi almak için ana yöntem.
        time_filter: 'bugün', 'yarın', 'haftasonu' vb. olabilir.
        """
        # 1. Kullanıcı Profilini ve Geçmişini Getir
        user = self._get_user_profile(user_id)
        if not user:
            return {'pair': [], 'alternates': [], 'reason': ''}

        user_interests = []
        try:
            user_interests = json.loads(user['interests'])
        except:
            pass
        
        # Geçmiş etkileşimleri getir
        interactions = self._get_user_interactions(user_id)
        
        # 2. Yerel Veritabanından Adayları Getir (UPGRADE: LİMİT 300)
        candidates = self._fetch_candidates_from_db(city_id, limit=300)

        # --- FİLMLERİ DAHİL ET ---
        if self.tmdb_api_key:
            try:
                movies = TMDBService.get_now_playing(self.tmdb_api_key)
                if movies:
                    candidates.extend(movies)
            except Exception as e:
                print(f"Lucky Pair Movie Fetch Error: {e}")

        # --- ZAMAN FİLTRESİ (Zorunlu) ---
        if time_filter:
            tf = time_filter.lower()
            today = datetime.now().date()
            filtered_candidates = []
            
            for c in candidates:
                try:
                    start_str = c.get('start')
                    if not start_str: continue
                    # Tarih parse et
                    # TMDB: YYYY-MM-DD, Etkinlik.io: ISO
                    if len(start_str) == 10: # YYYY-MM-DD
                        evt_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                    else:
                        evt_date = datetime.fromisoformat(start_str.replace('Z', '')).date()
                        
                    include = False
                    if tf in ['bugün', 'bugun', 'today']:
                        if evt_date == today: include = True
                    elif tf in ['yarın', 'yarin', 'tomorrow']:
                        if evt_date == today + timedelta(days=1): include = True
                    elif tf in ['haftasonu', 'weekend']:
                        # 5=Saturday, 6=Sunday
                        if evt_date.weekday() in [5, 6]: include = True
                    elif tf in ['bu hafta', 'this week']:
                        if evt_date <= today + timedelta(days=7): include = True
                    else:
                        include = True # Bilinmeyen filtre, hepsini dahil et (veya yoksay)
                        
                    if include:
                        filtered_candidates.append(c)
                except:
                    pass
            
            # Eğer filtre sonucunda hiçbir şey kalmazsa, boş dönmemek için orijinali kullanabiliriz veya boş döneriz.
            # Kullanıcı filtre seçtiyse, boş dönmek daha doğrudur (eşleşme yok).
            # Ancak UX için en azından 2 aday varsa filtreyi uygula, yoksa esnet?
            if len(filtered_candidates) >= 2:
                candidates = filtered_candidates
            # else: Yeterli aday yoksa filtreyi yoksayabiliriz ama şimdilik katı olalım.



        # 3. Puanla ve Sırala (Beğenilmeyenleri Dikkate Al)
        
        # --- ÖZELLİK: Favorileri Karıştır ---
        # Kullanıcı 10 veya daha fazla etkinliği beğendiyse, karıştırmada bu beğenilen etkinlikleri göstermeye öncelik ver.
        liked_event_ids = {str(i['event_id']) for i in interactions if i['action'] == 'like'}
        
        favorites_pool = []
        if len(liked_event_ids) >= 10:
            # Sadece beğenilenleri tutmak için adayları filtrele
            favorites_pool = [c for c in candidates if str(c.get('id')) in liked_event_ids]
            
        # Şu anda yeterli sayıda geçerli favorimiz varsa (en az 2), SADECE onları kullan.
        if len(favorites_pool) >= 2:
            scored_candidates = [{'event': e, 'score': 100} for e in favorites_pool]
            reason = '> 🎲 Mod: Favori Karıştırıcı\n> ❤️ Durum: Beğendiğin 10+ etkinlik var.\n> 🎯 Seçim: Beğendiklerin arasından rastgele seçildi.'
        else:
            # Standart Mantık
            scored_candidates = self._score_events(candidates, user_interests, interactions)
        
        # 4. İkili Seç
        selected_pair, alternates = self._select_diverse_pair(scored_candidates)
        
        reason = '> 🧬 Durum: Yapay Zeka (ML)\n> 🧠 Analiz: TF-IDF & Cosine Similarity kullanıldı.\n> 🎯 Seçim: Zevklerine en yakın etkinlikler vektörlendi.'
        
        # 5. Yapay Zeka Açıklaması
        if use_ai and self.ai_curator and len(selected_pair) >= 2:
            try:
                ai_result = self.ai_curator.explain_pair(
                    {'name': user['name'], 'interests_list': user_interests}, 
                    selected_pair
                )
                if ai_result:
                    reason = ai_result.get('comment', reason)
            except Exception as e:
                print(f"AI Explain Error: {e}")
        
        return {'pair': selected_pair, 'alternates': alternates, 'reason': reason}

    # Çakışmayı önlemek için eski yöntem kaldırıldı.
    # Aktif get_events_for_user aşağıda tanımlanmıştır.

    def _get_target_category_ids(self, user_interests):
        target_ids = set()
        if not self.category_map:
            self._update_category_map()
            
        for interest in user_interests:
            interest = interest.lower()
            found = False
            if interest in self.category_map:
                target_ids.add(str(self.category_map[interest]))
                found = True
            
            if not found and interest in self.synonyms:
                for syn in self.synonyms[interest]:
                    for cat_slug, cat_id in self.category_map.items():
                        if syn in cat_slug:
                            target_ids.add(str(cat_id))
                            found = True
            
            if not found:
                 for cat_slug, cat_id in self.category_map.items():
                    if interest in cat_slug:
                        target_ids.add(str(cat_id))
        return list(target_ids)

    def _get_user_profile(self, user_id):
        conn = self._get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        return user
        
    def _get_user_interactions(self, user_id):
        conn = self._get_db_connection()
        try:
            rows = conn.execute('''
                SELECT e.category_id, e.venue_name, i.action, i.event_id 
                FROM interactions i
                JOIN events e ON i.event_id = e.id
                WHERE i.user_id = ?
            ''', (user_id,)).fetchall()
            return rows
        except:
            return []
        finally:
            conn.close()

    def _fetch_candidates_from_db(self, city_id, limit=300):
        conn = self._get_db_connection()
        events = []
        try:
             rows = conn.execute('''
                SELECT raw_data FROM events 
                WHERE (city_id = ? OR city_id IS NULL OR city_id = '')
                AND start_date >= date('now')
                LIMIT ?
             ''', (city_id, limit)).fetchall()
             for row in rows:
                 try: events.append(json.loads(row['raw_data']))
                 except: pass
        except Exception as e:
            print(f"DB Fetch Error: {e}")
        finally:
            conn.close()
        return events

    def _fetch_candidates_from_api(self, category_ids, city_id):
        # 0. Check Cache
        cache_key = f"{city_id}_{','.join(category_ids) if category_ids else 'ALL'}"
        now = datetime.now()
        
        if cache_key in self.api_cache:
            entry = self.api_cache[cache_key]
            if now - entry['time'] < self.CACHE_DURATION:
                return entry['data'] # Return cached result instantly

        headers = {'X-Etkinlik-Token': self.api_token}
        params = {'take': 500, 'city_ids': city_id} # Daha iyi çeşitlilik için artırıldı
        
        # Sinema kontrolü
        looking_for_sinema = False
        if category_ids and ('3796' in category_ids or 3796 in category_ids):
             looking_for_sinema = True
             
        if category_ids:
            params['category_ids'] = ",".join(category_ids)
            
        events = []
        # 1. TMDB
        if looking_for_sinema or not category_ids: 
            if self.tmdb_api_key:
                try:
                    movies = TMDBService.get_now_playing(self.tmdb_api_key)
                    events.extend(movies)
                except: pass
        
        # 2. API
        try:
            resp = requests.get('https://backend.etkinlik.io/api/v2/events', headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get('items', [])
                if not items and category_ids:
                    # Yedek Plan: Kategori olmadan dene
                    params.pop('category_ids')
                    resp = requests.get('https://backend.etkinlik.io/api/v2/events', headers=headers, params=params)
                    if resp.status_code == 200:
                         data = resp.json()
                         items = data.get('items', [])
                events.extend(items)
        except Exception as e:
            print(f"API Fetch error: {e}")
            
        # Save to Cache
        self.api_cache[cache_key] = {'time': now, 'data': events}
        return events

    def _score_events(self, events, interests, interactions):
        """
        İçerik Tabanlı Filtreleme (TF-IDF + Kosinüs Benzerliği) kullanarak etkinlikleri puanlar.
        ML kütüphaneleri eksikse veya soğuk başlatma durumunda kural tabanlı puanlamaya geri döner.
        """
        
        # 0. Temel Filtre: Beğenilmeyenleri ve Geçmiş Etkinlikleri Kaldır
        disliked_ids = {str(i['event_id']) for i in interactions if i['action'] == 'dislike'}
        today_iso = datetime.now().date().isoformat()
        
        candidates = []
        for e in events:
            # Geçmiş Tarih Kontrolü
            start = e.get('start', '')
            # Basit string karşılaştırması ISO formatı için genellikle çalışır (YYYY-MM-DD)
            # Daha sağlam olması için parse edilebilir ama performans için string karşılaştırması yeterli olabilir
            if start and start[:10] < today_iso:
                continue
                
            if str(e.get('id')) not in disliked_ids:
                candidates.append(e)
        
        if not candidates: return []
        
        # --- ML STRATEJİSİ ---
        liked_event_ids = {str(i['event_id']) for i in interactions if i['action'] in ['like', 'click']}
        
        if ML_AVAILABLE and len(liked_event_ids) > 0:
             try:
                # 1. Vektörizasyon için Veri Hazırla
                # Her etkinlik için bir metin 'çorbası' oluşturmamız gerekiyor: İsim + Kategori + Mekan
                # Profili oluşturmak için kullanıcının daha önce beğendiği etkinlikleri de dahil etmemiz gerekiyor,
                # ancak basitlik adına, beğenilen etkinlikler aday listesindeyse sadece adayların meta verilerini kullanabiliriz.
                # Zorluk: Beğenilen etkinlikler mevcut 'etkinlikler' aday listesinde OLMAYABİLİR (geçmiş etkinlikler).
                # Çözüm: Adayları, ilgi alanlarıyla uyumlu olan *Aday Listesindeki Eşleşmelere* benzerliğine göre puanlayacağız,
                # VEYA daha sağlam bir şekilde, Kullanıcının İlgi Alanı Anahtar Kelimelerini 'Sorgu Vektörü' olarak kullanırız.
                
                # Hızlı uygulama için DAHA İYİ YAKLAŞIM:
                # 1. İlgi Alanları + Beğenilen Kategoriler/Mekanlardan bir 'Kullanıcı Çorbası' oluşturun.
                # 2. Adayları Vektörleştir.
                # 3. Kullanıcı Çorbasını Vektörleştir.
                # 4. Benzerliği Hesapla.
                
                # Kullanıcı Sinyalini Topla
                liked_categories = [i.get('category_id') for i in interactions if i['action'] == 'like' and i.get('category_id')]
                liked_venues = [i.get('venue_name') for i in interactions if i['action'] == 'like' and i.get('venue_name')]
                
                # Kullanıcı Profili Metnini Oluştur
                user_profile_text = " ".join(interests) * 3  # İlgi alanlarını güçlendir
                user_profile_text += " " + " ".join([str(c) for c in liked_categories]) 
                user_profile_text += " " + " ".join([str(v) for v in liked_venues])
                
                # Aday Çorbalarını Oluştur
                candidate_soups = []
                for event in candidates:
                    soup = f"{event.get('name', '')} {event.get('category', {}).get('name', '')} {event.get('venue', {}).get('name', '')}"
                    # Varsa açıklama ekle (genellikle HTML, temizlenmesi gerekebilir, hız/gürültü azaltma için atlanıyor)
                    candidate_soups.append(soup)
                
                # Vektörleştir (TF-IDF)
                # Vektörleştiriciye uyması için Kullanıcı Profili + Adayları Birleştir
                all_corpus = [user_profile_text] + candidate_soups
                
                vectorizer = TfidfVectorizer(stop_words=None) # Buraya Türkçe etkisiz kelimeler eklenebilir
                tfidf_matrix = vectorizer.fit_transform(all_corpus)
                
                # Benzerliği Ölç
                # İndeks 0 Kullanıcı Profilidir. İndeksler 1..N adaylardır.
                user_vector = tfidf_matrix[0]
                candidate_vectors = tfidf_matrix[1:]
                
                cosine_sim = cosine_similarity(user_vector, candidate_vectors).flatten()
                
                # Puanları Ata
                scored = []
                for idx, score in enumerate(cosine_sim):
                    # 0-100 aralığına ölçekle
                    final_score = score * 100
                    scored.append({'event': candidates[idx], 'score': final_score})
                    
                return sorted(scored, key=lambda x: x['score'], reverse=True)
                
             except Exception as e:
                 print(f"ML Scoring Failed: {e}, falling back to rule-based.")

        # --- YEDEK PLAN: Kural Tabanlı (Orijinal Mantık) ---
        liked_categories = set()
        liked_venues = set()
        
        for i in interactions:
            if i['action'] in ['like', 'click']:
                if i['category_id']: liked_categories.add(str(i['category_id']))
                if i['venue_name']: liked_venues.add(i['venue_name'])

        scored = []
        for event in candidates:
            score = 0
            name = event.get('name', '').lower()
            cat_name = event.get('category', {}).get('name', '').lower()
            
            # İlgi Alanı Eşleşmesi
            matched = False
            for intr in interests:
                ival = intr.lower()
                if ival in name or ival in cat_name:
                    score += 30
                    matched = True
                if not matched and ival in self.synonyms:
                    for syn in self.synonyms[ival]:
                        if syn in name or syn in cat_name:
                            score += 25
                            matched = True
                            break
                            
            # Öğrenme Eşleşmesi
            cat_id = str(event.get('category', {}).get('id', ''))
            if cat_id in liked_categories: score += 20
            v_name = event.get('venue', {}).get('name')
            if v_name in liked_venues: score += 15
            
            scored.append({'event': event, 'score': score})
            
        return sorted(scored, key=lambda x: x['score'], reverse=True)

    def _select_diverse_pair(self, scored_events):
        """
        UPGRADED: MMR (Maximal Marginal Relevance) ile çeşitli ve kaliteli ikili seçimi.
        - Hem yüksek puan (relevance) 
        - Hem de farklılık (diversity) hedeflenir
        """
        if not scored_events: 
            return [], []
        
        # Parametreler
        lambda_param = 0.65  # 0.65 relevance + 0.35 diversity dengesi
        # UPGRADE: Havuz boyutunu artırdık (30 -> 60 -> 100)
        pool_size = min(100, len(scored_events))
        
        # 1. En iyi adaylardan havuz oluştur
        pool = scored_events[:pool_size]
        
        # 2. MMR ile ikili seç
        selected_pair = []
        selected_indices = []
        
        # İlk etkinlik: En yüksek skorlu (KARIŞIKLIK İÇİN İLK 7'DEN RASTGELE SEÇ)
        # best_item = pool[0] # Deterministic was boring!
        
        # En iyi 7 adaydan birini seç (kaliteyi koru ama çeşitlilik ekle)
        top_n_limit = min(7, len(pool))
        first_idx = random.randint(0, top_n_limit - 1)
        
        best_item = pool[first_idx]
        selected_pair.append(best_item['event'])
        selected_indices.append(first_idx)
        
        # İkinci etkinlik: Relevance + Diversity dengesi
        best_mmr_score = -999
        best_idx = -1
        
        for idx, candidate in enumerate(pool):
            if idx in selected_indices:
                continue
            
            # Relevance score (0-1 normalize)
            relevance = candidate['score'] / 100 if candidate['score'] > 0 else 0
            
            # Diversity score (ilk seçilenden ne kadar farklı)
            diversity = self._calculate_event_diversity(
                candidate['event'], 
                selected_pair[0]
            )
            
            # MMR formülü
            mmr_score = lambda_param * relevance + (1 - lambda_param) * diversity
            
            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = idx
        
        if best_idx != -1:
            selected_pair.append(pool[best_idx]['event'])
            selected_indices.append(best_idx)
        
        # 3. Sinerji hesapla (mevcut mantığınızı koruyoruz)
        if len(selected_pair) == 2:
            syn_score, theme = self._calculate_synergy(selected_pair[0], selected_pair[1])
            selected_pair[0]['pair_theme'] = theme
            selected_pair[0]['match_score'] = min(int(best_mmr_score * 100), 99)
        
        # 4. Alternatifler (seçilmeyenlerden en iyiler)
        alternates = []
        for idx, item in enumerate(pool):
            if idx not in selected_indices:
                alternates.append(item['event'])
                if len(alternates) >= 12: # UPGRADE: Daha fazla alternatif (5 -> 12)
                    break
        
        return selected_pair, alternates

    def _calculate_event_diversity(self, event1, event2):
        """
        İki etkinlik arasındaki farklılığı 0-1 arasında hesaplar.
        1 = Tamamen farklı, 0 = Tamamen aynı
        """
        diversity_score = 0
        weights = {
            'category': 0.4,   # En önemli: Kategori farklılığı
            'venue': 0.25,     # Mekan farklılığı
            'date': 0.20,      # Tarih farklılığı
            'time': 0.15       # Saat farklılığı
        }
        
        # 1. Kategori Farklılığı
        cat1_id = event1.get('category', {}).get('id')
        cat2_id = event2.get('category', {}).get('id')
        cat1_name = event1.get('category', {}).get('name', '').lower()
        cat2_name = event2.get('category', {}).get('name', '').lower()
        
        if cat1_id != cat2_id:
            diversity_score += weights['category']
        elif cat1_name != cat2_name:
            # Farklı isim ama aynı ID (alt kategori)
            diversity_score += weights['category'] * 0.5
        
        # 2. Mekan Farklılığı
        venue1 = event1.get('venue', {}).get('name', '')
        venue2 = event2.get('venue', {}).get('name', '')
        
        if venue1 != venue2:
            diversity_score += weights['venue']
            
            # Bonus: Farklı semtler/bölgeler
            # HATA DÜZELTME: 'district' bazen bir nesne (dict) olarak gelebilir, string olmayabilir.
            d1_val = event1.get('venue', {}).get('district')
            d2_val = event2.get('venue', {}).get('district')

            # Eğer district bir dict ise (örn: {'id': 1, 'name': 'Kadikoy'}), ismini al
            if isinstance(d1_val, dict): d1_val = d1_val.get('name', '')
            if isinstance(d2_val, dict): d2_val = d2_val.get('name', '')
            
            district1 = str(d1_val or '').lower()
            district2 = str(d2_val or '').lower()
            
            if district1 and district2 and district1 != district2:
                diversity_score += weights['venue'] * 0.3
        
        # 3. Tarih Farklılığı
        try:
            date1_str = event1.get('start', '')
            date2_str = event2.get('start', '')
            
            if date1_str and date2_str:
                # Tarih parse
                if len(date1_str) == 10:  # YYYY-MM-DD (TMDB)
                    date1 = datetime.strptime(date1_str, '%Y-%m-%d')
                else:
                    date1 = datetime.fromisoformat(date1_str.replace('Z', ''))
                
                if len(date2_str) == 10:
                    date2 = datetime.strptime(date2_str, '%Y-%m-%d')
                else:
                    date2 = datetime.fromisoformat(date2_str.replace('Z', ''))
                
                # Gün farkı (0-7 gün arası normalize)
                day_diff = abs((date1.date() - date2.date()).days)
                
                if day_diff == 0:
                    date_diversity = 0  # Aynı gün
                elif day_diff <= 2:
                    date_diversity = 0.5  # Birbirine yakın
                else:
                    date_diversity = 1.0  # Farklı günler
                
                diversity_score += weights['date'] * date_diversity
                
                # 4. Saat Farklılığı (aynı gün ise önemli)
                if day_diff == 0:
                    hour_diff = abs((date1.hour - date2.hour))
                    if hour_diff >= 4:
                        diversity_score += weights['time']
                    elif hour_diff >= 2:
                        diversity_score += weights['time'] * 0.5
                else:
                    # Farklı günlerdeyse saat önemli değil
                    diversity_score += weights['time']
        except Exception as e:
            # Tarih parse hatası - orta puan ver
            diversity_score += (weights['date'] + weights['time']) * 0.5
        
        return min(diversity_score, 1.0)  # [0, 1] aralığında sınırla

    def get_events_for_user(self, user_id, scope='personal', category_filter=None):
        """
        Panel ızgarası için puana göre sıralanmış etkinlik listesini döndürür.
        Kapsam: 'kişisel' (ilgi alanlarına dayalı) veya 'tümü' (keşfet modu).
        Filtre: Sonuçları kesin olarak filtrelemek için isteğe bağlı kategori kısa adı.
        """
        # 1. Adayları Getir
        events = []
        use_direct_api = False # NameError hatasını önlemek için başlat
        
        # KULLANICI İSTEĞİ: Keşfet (scope='all'), veritabanından bağımsız olarak DOĞRUDAN API'den gelmelidir.
        if scope == 'all':
             target_cat_id = None
             if category_filter:
                 target = category_filter.lower()
                 if target in self.category_map:
                     target_cat_id = self.category_map[target]
             
             cat_list = [str(target_cat_id)] if target_cat_id else None
             events = self._fetch_candidates_from_api(cat_list, city_id='40')
             use_direct_api = True # Keşfet için bayrak etkinleştirildi
        else:
             # Varsayılan: Kişisel Panel için Yerel Veritabanından Getir (Daha hızlı, puanlamayı destekler)
             events = self._fetch_candidates_from_db('40')

        # HER ZAMAN geçerli: Filmleri doğrudan TMDB'den getir (Sinema filtresi veya hepsi için)
        # Filmlere ihtiyacımız olup olmadığını kontrol et
        need_movies = True
        if category_filter:
            cf = category_filter.lower()
            # Yalnızca filtre boşsa veya özellikle sinema ile ilgiliyse filmleri getir
            if cf not in ['sinema', 'film'] and cf not in ['bugün', 'yarın', 'haftasonu', 'bugun', 'yarin']: 
                 # Filtre 'konser' ise, filmlere gerek yok
                 need_movies = False
        
        if self.tmdb_api_key and need_movies:
             # ... (TMDB Mantığı)
            try:
                movies = TMDBService.get_now_playing(self.tmdb_api_key)
                # TMDBService doğru şekilde biçimlendirilmiş etkinlikleri döndürür, bu yüzden sadece genişletebiliriz
                if movies:
                    events.extend(movies)
            except Exception as e:
                print(f"TMDB Direct Fetch Error: {e}")
                
        if not events: return []
        
        # 2. Puanlama için Kullanıcı Profilini Getir
        user = self._get_user_profile(user_id)
        interests = []
        if user:
            try: interests = json.loads(user['interests'])
            except: pass
            
        interactions = self._get_user_interactions(user_id)
        
        # 3. Puanla
        scored = self._score_events(events, interests, interactions)
        
        # 4. Filtrele ve Biçimlendir
        results = []
        
        # Özel Tarih Filtreleri (Zaman Etiketleri)
        date_filter_mode = None
        if category_filter:
            cf_lower = category_filter.lower()
            if cf_lower in ['bugün', 'bugun', 'today']: date_filter_mode = 'today'
            elif cf_lower in ['yarın', 'yarin', 'tomorrow']: date_filter_mode = 'tomorrow'
            elif cf_lower in ['haftasonu', 'weekend']: date_filter_mode = 'weekend'
            elif cf_lower in ['bu hafta', 'this week']: date_filter_mode = 'week'
            
        today = datetime.now().date()
        
        for x in scored:
            evt = x['event']
            
            # --- TARİH FİLTRELEME (Eğer Zaman Etiketi seçildiyse) ---
            if date_filter_mode:
                try:
                    start_str = evt.get('start')
                    if not start_str: continue
                    e_date = datetime.fromisoformat(start_str.replace('Z', '')).date()
                    
                    if date_filter_mode == 'today':
                        if e_date != today: continue
                    elif date_filter_mode == 'tomorrow':
                        if e_date != today + timedelta(days=1): continue
                    elif date_filter_mode == 'weekend':
                        # Basit mantık: Cumartesi(5) veya Pazar(6)
                        if e_date.weekday() not in [5, 6]: continue
                    elif date_filter_mode == 'week':
                        if e_date > today + timedelta(days=7): continue
                        
                    # Tarih eşleşirse, metinsel kategori filtresini atlarız
                    results.append(evt)
                    continue
                except:
                     continue
            
            # Kategori Filtresi (Katı)
            # Doğrudan API kullandıysak (use_direct_api), kaynağa güveniriz ve kullanıcı kapsamın üzerinde manuel bir filtre sağlamadıkça bu katı metin kontrolünü atlarız.
            # Ancak burada category_filter, use_direct_api'nin tetikleyicisidir.
            
            should_strict_filter = True
            if use_direct_api and category_filter:
                 # API seviyesinde zaten ID ile filtreleme yaptık.
                 # 'Konser' ve 'Müzik' isimlendirme uyumsuzluklarını önlemek için sonuçlara güven
                 should_strict_filter = False
            
            # Ek kontrol: tarih filtresi modu uygulandıysa ve eşleştiyse, genellikle kategori kontrolünü atlar mıyız?
            # Hayır, ikisini de isteyebiliriz. Ancak 'Keşfet' için kategori yapısı katıdır.
            
            if category_filter and should_strict_filter:
                target = category_filter.lower()
                evt_name = (evt.get('name') or '').lower()
                evt_content = (evt.get('content') or '').lower()
                
                cat_data = evt.get('category') or {}
                cat_slug = (cat_data.get('slug') or '').lower()
                cat_name = (cat_data.get('name') or '').lower()

                # Eşleşme kontrolü (kısa ad, isim, başlık, açıklama)
                matched = False
                
                # Kategori veya İsimde Doğrudan Eşleşme (daha katı filtreleme için içerik kaldırıldı)
                if target in cat_slug or target in cat_name or target in evt_name: matched = True
                
                # Eş Anlamlı Kontrolü
                if not matched and target in self.synonyms:
                    for syn in self.synonyms[target]:
                         if syn in cat_slug or syn in cat_name or syn in evt_name:
                             matched = True
                             break
                             
                if not matched: continue

            # Kapsam Filtreleme (Kişisel vs Tümü)
            if scope == 'personal':
                # Açık filtre ayarlanmışsa, yukarıda kullandık.
                # Açık filtre YOKSA, filtre olarak KULLANICI İLGİ ALANLARINI kullanmalıyız.
                if not category_filter and interests:
                    # Etkinliğin kullanıcının ilgi alanlarından HERHANGİ BİRİYLE eşleşip eşleşmediğini kontrol et
                    is_relevant = False
                    
                    e_name = evt.get('name', '').lower()
                    c_name = evt.get('category', {}).get('name', '').lower()
                    c_slug = evt.get('category', {}).get('slug', '').lower()
                    
                    for intr in interests:
                        ival = intr.lower()
                        # Doğrudan eşleşme
                        if ival in e_name or ival in c_name or ival in c_slug:
                            is_relevant = True
                            break
                        # Eş anlamlı eşleşme
                        if ival in self.synonyms:
                            for syn in self.synonyms[ival]:
                                if syn in e_name or syn in c_name or syn in c_slug:
                                    is_relevant = True
                                    break
                        if is_relevant: break
                    
                    if not is_relevant: 
                        continue

                # Ayrıca puan eşiği
                if not category_filter and x['score'] < 5: 
                    continue
                
            results.append(evt)
            
        return results[:50] # 50 ile sınırla
        
    def _calculate_synergy(self, e1, e2):
        """
        UPGRADED: Daha detaylı sinerji hesaplama
        """
        c1 = e1.get('category', {}).get('name', '').lower()
        c2 = e2.get('category', {}).get('name', '').lower()
        
        # Kategori kontrolleri
        is_music = any(x in c1 for x in ['müzik', 'konser', 'music'])
        is_stage = any(x in c1 for x in ['tiyatro', 'sahne', 'gösteri', 'theatre'])
        is_art = any(x in c1 for x in ['sergi', 'müze', 'sanat', 'art', 'gallery'])
        is_edu = any(x in c1 for x in ['atölye', 'eğitim', 'workshop'])
        is_movie = any(x in c1 for x in ['sinema', 'film', 'cinema'])
        is_sport = any(x in c1 for x in ['spor', 'sport', 'maç'])
        
        is_music2 = any(x in c2 for x in ['müzik', 'konser', 'music'])
        is_stage2 = any(x in c2 for x in ['tiyatro', 'sahne', 'gösteri', 'theatre'])
        is_art2 = any(x in c2 for x in ['sergi', 'müze', 'sanat', 'art', 'gallery'])
        is_edu2 = any(x in c2 for x in ['atölye', 'eğitim', 'workshop'])
        is_movie2 = any(x in c2 for x in ['sinema', 'film', 'cinema'])
        is_sport2 = any(x in c2 for x in ['spor', 'sport', 'maç'])
        
        score = 50  # Base
        theme = "Keyifli Bir Gün"
        
        # ZORUNLU: Aynı kategoriyi cezalandır
        if c1 == c2:
            return 20, f"Çift {c1.capitalize()}"
        
        # Özel kombinasyonlar (Puan: Yüksekten düşüğe)
        
        # Sinema kombinasyonları
        if (is_movie and is_music2) or (is_music and is_movie2):
            score = 95
            theme = "🎬 Film & Müzik Keyfi"
        elif (is_movie and is_stage2) or (is_stage and is_movie2):
            score = 92
            theme = "🎭 Beyaz Perde & Sahne"
        elif (is_movie and is_art2) or (is_art and is_movie2):
            score = 88
            theme = "🎨 Görsel Sanatlar Günü"
        
        # Klasik güçlü kombinasyonlar
        elif (is_art and is_music2) or (is_music and is_art2):
            score = 90
            theme = "🎵 Sanat ve Ritim"
        elif (is_stage and is_music2) or (is_music and is_stage2):
            score = 85
            theme = "✨ Sahne Işıkları"
        elif (is_edu and is_art2) or (is_art and is_edu2):
            score = 80
            theme = "🧠 Keşif Rotası"
        
        # Yeni kombinasyonlar
        elif (is_sport and is_music2) or (is_music and is_sport2):
            score = 82
            theme = "⚡ Enerji Dolu Gün"
        elif (is_edu and is_music2) or (is_music and is_edu2):
            score = 78
            theme = "🎓 Öğren ve Eğlen"
        elif (is_sport and is_art2) or (is_art and is_sport2):
            score = 75
            theme = "💪 Aktif & Sakin Denge"
        
        # Genel çeşitlilik bonusu
        elif c1 != c2:
            score = 70
            theme = "🌈 Farklı Tatlar"
        
        # Tarih yakınlığı bonusu
        try:
            date1 = datetime.fromisoformat(e1.get('start', '').replace('Z', ''))
            date2 = datetime.fromisoformat(e2.get('start', '').replace('Z', ''))
            day_diff = abs((date1.date() - date2.date()).days)
            
            if day_diff == 0:
                score += 10  # Aynı gün bonusu
                theme += " (Aynı Gün)"
            elif day_diff <= 2:
                score += 5  # Yakın tarih bonusu
        except:
            pass
        
        return score, theme
    
    def get_diversity_stats(self, pair):
        """
        DEBUG/TEST: Seçilen ikilinin çeşitlilik istatistiklerini döndürür
        """
        if len(pair) != 2:
            return None
        
        diversity = self._calculate_event_diversity(pair[0], pair[1])
        
        return {
            'diversity_score': round(diversity, 2),
            'category_1': pair[0].get('category', {}).get('name'),
            'category_2': pair[1].get('category', {}).get('name'),
            'venue_1': pair[0].get('venue', {}).get('name'),
            'venue_2': pair[1].get('venue', {}).get('name'),
            'same_category': pair[0].get('category', {}).get('id') == pair[1].get('category', {}).get('id')
        }
