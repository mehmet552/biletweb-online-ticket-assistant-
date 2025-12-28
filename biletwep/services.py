import requests
import os

class TMDBService:
    @staticmethod
    def get_now_playing(api_key):
        """
        Fetches 'Now Playing' movies from TMDB for Turkey.
        """
        url = f"https://api.themoviedb.org/3/movie/now_playing"
        params = {
            'api_key': api_key,
            'language': 'tr-TR',
            'page': 1,
            'region': 'TR'
        }

        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                
                events = []
                for movie in results:
                    # TMDB fields: title, overview, poster_path, backdrop_path, release_date
                    poster_path = movie.get('poster_path')
                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                    
                    overview = movie.get('overview')
                    if not overview: overview = "Özet bulunmuyor."
                    
                    events.append({
                        'id': f"tmdb_{movie.get('id')}", 
                        'name': movie.get('title'),
                        'image': poster_url, 
                        'poster_url': poster_url,
                        'content': f"{overview} (Yayın Tarihi: {movie.get('release_date')})",
                        'category': {'name': 'Sinema', 'slug': 'sinema', 'id': 3796}, 
                        'start': movie.get('release_date'), 
                        'venue': {'name': 'Sinemalar', 'city': {'name': 'İstanbul'}}, 
                        'ticket_price': 0, 
                        'is_free': False,
                        'ticket_url': f"https://www.themoviedb.org/movie/{movie.get('id')}"
                    })
                return events
            else:
                print(f"TMDB Error: {response.status_code}")
                
        except Exception as e:
            print(f"TMDB Exception: {e}")
            
        return []
