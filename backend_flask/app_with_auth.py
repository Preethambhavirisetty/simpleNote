from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import jwt as pyjwt
import bcrypt
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler

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

# Database configuration - PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://simplenote_user:simplenote_secure_password_2024@localhost:5432/simplenote')

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
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
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Documents table - now with user_id
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                title TEXT NOT NULL,
                content JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_documents_user_id 
            ON documents(user_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_documents_updated_at 
            ON documents(updated_at DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_documents_is_deleted 
            ON documents(is_deleted)
        ''')
        
        # AI interactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ai_interactions (
                id SERIAL PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                interaction_type VARCHAR(100) NOT NULL,
                input_text TEXT,
                output_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        ''')
        
        # Speech sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS speech_sessions (
                id SERIAL PRIMARY KEY,
                document_id VARCHAR(255) NOT NULL,
                transcript TEXT,
                duration INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        cursor.close()
        print("✓ Database initialized successfully with authentication (PostgreSQL)")

# Initialize database on startup
try:
    init_db()
except Exception as e:
    print(f"⚠️  Database initialization warning: {e}")
    print("   This is normal if tables already exist or database is not yet available")

# Helper function to convert Row to dict
def row_to_dict(row):
    """Convert RealDictRow to dictionary with JSON parsing for content"""
    result = dict(row)
    
    # Parse content field from JSON string to object (if stored as text)
    # PostgreSQL JSONB is already parsed, but handle both cases
    if 'content' in result and result['content']:
        if isinstance(result['content'], str):
            try:
                result['content'] = json.loads(result['content'])
            except (json.JSONDecodeError, TypeError):
                pass
    
    # Convert timestamps to ISO format strings
    for key in ['created_at', 'updated_at']:
        if key in result and result[key] and isinstance(result[key], datetime):
            result[key] = result[key].isoformat()
    
    # Convert boolean to integer for compatibility
    if 'is_deleted' in result:
        result['is_deleted'] = 1 if result['is_deleted'] else 0
    
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
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
        return jsonify({
            'status': 'ok', 
            'message': 'Flask server is running with authentication (PostgreSQL)',
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'ok',
            'message': 'Flask server is running with authentication (PostgreSQL)',
            'database': 'disconnected',
            'error': str(e)
        }), 200

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
        now = datetime.now(timezone.utc)
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if email already exists
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            if cursor.fetchone():
                return jsonify({'error': 'Email already registered'}), 409
            
            # Create user
            cursor.execute(
                'INSERT INTO users (id, name, email, password_hash, created_at) VALUES (%s, %s, %s, %s, %s)',
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
        import traceback
        traceback.print_exc()
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
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
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
    response.delete_cookie('auth_token')
    return response

@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current authenticated user"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, email, created_at FROM users WHERE id = %s', (request.user_id,))
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
                'SELECT * FROM documents WHERE user_id = %s AND is_deleted = FALSE ORDER BY updated_at DESC',
                (request.user_id,)
            )
            documents = [row_to_dict(row) for row in cursor.fetchall()]
            return jsonify(documents)
    except Exception as e:
        print(f"Error fetching documents: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['GET'])
@token_required
def get_document(document_id):
    """Get single document by ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM documents WHERE id = %s AND user_id = %s AND is_deleted = FALSE',
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
        now = datetime.now(timezone.utc)
        
        if not doc_id or not title:
            return jsonify({'error': 'ID and title are required'}), 400
        
        # Store content as JSONB (PostgreSQL native JSON)
        # Handle empty content first
        if content is None or content == '':
            content_json = '{}'
        elif isinstance(content, (dict, list)):
            content_json = json.dumps(content)
        elif isinstance(content, str):
            # If it's a string, validate it's valid JSON
            if content.strip() == '':
                content_json = '{}'
            else:
                try:
                    # Validate it's valid JSON
                    json.loads(content)
                    content_json = content
                except (json.JSONDecodeError, TypeError):
                    # If not valid JSON, wrap it as a string value
                    content_json = json.dumps(content)
        else:
            # For any other type, convert to JSON
            content_json = json.dumps(content)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO documents (id, user_id, title, content, created_at, updated_at) VALUES (%s, %s, %s, %s::jsonb, %s, %s)',
                (doc_id, request.user_id, title, content_json, now, now)
            )
            
        return jsonify({
            'id': doc_id,
            'user_id': request.user_id,
            'title': title,
            'content': content,  # Return original content object
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }), 201
    except Exception as e:
        print(f"Error creating document: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['PUT'])
@token_required
def update_document(document_id):
    """Update existing document"""
    try:
        data = request.get_json()
        title = data.get('title')
        content = data.get('content')
        now = datetime.now(timezone.utc)
        
        if not title or content is None:
            return jsonify({'error': 'Title and content are required'}), 400
        
        # Store content as JSONB (PostgreSQL native JSON)
        # Handle empty content first
        if content is None or content == '':
            content_json = '{}'
        elif isinstance(content, (dict, list)):
            content_json = json.dumps(content)
        elif isinstance(content, str):
            # If it's a string, validate it's valid JSON
            if content.strip() == '':
                content_json = '{}'
            else:
                try:
                    # Validate it's valid JSON
                    json.loads(content)
                    content_json = content
                except (json.JSONDecodeError, TypeError):
                    # If not valid JSON, wrap it as a string value
                    content_json = json.dumps(content)
        else:
            # For any other type, convert to JSON
            content_json = json.dumps(content)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET title = %s, content = %s::jsonb, updated_at = %s WHERE id = %s AND user_id = %s AND is_deleted = FALSE',
                (title, content_json, now, document_id, request.user_id)
            )
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Document not found'}), 404
            
        return jsonify({
            'id': document_id,
            'title': title,
            'content': content,  # Return original content object
            'updated_at': now.isoformat()
        })
    except Exception as e:
        print(f"Error updating document: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['DELETE'])
@token_required
def delete_document(document_id):
    """Soft delete document"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET is_deleted = TRUE WHERE id = %s AND user_id = %s',
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
        now = datetime.now(timezone.utc)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ai_interactions (document_id, interaction_type, input_text, output_text, created_at) VALUES (%s, %s, %s, %s, %s)',
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
        now = datetime.now(timezone.utc)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ai_interactions (document_id, interaction_type, input_text, output_text, created_at) VALUES (%s, %s, %s, %s, %s)',
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
    # Setup logging
    os.makedirs('/app/logs', exist_ok=True)
    file_handler = RotatingFileHandler('/app/logs/app.log', maxBytes=10240000, backupCount=3)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    
    print("🚀 Starting Flask backend server with authentication (PostgreSQL)...")
    print("📍 Server running at: http://localhost:5002")
    print("📊 API endpoints available at: http://localhost:5002/api")
    print("🔐 Authentication: JWT with HTTP-only cookies")
    print("💾 Database: PostgreSQL")
    print("✨ Press Ctrl+C to stop")
    print()
    app.run(debug=True, host='0.0.0.0', port=5002)
