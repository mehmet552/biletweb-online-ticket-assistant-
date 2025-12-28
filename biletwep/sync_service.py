import requests
import json
import sqlite3
import time
from datetime import datetime, timedelta
from services import TMDBService

class EventSyncService:
    def __init__(self, db_path, api_token, tmdb_api_key=None):
        self.db_path = db_path
        self.api_token = api_token
        self.tmdb_api_key = tmdb_api_key
        self.base_url = 'https://backend.etkinlik.io/api/v2/events'

    def fetch_movies_from_tmdb(self):
        """
        Fetches 'Now Playing' movies from TMDB as fake events.
        """
        if not self.tmdb_api_key: # Changed from self.tmdb_key to self.tmdb_api_key
            print("TMDB Key missing, skipping movies.")
            return []
            
        print("Fetching movies from TMDB...")
        url = "https://api.themoviedb.org/3/movie/now_playing"
        params = {
            'api_key': self.tmdb_api_key, # Changed from self.tmdb_key to self.tmdb_api_key
            'language': 'tr-TR',
            'page': 1,
            'region': 'TR'
        }
        
        movies = []
        try:
            res = requests.get(url, params=params)
            res.raise_for_status() # Raise an exception for HTTP errors
            data = res.json()
            
            for m in data.get('results', []):
                # Create a pseudo-event for the movie
                movie_event = {
                    'id': f"tmdb_{m['id']}", # Unique ID prefix
                    'name': m['title'],
                    'slug': f"film-{m['id']}",
                    'category': {'name': 'Sinema', 'slug': 'sinema', 'id': 999}, # Dummy Cat
                    'venue': {'name': 'Tüm Sinemalar', 'id': 0}, # Generic Venue
                    'start': datetime.now().isoformat(), # Available now
                    'end': (datetime.now() + timedelta(days=30)).isoformat(),
                    'poster_url': f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get('poster_path') else None,
                    'content': m.get('overview', ''),
                    'ticket_url': 'https://www.paribucineverse.com', # Generic link
                    'is_free': False
                }
                movies.append(movie_event)
                
        except requests.exceptions.RequestException as e:
            print(f"TMDB API Request Error: {e}")
        except json.JSONDecodeError:
            print("TMDB API Response Error: Could not decode JSON.")
        except Exception as e:
            print(f"TMDB Fetch Error: {e}")
            
        print(f"Fetched {len(movies)} movies.")
        return movies

    def sync_all_events(self, city_id='40', limit=3000):
        """
        Fetches events from API and saves to DB. 
        Limit protects against infinite loops.
        """
        print(f"Starting sync for city {city_id}...")
        conn = sqlite3.connect(self.db_path)
        
        # Performance: Use a transaction
        conn.execute('BEGIN TRANSACTION')
        
        try:
            # 1. Sync TMDB Movies (If Key Exists)
            if self.tmdb_api_key:
                print("Syncing TMDB Movies...")
                movies = TMDBService.get_now_playing(self.tmdb_api_key)
                for movie in movies:
                    self._save_event(conn, movie)
                print(f"Synced {len(movies)} movies.")
            
            # 2. Sync Etkinlik.io Events
            headers = {'X-Etkinlik-Token': self.api_token}
            take = 100
            skip = 0
            total_fetched = 0
        
            while total_fetched < limit:
                params = {
                    'take': take, 
                    'skip': skip, 
                    'city_ids': city_id
                }
                
                resp = requests.get(self.base_url, headers=headers, params=params)
                if resp.status_code != 200:
                    print(f"API Error: {resp.status_code}")
                    break
                    
                data = resp.json()
                items = data.get('items', [])
                
                if not items:
                    print("No more items found.")
                    break
                    
                for item in items:
                    self._save_event(conn, item)
                
                count = len(items)
                total_fetched += count
                skip += count
                
                print(f"Fetched {count} items... Total: {total_fetched}")
                
                # Politeness
                time.sleep(0.2)
                
                if count < take:
                    # Last page
                    break
                
            conn.commit()
            print(f"Sync complete. Total events synced: {total_fetched}")
            
        except Exception as e:
            conn.rollback()
            print(f"Sync failed: {e}")
            raise e
        finally:
            conn.close()

    def _save_event(self, conn, item):
        # Extract fields
        e_id = str(item.get('id'))
        name = item.get('name')
        
        cat = item.get('category') or {}
        cat_id = str(cat.get('id')) if cat else None
        
        venue = item.get('venue') or {}
        venue_name = venue.get('name')
        city_id = str(venue.get('city', {}).get('id')) if venue.get('city') else None
        
        start = item.get('start')
        
        price = 0.0
        if item.get('ticket_price'):
             try:
                 price = float(item['ticket_price'])
             except:
                 pass
                 
        raw = json.dumps(item)
        
        # Upsert
        conn.execute('''
            INSERT OR REPLACE INTO events (id, name, category_id, venue_name, city_id, start_date, ticket_price, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (e_id, name, cat_id, venue_name, city_id, start, price, raw))
