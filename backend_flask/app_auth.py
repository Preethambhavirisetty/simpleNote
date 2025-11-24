from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import jwt
import bcrypt
from functools import wraps

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=['http://localhost:3002', 'http://localhost:5173'])

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'simplenote-secret-key-change-in-production-2024')
app.config['JWT_EXPIRATION_HOURS'] = 24 * 7  # 7 days

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://simplenote_user:simplenote_secure_password_2024@localhost:5432/simplenote')

def get_db_connection():
    """Create a database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        app.logger.error(f"Database connection error: {e}")
        raise

def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Documents table with user_id
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create indexes
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_documents_user_id 
        ON documents(user_id)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_documents_updated_at 
        ON documents(updated_at DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_email 
        ON users(email)
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    app.logger.info("Database initialized successfully")

# JWT Helper Functions
def generate_token(user_id, email):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS']),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def verify_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Authentication Decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('auth_token')
        
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        
        payload = verify_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Add user info to request
        request.user_id = payload['user_id']
        request.user_email = payload['email']
        
        return f(*args, **kwargs)
    
    return decorated

# Auth Endpoints
@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        name = data.get('name', '').strip()
        
        # Validation
        if not email or not password or not name:
            return jsonify({'error': 'All fields are required'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Insert user
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO users (email, password_hash, name)
                VALUES (%s, %s, %s)
                RETURNING id, email, name
            ''', (email, password_hash, name))
            
            user = cursor.fetchone()
            conn.commit()
            
            # Generate token
            token = generate_token(user['id'], user['email'])
            
            # Create response with HTTP-only cookie
            response = make_response(jsonify({
                'success': True,
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'name': user['name']
                }
            }), 201)
            
            response.set_cookie(
                'auth_token',
                token,
                httponly=True,
                secure=False,  # Set to True in production with HTTPS
                samesite='Lax',
                max_age=60*60*24*7  # 7 days
            )
            
            app.logger.info(f'User registered: {email}')
            return response
            
        except psycopg2.IntegrityError:
            conn.rollback()
            return jsonify({'error': 'Email already exists'}), 409
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        app.logger.error(f'Registration error: {e}')
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        # Get user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Generate token
        token = generate_token(user['id'], user['email'])
        
        # Create response with HTTP-only cookie
        response = make_response(jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user['name']
            }
        }), 200)
        
        response.set_cookie(
            'auth_token',
            token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite='Lax',
            max_age=60*60*24*7  # 7 days
        )
        
        app.logger.info(f'User logged in: {email}')
        return response
        
    except Exception as e:
        app.logger.error(f'Login error: {e}')
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    response = make_response(jsonify({'success': True}), 200)
    response.set_cookie('auth_token', '', httponly=True, expires=0)
    return response

@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user info"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, email, name FROM users WHERE id = %s', (request.user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            return jsonify({
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'name': user['name']
                }
            }), 200
        else:
            return jsonify({'error': 'User not found'}), 404
            
    except Exception as e:
        app.logger.error(f'Get user error: {e}')
        return jsonify({'error': 'Failed to get user'}), 500

# Health Check
@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.close()
        conn.close()
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        app.logger.error(f'Health check failed: {e}')
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 503

# Document Endpoints (Protected)
@app.route('/api/documents', methods=['GET'])
@token_required
def get_documents():
    """Get user's documents"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM documents 
            WHERE user_id = %s 
            ORDER BY updated_at DESC
        ''', (request.user_id,))
        docs = cursor.fetchall()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Retrieved {len(docs)} documents for user {request.user_id}')
        return jsonify([dict(doc) for doc in docs]), 200
    except Exception as e:
        app.logger.error(f'Error fetching documents: {e}')
        return jsonify({'error': 'Failed to fetch documents'}), 500

@app.route('/api/documents', methods=['POST'])
@token_required
def create_document():
    """Create a new document"""
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO documents (id, user_id, title, content, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            data['id'],
            request.user_id,
            data['title'],
            data.get('content', ''),
            data['created_at'],
            data['updated_at']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Created document: {data["title"]} for user {request.user_id}')
        return jsonify({'success': True, 'id': data['id']}), 201
    except Exception as e:
        app.logger.error(f'Error creating document: {e}')
        return jsonify({'error': 'Failed to create document'}), 500

@app.route('/api/documents/<doc_id>', methods=['PUT'])
@token_required
def update_document(doc_id):
    """Update a document"""
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute('SELECT user_id FROM documents WHERE id = %s', (doc_id,))
        doc = cursor.fetchone()
        
        if not doc:
            return jsonify({'error': 'Document not found'}), 404
        
        if doc['user_id'] != request.user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        cursor.execute('''
            UPDATE documents 
            SET title = %s, content = %s, updated_at = %s
            WHERE id = %s AND user_id = %s
        ''', (
            data['title'],
            data['content'],
            datetime.now().isoformat(),
            doc_id,
            request.user_id
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Updated document: {data["title"]} (ID: {doc_id})')
        return jsonify({'success': True}), 200
    except Exception as e:
        app.logger.error(f'Error updating document {doc_id}: {e}')
        return jsonify({'error': 'Failed to update document'}), 500

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
@token_required
def delete_document(doc_id):
    """Delete a document"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute('SELECT user_id FROM documents WHERE id = %s', (doc_id,))
        doc = cursor.fetchone()
        
        if not doc:
            return jsonify({'error': 'Document not found'}), 404
        
        if doc['user_id'] != request.user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        cursor.execute('DELETE FROM documents WHERE id = %s AND user_id = %s', (doc_id, request.user_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Deleted document: {doc_id}')
        return jsonify({'success': True}), 200
    except Exception as e:
        app.logger.error(f'Error deleting document {doc_id}: {e}')
        return jsonify({'error': 'Failed to delete document'}), 500

if __name__ == '__main__':
    # Setup logging
    os.makedirs('/app/logs', exist_ok=True)
    file_handler = RotatingFileHandler('/app/logs/app.log', maxBytes=10240000, backupCount=3)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    
    # Initialize database
    try:
        app.logger.info('Initializing database...')
        init_db()
        app.logger.info('SimpleNote backend starting with PostgreSQL and JWT Auth...')
    except Exception as e:
        app.logger.error(f'Failed to initialize database: {e}')
        raise
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5002, debug=False)

