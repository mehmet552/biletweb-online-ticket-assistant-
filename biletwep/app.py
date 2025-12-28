import sqlite3
import requests
import json
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from recommendations import RecommendationEngine
from datetime import datetime


import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_dev_key')
DB_NAME = 'biletwep.db'

# API Tokens from Environment
ETKINLIK_API_TOKEN = os.getenv('ETKINLIK_API_TOKEN')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')


# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Users table includes preferences directly for simplicity
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            budget INTEGER DEFAULT 0,
            frequency TEXT DEFAULT 'weekly',
            interests TEXT DEFAULT '[]'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
             id INTEGER PRIMARY KEY,
             slug TEXT,
             name TEXT
        )
    ''')
    
    # Community Tables
    conn.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_name TEXT,
            event_id TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, user_id),
            FOREIGN KEY (post_id) REFERENCES posts (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Smart Recommendation Tables
    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            name TEXT,
            category_id TEXT,
            venue_name TEXT,
            city_id TEXT,
            start_date TEXT,
            ticket_price REAL,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            action TEXT NOT NULL, 
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_id TEXT,
            event_date TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # --- PERFORMANCE INDEXES (Optimizations) ---
    # Accelerate filtering by category and date
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_category ON events(category_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_city ON events(city_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date)')
    
    # Accelerate user history lookups
    conn.execute('CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_interactions_event ON interactions(event_id)')
    
    conn.commit()
    conn.close()

# Helper to parse keys
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = dict_factory # Use dict factory for easier manipulation
    return conn

# Initialize Recommendation Engine
from ai_services import AICurator

# Configuration
# Configuration
ETKINLIK_API_TOKEN = os.getenv('ETKINLIK_API_TOKEN')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Initialize Helpers
ai_curator = AICurator(GEMINI_API_KEY)

# Initialize Recommendation Engine
recommendation_engine = RecommendationEngine(
    {'get_conn': get_db_connection}, 
    ETKINLIK_API_TOKEN,
    tmdb_api_key=TMDB_API_KEY,
    ai_curator=ai_curator
)


# --- Routes ---

# --- Community Routes ---
@app.route('/community')
def community():
    conn = get_db_connection()
    # Fetch posts with user info, like count, comment count, AND event details
    posts = conn.execute('''
        SELECT 
            p.*, 
            u.name as user_name,
            u.profile_image as user_image,
            (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as like_count,
            (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comment_count,
            EXISTS(SELECT 1 FROM likes WHERE post_id = p.id AND user_id = ?) as user_liked,
            e.raw_data as event_raw
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN events e ON p.event_id = e.id
        ORDER BY p.created_at DESC
    ''', (session.get('user_id', -1),)).fetchall()
    
    # For each post, fetch comments and parse event URL
    posts_data = []
    for post in posts:
        p_dict = dict(post)
        
        # Parse Event URL
        p_dict['event_url'] = None
        if p_dict.get('event_raw'):
            try:
                raw = json.loads(p_dict['event_raw'])
                p_dict['event_url'] = raw.get('ticket_url') or raw.get('url')
            except: pass
            
        # Fallback if no URL found in DB
        if not p_dict['event_url'] and p_dict.get('event_id'):
            eid = str(p_dict['event_id'])
            if eid.startswith('tmdb_'):
                clean_id = eid.replace('tmdb_', '')
                p_dict['event_url'] = f"https://www.themoviedb.org/movie/{clean_id}"
            elif eid.isdigit():
                # Etkinlik.io ID fallback
                p_dict['event_url'] = f"https://etkinlik.io/etkinlik/{eid}"
            else:
                 # Unknown ID format
                 pass
                 
        # Final Fallback: Google Search
        if not p_dict['event_url'] and p_dict.get('event_name'):
             p_dict['event_url'] = f"https://www.google.com/search?q={p_dict['event_name']} bilet"
            
        comments = conn.execute('''
            SELECT c.*, u.name as user_name 
            FROM comments c 
            JOIN users u ON c.user_id = u.id 
            WHERE c.post_id = ? 
            ORDER BY c.created_at ASC
        ''', (post['id'],)).fetchall()
        p_dict['comments'] = [dict(c) for c in comments]
        posts_data.append(p_dict)
        
    conn.close()
    
    return render_template('community.html', posts=posts_data)

@app.route('/community/share', methods=['POST'])
def share_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    content = request.form.get('content')
    event_name = request.form.get('event_name')
    event_id = request.form.get('event_id')
    
    if content:
        conn = get_db_connection()
        conn.execute('INSERT INTO posts (user_id, content, event_name, event_id) VALUES (?, ?, ?, ?)',
                     (session['user_id'], content, event_name, event_id))
        conn.commit()
        conn.close()
        flash('Paylaşımınız yayınlandı!', 'success')
        
    return redirect(url_for('community'))

@app.route('/community/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401
        
    conn = get_db_connection()
    # Check if liked
    liked = conn.execute('SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?', 
                         (post_id, session['user_id'])).fetchone()
    
    if liked:
        conn.execute('DELETE FROM likes WHERE post_id = ? AND user_id = ?', (post_id, session['user_id']))
        action = 'unliked'
    else:
        conn.execute('INSERT INTO likes (post_id, user_id) VALUES (?, ?)', (post_id, session['user_id']))
        action = 'liked'
        
        # --- Notification: LIKE ---
        post = conn.execute('SELECT user_id, event_name FROM posts WHERE id = ?', (post_id,)).fetchone()
        if post and post['user_id'] != session['user_id']:
            msg = f"{session.get('user_name', 'Bir kullanıcı')} senin gönderini beğendi."
            conn.execute('INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)',
                         (post['user_id'], msg, url_for('community')))
        # --------------------------
        
    conn.commit()
    
    # Get new count
    count = conn.execute('SELECT COUNT(*) as c FROM likes WHERE post_id = ?', (post_id,)).fetchone()['c']
    conn.close()
    
    return jsonify({'action': action, 'count': count})

@app.route('/community/comment/<int:post_id>', methods=['POST'])
def comment_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    content = request.form.get('content')
    if content:
        conn = get_db_connection()
        conn.execute('INSERT INTO comments (post_id, user_id, content) VALUES (?, ?, ?)',
                     (post_id, session['user_id'], content))
                     
        # --- Notification: COMMENT ---
        post = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
        if post and post['user_id'] != session['user_id']:
            msg = f"{session.get('user_name', 'Bir kullanıcı')} senin gönderine yorum yaptı."
            conn.execute('INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)',
                         (post['user_id'], msg, url_for('community')))
        # -----------------------------

        conn.commit()
        conn.close()
        
    return redirect(url_for('community'))


@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        hashed_pw = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('INSERT INTO users (name, email, password) VALUES (?, ?, ?)',
                         (name, email, hashed_pw))
            user_id = cur.lastrowid # Get ID to auto-login
            conn.commit()
            conn.close()
            
            # Auto-login and redirect to Onboarding
            session['user_id'] = user_id
            session['user_name'] = name
            flash('Hesabınız oluşturuldu! Lütfen tercihlerinizi belirleyin.', 'success')
            return redirect(url_for('onboarding'))
            
        except sqlite3.IntegrityError:
            flash('Bu email adresi zaten kayıtlı.', 'error')
            conn.close()
            
    return render_template('register.html')

@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        budget = request.form.get('budget', 0)
        frequency = request.form.get('frequency', 'weekly')
        interests = request.form.getlist('interests') # Expecting checkboxes
        
        conn = get_db_connection()
        conn.execute('UPDATE users SET budget = ?, frequency = ?, interests = ? WHERE id = ?',
                     (budget, frequency, json.dumps(interests), session['user_id']))
        conn.commit()
        conn.close()
        
        flash('Tercihleriniz kaydedildi!', 'success')
        return redirect(url_for('onboarding_quiz'))
        
    return render_template('onboarding.html')

@app.route('/onboarding/quiz')
def onboarding_quiz():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('onboarding_quiz.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        else:
            flash('Hatalı email veya şifre.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))



@app.route('/explore')
def explore():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('explore.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    
    if request.method == 'POST':
        # budget removed
        frequency = request.form.get('frequency')
        interests = request.form.getlist('interests')
        
        profile_image = None
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '':
                import os
                from werkzeug.utils import secure_filename
                
                filename = secure_filename(file.filename)
                # Randomize name to avoid cache issues
                import uuid
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
                new_filename = f"{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                
                save_dir = os.path.join(app.root_path, 'static/uploads/profiles')
                os.makedirs(save_dir, exist_ok=True)
                file.save(os.path.join(save_dir, new_filename))
                
                profile_image = new_filename

        if profile_image:
            conn.execute('UPDATE users SET frequency = ?, interests = ?, profile_image = ? WHERE id = ?',
                         (frequency, json.dumps(interests), profile_image, session['user_id']))
        else:
            conn.execute('UPDATE users SET frequency = ?, interests = ? WHERE id = ?',
                         (frequency, json.dumps(interests), session['user_id']))
                         
        conn.commit()
        flash('Profiliniz güncellendi.', 'success')
        return redirect(url_for('profile'))
        
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Fetch Interactions
    interactions = conn.execute('''
        SELECT e.raw_data, i.action 
        FROM interactions i
        JOIN events e ON i.event_id = e.id
        WHERE i.user_id = ?
        ORDER BY i.timestamp DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    user_data = dict(user)
    try:
        user_data['interests_list'] = json.loads(user_data['interests'])
    except:
        user_data['interests_list'] = []
        
    liked_events = []
    disliked_events = []
    
    for row in interactions:
        try:
            event = json.loads(row['raw_data'])
            if row['action'] == 'like':
                liked_events.append(event)
            elif row['action'] == 'dislike':
                disliked_events.append(event)
        except: pass
    
    return render_template('profile.html', user=user_data, liked_events=liked_events, disliked_events=disliked_events)



# --- API Proxies ---




@app.route('/api/recommend_pair')
def recommend_pair():
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = recommendation_engine.get_recommendations(session['user_id'])
    return jsonify(data)

@app.route('/api/events')
def get_events():
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    
    scope = request.args.get('scope', 'personal')
    category_filter = request.args.get('category')
    events = recommendation_engine.get_events_for_user(session['user_id'], scope=scope, category_filter=category_filter)
    return jsonify(events)

@app.route('/api/user/remove_interest', methods=['POST'])
def remove_interest():
    if 'user_id' not in session: return jsonify({'error': 'Auth'}), 401
    
    interest = request.json.get('interest')
    if not interest: return jsonify({'error': 'No interest'}), 400
    
    conn = get_db_connection()
    user = conn.execute('SELECT interests FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if user:
        current_interests = []
        try: current_interests = json.loads(user['interests'])
        except: pass
        
        if interest in current_interests:
            current_interests.remove(interest)
            conn.execute('UPDATE users SET interests = ? WHERE id = ?', (json.dumps(current_interests), session['user_id']))
            conn.commit()
            
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Load user
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # AUTO-SYNC CHECK
    # Check if we have events. If not, sync automatically.
    event_count = conn.execute('SELECT COUNT(*) as c FROM events').fetchone()['c']
    
    if event_count < 10:
        print("Auto-syncing events as DB is empty...")
        # Close conn before sync to avoid lock
        conn.close()
        try:
             syncer = EventSyncService(DB_NAME, ETKINLIK_API_TOKEN, tmdb_api_key=TMDB_API_KEY)
             # Sync fewer to be fast
             syncer.sync_all_events(limit=200) 
        except Exception as e:
            print(f"Auto-sync failed: {e}")
        
        # Re-open for user fetch
        conn = get_db_connection()
    
    conn.close()
    
    if not user:
        session.clear()
        return redirect(url_for('login'))

    user_data = dict(user)
    try:
        user_data['interests_list'] = json.loads(user_data['interests'])
    except:
        user_data['interests_list'] = []
        
    # SSR: Fetch Data
    cat_filter = request.args.get('filter')
    events = recommendation_engine.get_events_for_user(session['user_id'], category_filter=cat_filter)
    # Lucky Pair now respects Time filters (passed as time_filter), but ignores Category filters internally.
    pair_data = recommendation_engine.get_recommendations(session['user_id'], time_filter=cat_filter)
    
    # --- Check for Event Reminders (Today) ---
    today_str = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection() # Re-open for notifications
    upcoming_events = conn.execute('''
        SELECT c.*, e.name 
        FROM user_calendar c
        JOIN events e ON c.event_id = e.id
        WHERE c.user_id = ? AND c.event_date LIKE ?
    ''', (session['user_id'], f'{today_str}%')).fetchall()
    
    for evt in upcoming_events:
        # Check if we already notified today
        existing = conn.execute('''
            SELECT 1 FROM notifications 
            WHERE user_id = ? AND message LIKE ? AND created_at LIKE ?
        ''', (session['user_id'], f"%{evt['name']}%", f'{today_str}%')).fetchone()
        
        if not existing:
            msg = f"📅 Hatırlatma: '{evt['name']}' etkinliğin bugün yaklaşıyor!"
            conn.execute('INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)',
                         (session['user_id'], msg, url_for('calendar_page')))
            print(f"Notification created for {evt['name']}")
            
    conn.commit()
    conn.close()
    
    # Pass data to template
    return render_template('dashboard.html', 
                           user=user_data, 
                           events=events,
                           pair=pair_data.get('pair', []),
                           alternates=pair_data.get('alternates', []),
                           reason=pair_data.get('reason'))

def update_category_map():
    # This is now handled by recommendation_engine, but we might need to populate the DB table initially
    # If the categories table is empty, we should fetch api and fill it.
    conn = get_db_connection()
    count = conn.execute('SELECT count(*) as c FROM categories').fetchone()['c']
    
    if count == 0:
        headers = {'X-Etkinlik-Token': ETKINLIK_API_TOKEN}
        try:
             resp = requests.get('https://backend.etkinlik.io/api/v2/categories', headers=headers)
             if resp.status_code == 200:
                 for cat in resp.json():
                     conn.execute('INSERT INTO categories (id, slug, name) VALUES (?, ?, ?)', 
                                  (cat['id'], cat['slug'], cat['name']))
                 conn.commit()
                 print("Categories seeded into DB.")
        except Exception as e:
            print("Failed to seed categories:", e)
    conn.close()
    
    # Also tell engine to reload if needed (it does on init, but if we just seeded...)
    recommendation_engine._update_category_map()


# Import Sync Service
from sync_service import EventSyncService

# ... (Existing code)


# --- Notification Routes ---
@app.route('/notifications')
def notifications():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    notifications = conn.execute('SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC', 
                                 (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('notifications.html', notifications=notifications)

@app.route('/api/notifications/read/<int:notif_id>', methods=['POST'])
def mark_notification_read(notif_id):
    if 'user_id' not in session: return jsonify({'error': 'Auth'}), 401
    
    conn = get_db_connection()
    conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?', 
                 (notif_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/notifications/clear', methods=['POST'])
def clear_notifications():
    if 'user_id' not in session: return jsonify({'error': 'Auth'}), 401
    
    conn = get_db_connection()
    conn.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/notifications/count')
def get_notification_count():
    if 'user_id' not in session: return jsonify({'count': 0})
    
    conn = get_db_connection()
    count = conn.execute('SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND is_read = 0', 
                         (session['user_id'],)).fetchone()['c']
    conn.close()
    return jsonify({'count': count})

@app.route('/admin/sync')
def admin_sync():
    # In a real app, protect this with admin login!
    if 'user_id' not in session: return redirect(url_for('login'))
    
    city_id = request.args.get('city_id', '40')
    try:
        syncer = EventSyncService(DB_NAME, ETKINLIK_API_TOKEN, tmdb_api_key=TMDB_API_KEY)
        # Run sync (this might take a while, in prod use background worker like Celery)
        syncer.sync_all_events(city_id=city_id, limit=2000)
        flash(f'Veritabanı senkronizasyonu tamamlandı. ({city_id})', 'success')
    except Exception as e:
        flash(f'Senkronizasyon hatası: {e}', 'error')
        
    return redirect(url_for('dashboard'))

@app.route('/api/interact', methods=['POST'])
def track_interaction():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    
    data = request.json
    event_id = data.get('event_id')
    action = data.get('action') # 'click', 'like', 'view', 'delete'
    
    if event_id and action:
        conn = get_db_connection()
        
        # JIT SAVING: Ensure event exists in DB so it feeds the Algo (which relies on JOINs)
        try:
            exists = conn.execute('SELECT 1 FROM events WHERE id = ?', (event_id,)).fetchone()
            if not exists:
                # We need to fetch and save this event metadata!
                print(f"JIT Saving Event: {event_id}")
                
                # 1. TMDB
                if event_id.startswith('tmdb_'):
                    movie_id = event_id.replace('tmdb_', '')
                    import requests
                    url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=tr-TR"
                    resp = requests.get(url)
                    if resp.status_code == 200:
                        m = resp.json()
                        # Construct Event Object matching sync_service logic
                        poster_url = f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get('poster_path') else None
                        evt_data = {
                            'id': event_id,
                            'name': m.get('title'),
                            'category': {'id': 3796, 'name': 'Sinema', 'slug': 'sinema'},
                            'venue': {'name': 'Sinemalar'},
                            'start': m.get('release_date', datetime.now().isoformat()),
                            'poster_url': poster_url,
                            'content': m.get('overview'),
                            'ticket_url': f"https://www.themoviedb.org/movie/{m.get('id')}"
                        }
                        
                        conn.execute('''
                            INSERT INTO events (id, name, category_id, venue_name, raw_data, start_date) 
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (event_id, m.get('title'), '3796', 'Sinemalar', json.dumps(evt_data), m.get('release_date')))
                
                # 2. Etkinlik.io
                else:
                    # Fetch from Etkinlik API
                    headers = {'X-Etkinlik-Token': ETKINLIK_API_TOKEN}
                    url = f"https://backend.etkinlik.io/api/v2/events/{event_id}"
                    resp = requests.get(url, headers=headers)
                    if resp.status_code == 200:
                        e = resp.json()
                        cat = e.get('category') or {}
                        ven = e.get('venue') or {}
                        conn.execute('''
                            INSERT INTO events (id, name, category_id, venue_name, raw_data, start_date) 
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (str(e['id']), e.get('name'), str(cat.get('id')), ven.get('name'), json.dumps(e), e.get('start')))
                    
        except Exception as e:
            print(f"JIT Save Error: {e}")
            # Continue anyway, saving interaction is primary goal
        
        if action == 'delete':
            # Remove all history for this event (un-like / un-dislike / forget)
            conn.execute('DELETE FROM interactions WHERE user_id = ? AND event_id = ?', 
                         (session['user_id'], event_id))
        else:
            conn.execute('INSERT INTO interactions (user_id, event_id, action) VALUES (?, ?, ?)',
                         (session['user_id'], event_id, action))
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Invalid data'}), 400

@app.route('/api/save_plan', methods=['POST'])
def save_plan():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    
    data = request.json
    event_1_id = data.get('event_1_id')
    event_2_id = data.get('event_2_id')
    theme = data.get('theme', 'Özel Plan')
    
    if event_1_id and event_2_id:
        conn = get_db_connection()
        conn.execute('INSERT INTO saved_plans (user_id, event_1_id, event_2_id, theme) VALUES (?, ?, ?, ?)',
                     (session['user_id'], event_1_id, event_2_id, theme))
        
        # Calendar Auto-Add
        # We need dates. Fetch events to get dates (simplified: assume frontend sends or we fetch)
        # For now, just insert if we can, or let user add manually. 
        # Requirement: "Planı Kaydet ... takvime de eklensin"
        # We'll fetch the events to get their dates.
        try:
             e1 = conn.execute('SELECT raw_data FROM events WHERE id = ?', (event_1_id,)).fetchone()
             e2 = conn.execute('SELECT raw_data FROM events WHERE id = ?', (event_2_id,)).fetchone()
             
             messages = []
             if e1 and e2:
                 d1 = json.loads(e1['raw_data']).get('start')
                 d2 = json.loads(e2['raw_data']).get('start')
                 
                 # Logic: Add only if date exists, else warn
                 if d1:
                     conn.execute('INSERT INTO user_calendar (user_id, event_id, event_date) VALUES (?, ?, ?)', (session['user_id'], event_1_id, d1))
                 else:
                     messages.append(f"⚠️ {json.loads(e1['raw_data']).get('name', 'Etkinlik 1')} için tarih bulunamadı, takvime eklenmedi.")
                     
                 if d2:
                     conn.execute('INSERT INTO user_calendar (user_id, event_id, event_date) VALUES (?, ?, ?)', (session['user_id'], event_2_id, d2))
                 else:
                     messages.append(f"⚠️ {json.loads(e2['raw_data']).get('name', 'Etkinlik 2')} için tarih bulunamadı, takvime eklenmedi.")

             final_msg = 'Plan kaydedildi!'
             if messages:
                 final_msg += " " + " ".join(messages)
             else:
                 final_msg += " İkisi de takvime eklendi. ✅"

        except Exception as e:
            print(f"Calendar auto-add failed: {e}")
            final_msg = "Plan kaydedildi fakat takvim hatası oluştu."

        conn.commit()
        conn.close()
        return jsonify({'status': 'ok', 'message': final_msg})
    return jsonify({'error': 'Missing events'}), 400

@app.route('/api/my_plans')
def get_my_plans():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    
    conn = get_db_connection()
    plans = conn.execute('''
        SELECT p.*, 
               e1.name as e1_name, e1.raw_data as e1_data,
               e2.name as e2_name, e2.raw_data as e2_data
        FROM saved_plans p
        LEFT JOIN events e1 ON p.event_1_id = e1.id
        LEFT JOIN events e2 ON p.event_2_id = e2.id
        WHERE p.user_id = ?
        ORDER BY p.created_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    # Process raw data if needed, but for list view names might be enough
    return jsonify([dict(row) for row in plans])

@app.route('/calendar')
def calendar_page():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('calendar.html')

@app.route('/api/calendar/events')
def get_calendar_events():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT c.*, e.name, e.raw_data, e.ticket_price
        FROM user_calendar c
        JOIN events e ON c.event_id = e.id
        WHERE c.user_id = ?
        ORDER BY c.event_date ASC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    events = []
    for row in rows:
        d = dict(row)
        try: 
            rd = json.loads(d['raw_data'])
            d['raw_data'] = rd
            # Extract vital link fields for usage in frontend
            d['url'] = rd.get('url')
            d['ticket_url'] = rd.get('ticket_url')
            d['poster_url'] = rd.get('poster_url', rd.get('image'))
        except: 
            d['raw_data'] = {}
        events.append(d)
        
    return jsonify(events)

@app.route('/api/calendar/add', methods=['POST'])
def add_to_calendar():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    
    data = request.json
    event_id = data.get('event_id')
    # Optional: date override, otherwise fetch from DB
    
    conn = get_db_connection()
    
    # Check if already added? (Optional, let's allow duplicates or single?)
    # Let's prevent exact duplicate
    exists = conn.execute('SELECT 1 FROM user_calendar WHERE user_id = ? AND event_id = ?', (session['user_id'], event_id)).fetchone()
    if exists:
        conn.close()
        return jsonify({'status': 'exists', 'message': 'Zaten takvimde.'})
        
    # Get date
    event_row = conn.execute('SELECT raw_data FROM events WHERE id = ?', (event_id,)).fetchone()
    if not event_row:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
        
    event_data = json.loads(event_row['raw_data'])
    event_date = event_data.get('start')
    
    conn.execute('INSERT INTO user_calendar (user_id, event_id, event_date) VALUES (?, ?, ?)', 
                 (session['user_id'], event_id, event_date))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok', 'message': 'Takvime eklendi.'})

@app.route('/api/calendar/remove', methods=['POST'])
def remove_from_calendar():
    if 'user_id' not in session: return jsonify({'error': 'Auth required'}), 401
    data = request.json
    conn = get_db_connection()
    conn.execute('DELETE FROM user_calendar WHERE id = ? AND user_id = ?', (data.get('id'), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    init_db()
    update_category_map() # Seed categories if empty
    
    # Optional: Auto-sync on startup if DB is empty
    # conn = sqlite3.connect(DB_NAME)
    # count = conn.execute('SELECT count(*) FROM events').fetchone()[0]
    # conn.close()
    # if count == 0:
    #     print("Initial Sync...")
    #     syncer = EventSyncService(DB_NAME, ETKINLIK_API_TOKEN)
    #     syncer.sync_all_events(limit=500)
        
    app.run(debug=True, port=5000)

