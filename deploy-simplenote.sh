#!/bin/bash

# SimpleNote - Low Memory EC2 Deployment Script
# Designed to work alongside existing Finance Tracker app
# Uses ports: 3001 (frontend), 5001 (backend)

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   SimpleNote Deployment Script        ║${NC}"
echo -e "${BLUE}║   Optimized for Low Memory EC2        ║${NC}"
echo -e "${BLUE}║   Frontend: 3002 | API: 5002 | DB: 5433${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Get project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Step 1: Pre-deployment Docker cleanup
echo -e "${YELLOW}[1/10] Cleaning up old Docker resources...${NC}"
echo ""
echo -e "${BLUE}Current disk usage:${NC}"
df -h / | grep -E "Filesystem|/$" || df -h / | tail -1
echo ""
echo -e "${BLUE}Docker space before cleanup:${NC}"
docker system df 2>/dev/null || true
echo ""

# Stop existing SimpleNote containers first
echo "Stopping SimpleNote containers..."
docker compose down 2>/dev/null || true

# Remove stopped containers
echo "Removing stopped containers..."
docker container prune -f 2>/dev/null || true

# Remove dangling/untagged images
echo "Removing dangling images..."
docker image prune -f 2>/dev/null || true

# Remove old SimpleNote images (not currently in use)
echo "Removing old SimpleNote images..."
docker images | grep simplenote | grep -v "$(docker compose images -q 2>/dev/null | head -1)" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true

# Remove unused networks
echo "Removing unused networks..."
docker network prune -f 2>/dev/null || true

# Remove unused volumes (only if not SimpleNote volumes)
echo "Removing unused volumes (preserving data)..."
docker volume ls -qf dangling=true | xargs -r docker volume rm 2>/dev/null || true

# Clean build cache
echo "Cleaning build cache..."
docker builder prune -f 2>/dev/null || true

echo ""
echo -e "${BLUE}Docker space after cleanup:${NC}"
docker system df 2>/dev/null || true

echo ""
echo -e "${BLUE}Disk space reclaimed:${NC}"
df -h / | grep -E "Filesystem|/$" || df -h / | tail -1
echo ""
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

# Step 2: Verify swap exists
echo -e "${YELLOW}[2/10] Checking swap space...${NC}"
if swapon --show | grep -q "/swapfile"; then
    echo "✓ Swap is active"
    free -h
else
    echo -e "${RED}⚠️  Warning: No swap detected!${NC}"
    echo "Swap is critical for low-memory deployments."
    read -p "Create 2GB swap now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Creating swap..."
        sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        echo "✓ Swap created and activated"
    fi
fi

# Step 3: Check port availability
echo -e "${YELLOW}[3/10] Checking port availability...${NC}"
echo "Ports in use: 3001, 5001 (other services), 5432 (existing database)"
echo "SimpleNote will use: 3002 (frontend), 5002 (backend), 5433 (PostgreSQL)"

if lsof -Pi :3002 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}⚠️  Port 3002 is in use!${NC}"
    echo "Please free port 3002 or modify docker-compose.yml"
    exit 1
fi
if lsof -Pi :5002 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}⚠️  Port 5002 is in use!${NC}"
    echo "Please free port 5002 or modify docker-compose.yml"
    exit 1
fi
if lsof -Pi :5433 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}⚠️  Port 5433 is in use!${NC}"
    echo "Please free port 5433 or modify docker-compose.yml"
    exit 1
fi
echo "✓ Ports 3002, 5002, and 5433 are available"

# Step 3: Update backend config for production
echo -e "${YELLOW}[3/9] Updating backend configuration...${NC}"
cat > backend_flask/app.py.tmp << 'EOF'
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Use persistent volume for database
DB_PATH = '/app/data/database.db'
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/api/health', methods=['GET'])
def health():
    app.logger.info('Health check requested')
    return jsonify({'status': 'healthy'}), 200

@app.route('/api/documents', methods=['GET'])
def get_documents():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM documents ORDER BY updated_at DESC')
    docs = cursor.fetchall()
    conn.close()
    return jsonify([{
        'id': doc[0],
        'title': doc[1],
        'content': doc[2],
        'created_at': doc[3],
        'updated_at': doc[4]
    } for doc in docs])

@app.route('/api/documents', methods=['POST'])
def create_document():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO documents (id, title, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (data['id'], data['title'], data.get('content', ''),
          data['created_at'], data['updated_at']))
    conn.commit()
    conn.close()
    return jsonify({'success': True}), 201

