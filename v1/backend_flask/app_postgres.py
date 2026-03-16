from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
CORS(app)

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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create index for better query performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_documents_updated_at 
        ON documents(updated_at DESC)
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    app.logger.info("Database initialized successfully")

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.close()
        conn.close()
        app.logger.info('Health check: OK')
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

@app.route('/api/documents', methods=['GET'])
def get_documents():
    """Get all documents"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM documents ORDER BY updated_at DESC')
        docs = cursor.fetchall()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Retrieved {len(docs)} documents')
        return jsonify([dict(doc) for doc in docs]), 200
    except Exception as e:
        app.logger.error(f'Error fetching documents: {e}')
        return jsonify({'error': 'Failed to fetch documents'}), 500

@app.route('/api/documents', methods=['POST'])
def create_document():
    """Create a new document"""
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO documents (id, title, content, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
        ''', (
            data['id'],
            data['title'],
            data.get('content', ''),
            data['created_at'],
            data['updated_at']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f'Created document: {data["title"]} (ID: {data["id"]})')
        return jsonify({'success': True, 'id': data['id']}), 201
    except Exception as e:
        app.logger.error(f'Error creating document: {e}')
        return jsonify({'error': 'Failed to create document'}), 500

@app.route('/api/documents/<doc_id>', methods=['PUT'])
def update_document(doc_id):
    """Update a document"""
    try:
        data = request.json
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE documents 
            SET title = %s, content = %s, updated_at = %s
            WHERE id = %s
        ''', (
            data['title'],
            data['content'],
            datetime.now().isoformat(),
            doc_id
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
def delete_document(doc_id):
    """Delete a document"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM documents WHERE id = %s', (doc_id,))
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
        app.logger.info('SimpleNote backend starting with PostgreSQL...')
    except Exception as e:
        app.logger.error(f'Failed to initialize database: {e}')
        raise
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5002, debug=False)

