from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Database configuration
DB_PATH = os.path.join(os.path.dirname(__file__), 'notes.db')

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
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
        
        # Documents table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_deleted INTEGER DEFAULT 0
            )
        ''')
        
        # AI interactions table (for future features)
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
        
        # Speech sessions table (for future features)
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
        print("✓ Database initialized successfully")

# Initialize database on startup
init_db()

# Helper function to convert Row to dict
def row_to_dict(row):
    """Convert sqlite3.Row to dictionary"""
    return {key: row[key] for key in row.keys()}

# API Routes

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Flask server is running'})

@app.route('/api/documents', methods=['GET'])
def get_documents():
    """Get all documents"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM documents WHERE is_deleted = 0 ORDER BY updated_at DESC'
            )
            documents = [row_to_dict(row) for row in cursor.fetchall()]
            return jsonify(documents)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['GET'])
def get_document(document_id):
    """Get single document by ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM documents WHERE id = ? AND is_deleted = 0',
                (document_id,)
            )
            document = cursor.fetchone()
            
            if document is None:
                return jsonify({'error': 'Document not found'}), 404
            
            return jsonify(row_to_dict(document))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents', methods=['POST'])
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
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO documents (id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                (doc_id, title, content, now, now)
            )
            
        return jsonify({
            'id': doc_id,
            'title': title,
            'content': content,
            'created_at': now,
            'updated_at': now
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['PUT'])
def update_document(document_id):
    """Update existing document"""
    try:
        data = request.get_json()
        title = data.get('title')
        content = data.get('content')
        now = datetime.now().isoformat()
        
        if not title or content is None:
            return jsonify({'error': 'Title and content are required'}), 400
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET title = ?, content = ?, updated_at = ? WHERE id = ? AND is_deleted = 0',
                (title, content, now, document_id)
            )
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Document not found'}), 404
            
        return jsonify({
            'id': document_id,
            'title': title,
            'content': content,
            'updated_at': now
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<document_id>', methods=['DELETE'])
def delete_document(document_id):
    """Soft delete document"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE documents SET is_deleted = 1 WHERE id = ?',
                (document_id,)
            )
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Document not found'}), 404
            
        return jsonify({'message': 'Document deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# AI Feature Endpoints (Placeholders for future implementation)

@app.route('/api/ai/summarize', methods=['POST'])
def summarize_text():
    """Summarize selected text (placeholder for AI integration)"""
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        selected_text = data.get('selectedText')
        now = datetime.now().isoformat()
        
        # Log to database
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ai_interactions (document_id, interaction_type, input_text, output_text, created_at) VALUES (?, ?, ?, ?, ?)',
                (document_id, 'summarize', selected_text, 'AI summarization will be implemented here', now)
            )
        
        return jsonify({
            'summary': 'AI summarization feature coming soon!',
            'message': 'This endpoint is ready for AI integration (OpenAI, Claude, or local models)'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/rewrite', methods=['POST'])
def rewrite_text():
    """Rewrite text with specified style (placeholder for AI integration)"""
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        selected_text = data.get('selectedText')
        style = data.get('style', 'professional')
        now = datetime.now().isoformat()
        
        # Log to database
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

@app.route('/api/speech/transcribe', methods=['POST'])
def transcribe_speech():
    """Transcribe speech to text (placeholder for speech-to-text integration)"""
    try:
        data = request.get_json()
        document_id = data.get('documentId')
        audio_data = data.get('audioData')
        now = datetime.now().isoformat()
        
        # Log to database
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO speech_sessions (document_id, transcript, duration, created_at) VALUES (?, ?, ?, ?)',
                (document_id, 'Speech transcription will be implemented here', 0, now)
            )
        
        return jsonify({
            'transcript': 'Speech-to-text feature coming soon!',
            'message': 'This endpoint is ready for speech recognition integration'
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
    print("🚀 Starting Flask backend server...")
    print("📍 Server running at: http://localhost:3001")
    print("📊 API endpoints available at: http://localhost:3001/api")
    print("✨ Press Ctrl+C to stop")
    print()
    app.run(debug=True, host='0.0.0.0', port=5001)

