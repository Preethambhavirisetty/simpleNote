from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import sqlite3
import os
import json
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import jwt as pyjwt
import bcrypt
from functools import wraps

app = Flask(__name__)

# CORS configuration - allow credentials for cookies
CORS(app, supports_credentials=True, origins=[
    'http://localhost:5173',  # Vite dev server
    'http://localhost:3002',  # Docker frontend
    'http://localhost:3000',  # Docker frontend
    'http://44.192.13.139:3002'  # EC2 production
])

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'simplenote-secret-key-2024-change-in-production')

# Database configuration
DB_PATH = os.path.join(os.path.dirname(__file__), 'notes.db')

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    """Initialize database with required tables"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Documents table - now with user_id
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_deleted INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # AI interactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ai_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                interaction_type TEXT NOT NULL,
                input_text TEXT,
                output_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        ''')
        
        # Speech sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS speech_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                transcript TEXT,
                duration INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        ''')
        
        conn.commit()
        print("✓ Database initialized successfully with authentication")

# Initialize database on startup
init_db()

# Helper function to convert Row to dict
def row_to_dict(row):
    """Convert sqlite3.Row to dictionary with JSON parsing for content"""
    result = {key: row[key] for key in row.keys()}
    
    # Parse content field from JSON string to object
    if 'content' in result and result['content']:
        try:
            result['content'] = json.loads(result['content'])
        except (json.JSONDecodeError, TypeError):
            # If not valid JSON, keep as string (for backward compatibility)
            pass
    
    return result

# Authentication decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('auth_token')
        
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        
        try:
            data = pyjwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user_id = data['user_id']
            request.user_id = current_user_id
        except pyjwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except pyjwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated

# Helper function to generate JWT token
def generate_token(user_id):
    """Generate JWT token"""
    expiration = datetime.now(timezone.utc) + timedelta(days=7)
    token = pyjwt.encode({
        'user_id': user_id,
        'exp': expiration
    }, app.config['SECRET_KEY'], algorithm='HS256')
    return token

# Authentication Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Flask server is running with authentication'})

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        
        if not name or not email or not password:
            return jsonify({'error': 'Name, email and password are required'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Generate user ID
        user_id = f"user_{int(datetime.now().timestamp() * 1000)}"
        now = datetime.now().isoformat()
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if email already exists
            cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
            if cursor.fetchone():
                return jsonify({'error': 'Email already registered'}), 409
            
            # Create user
            cursor.execute(
                'INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, name, email, password_hash, now)
            )
        
        # Generate token
        token = generate_token(user_id)
        
        # Create response with cookie
        response = make_response(jsonify({
            'user': {
                'id': user_id,
                'name': name,
                'email': email
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
        
        return response
        
    except Exception as e:
        print(f"Registration error: {e}")
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({'error': 'Invalid credentials'}), 401
            
            # Verify password
            if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                return jsonify({'error': 'Invalid credentials'}), 401
        
        # Generate token
        token = generate_token(user['id'])
        
        # Create response with cookie
        response = make_response(jsonify({
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email']
            }
        }))
        
        response.set_cookie(
            'auth_token',
            token,
            httponly=True,
            secure=False,
            samesite='Lax',
            max_age=60*60*24*7
        )
        
        return response
        
    except Exception as e:
        print(f"Login error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    response = make_response(jsonify({'message': 'Logged out successfully'}))
    # response.set_cookie('auth_token', '', expires=0)
    response.delete_cookie('auth_token')
    return response

@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current authenticated user"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, email, created_at FROM users WHERE id = ?', (request.user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            return jsonify({'user': row_to_dict(user)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Document Routes (Protected)

@app.route('/api/documents', methods=['GET'])
@token_required
def get_documents():
    """Get all documents for current user"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM documents WHERE user_id = ? AND is_deleted = 0 ORDER BY updated_at DESC',
                (request.user_id,)
            )
            documents = [row_to_dict(row) for row in cursor.fetchall()]
            return jsonify(documents)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['GET'])
@token_required
def get_document(document_id):
    """Get single document by ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM documents WHERE id = ? AND user_id = ? AND is_deleted = 0',
                (document_id, request.user_id)
            )
            document = cursor.fetchone()
            
            if document is None:
                return jsonify({'error': 'Document not found'}), 404
            
            return jsonify(row_to_dict(document))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents', methods=['POST'])
@token_required
def create_document():
    """Create new document"""
    try:
        data = request.get_json()
        doc_id = data.get('id')
        title = data.get('title')
        content = data.get('content', '')
        now = datetime.now().isoformat()
        
        if not doc_id or not title:
            return jsonify({'error': 'ID and title are required'}), 400
        
        # Store content as JSON string (ProseMirror JSON format)
        content_str = json.dumps(content) if isinstance(content, (dict, list)) else content
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO documents (id, user_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                (doc_id, request.user_id, title, content_str, now, now)
            )
            
        return jsonify({
            'id': doc_id,
            'user_id': request.user_id,
            'title': title,
            'content': content,  # Return original content object
            'created_at': now,
            'updated_at': now
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['PUT'])
@token_required
def update_document(document_id):
    """Update existing document"""
    try:
        data = request.get_json()
        title = data.get('title')
        content = data.get('content')
        now = datetime.now().isoformat()
        
        if not title or content is None:
            return jsonify({'error': 'Title and content are required'}), 400
        
        # Store content as JSON string (ProseMirror JSON format)
        content_str = json.dumps(content) if isinstance(content, (dict, list)) else content
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET title = ?, content = ?, updated_at = ? WHERE id = ? AND user_id = ? AND is_deleted = 0',
                (title, content_str, now, document_id, request.user_id)
            )
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Document not found'}), 404
            
        return jsonify({
            'id': document_id,
            'title': title,
            'content': content,  # Return original content object
            'updated_at': now
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['DELETE'])
@token_required
def delete_document(document_id):
    """Soft delete document"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET is_deleted = 1 WHERE id = ? AND user_id = ?',
                (document_id, request.user_id)
            )
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Document not found'}), 404
            
        return jsonify({'message': 'Document deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# AI Feature Endpoints (Protected)

@app.route('/api/ai/summarize', methods=['POST'])
@token_required
def summarize_text():
    """Summarize selected text"""
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        selected_text = data.get('selectedText')
        now = datetime.now().isoformat()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ai_interactions (document_id, interaction_type, input_text, output_text, created_at) VALUES (?, ?, ?, ?, ?)',
                (document_id, 'summarize', selected_text, 'AI summarization will be implemented here', now)
            )
        
        return jsonify({
            'summary': 'AI summarization feature coming soon!',
            'message': 'This endpoint is ready for AI integration'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/rewrite', methods=['POST'])
@token_required
def rewrite_text():
    """Rewrite text with specified style"""
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        selected_text = data.get('selectedText')
        style = data.get('style', 'professional')
        now = datetime.now().isoformat()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ai_interactions (document_id, interaction_type, input_text, output_text, created_at) VALUES (?, ?, ?, ?, ?)',
                (document_id, f'rewrite_{style}', selected_text, 'AI rewriting will be implemented here', now)
            )
        
        return jsonify({
            'rewrittenText': 'AI rewriting feature coming soon!',
            'message': 'This endpoint is ready for AI integration'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Error handlers

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("🚀 Starting Flask backend server with authentication...")
    print("📍 Server running at: http://localhost:5002")
    print("📊 API endpoints available at: http://localhost:5002/api")
    print("🔐 Authentication: JWT with HTTP-only cookies")
    print("✨ Press Ctrl+C to stop")
    print()
    app.run(debug=True, host='0.0.0.0', port=5002)