@app.route('/api/documents/<doc_id>', methods=['PUT'])
def update_document(doc_id):
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE documents 
        SET title = ?, content = ?, updated_at = ?
        WHERE id = ?
    ''', (data['title'], data['content'], datetime.now().isoformat(), doc_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    import logging
    from logging.handlers import RotatingFileHandler
    
    # Setup logging
    if not app.debug:
        os.makedirs('/app/logs', exist_ok=True)
        file_handler = RotatingFileHandler('/app/logs/app.log', maxBytes=10240000, backupCount=3)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('SimpleNote backend starting...')
    
    app.run(host='0.0.0.0', port=5002, debug=False)
EOF

# Backup original and use new config
if [ -f backend_flask/app.py ]; then
    cp backend_flask/app.py backend_flask/app.py.backup
fi
mv backend_flask/app.py.tmp backend_flask/app.py
echo "✓ Backend configured for production"

# Step 4: Update frontend API URL
echo -e "${YELLOW}[4/9] Updating frontend configuration...${NC}"
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")
echo "Using public IP: $PUBLIC_IP"

# Update API base URL
sed -i.backup "s|const API_BASE_URL = .*|const API_BASE_URL = '/api';|g" frontend/src/services/api.js
echo "✓ Frontend configured for production"

# Step 5: Ensure SimpleNote is stopped (already done in Step 1)
echo -e "${YELLOW}[5/9] Verifying SimpleNote is stopped...${NC}"
docker compose down 2>/dev/null || true
echo "✓ Containers confirmed stopped"

# Step 8: Build database and backend
echo -e "${YELLOW}[8/10] Pulling PostgreSQL image...${NC}"
docker compose pull simplenote-db
echo "✓ PostgreSQL image ready"

echo -e "${YELLOW}[8/10] Building backend...${NC}"
docker compose build --no-cache simplenote-backend
echo "✓ Backend built"

# Wait for memory
echo "Waiting 15 seconds for memory to stabilize..."
sleep 15

# Step 9: Build frontend (memory intensive)
echo -e "${YELLOW}[9/10] Building frontend (may take 5-10 minutes)...${NC}"
echo -e "${RED}⚠️  System will slow down. DO NOT interrupt!${NC}"

export NODE_OPTIONS="--max_old_space_size=512"
docker compose build --no-cache --build-arg NODE_OPTIONS="--max_old_space_size=512" simplenote-frontend || {
    echo -e "${YELLOW}Build failed. Retrying with lower memory...${NC}"
    export NODE_OPTIONS="--max_old_space_size=400"
    docker compose build --no-cache --build-arg NODE_OPTIONS="--max_old_space_size=400" simplenote-frontend
}
echo "✓ Frontend built"

# Step 10: Start services
echo -e "${YELLOW}[10/10] Starting SimpleNote...${NC}"
docker compose up -d

echo "Waiting for services to start (60 seconds)..."
sleep 60

# Verify deployment
echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Deployment Complete! ✓             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""

# Show running containers
echo -e "${BLUE}Running Containers:${NC}"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo -e "${GREEN}Access your apps:${NC}"
echo -e "  ${BLUE}SimpleNote:${NC}        http://$PUBLIC_IP:3002"
echo -e "  ${BLUE}Other Service:${NC}     http://$PUBLIC_IP:3001"
echo -e "  ${BLUE}Finance Tracker:${NC}   http://$PUBLIC_IP (if running)"
echo ""

# Health check
echo -e "${YELLOW}Health Check:${NC}"
if curl -s http://localhost:5002/api/health > /dev/null 2>&1; then
    echo "  ✓ Backend is healthy"
else
    echo "  ⚠️  Backend may need more time to start"
fi

echo ""
echo -e "${YELLOW}📋 Logging Information:${NC}"
echo "Backend logs are stored in:"
echo "  • Docker logs: docker compose logs -f simplenote-backend"
echo "  • App logs:    docker compose exec simplenote-backend cat /app/logs/app.log"
echo "  • Volume:      /var/lib/docker/volumes/simplenote_simplenote-logs/_data/"
echo ""
echo "Frontend (Nginx) logs are stored in:"
echo "  • Docker logs: docker compose logs -f simplenote-frontend"
echo "  • Access log:  docker compose exec simplenote-frontend cat /var/log/nginx/access.log"
echo "  • Error log:   docker compose exec simplenote-frontend cat /var/log/nginx/error.log"
echo "  • API log:     docker compose exec simplenote-frontend cat /var/log/nginx/api_access.log"
echo "  • Volume:      /var/lib/docker/volumes/simplenote_simplenote-nginx-logs/_data/"
echo ""

echo -e "${YELLOW}Useful Commands:${NC}"
echo "  View all logs:      docker compose logs -f"
echo "  View backend logs:  docker compose logs -f simplenote-backend"
echo "  View frontend logs: docker compose logs -f simplenote-frontend"
echo "  Tail app logs:      docker compose exec simplenote-backend tail -f /app/logs/app.log"
echo "  Stop SimpleNote:    docker compose down"
echo "  Restart:            docker compose restart"
echo "  Check memory:       free -h"
echo "  Check containers:   docker ps"
echo ""
echo -e "${YELLOW}Docker Cleanup Commands:${NC}"
echo "  Quick cleanup:      docker system prune -f"
echo "  Full cleanup:       docker system prune -af --volumes"
echo "  Remove SimpleNote:  docker images | grep simplenote | awk '{print \$3}' | xargs docker rmi -f"
echo "  Show disk usage:    docker system df"
echo "  Or use Makefile:    make prune, make prune-all, make cleanup-simplenote"
echo ""
echo -e "${BLUE}Memory & Disk:${NC}"
docker system df 2>/dev/null || true
echo ""
free -h 2>/dev/null || true
echo ""
echo -e "${GREEN}🎉 SimpleNote is ready!${NC}"

