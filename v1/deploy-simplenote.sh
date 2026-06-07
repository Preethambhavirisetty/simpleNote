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

# Step 3: Verify backend authentication setup
echo -e "${YELLOW}[3/10] Verifying backend configuration...${NC}"
if [ ! -f backend_flask/app_with_auth.py ]; then
    echo -e "${RED}⚠️  Error: app_with_auth.py not found!${NC}"
    echo "Make sure you have the authentication backend file."
    exit 1
fi
echo "✓ Backend with authentication found"

# Check if SECRET_KEY is set in docker-compose.yml
if ! grep -q "SECRET_KEY" docker-compose.yml; then
    echo -e "${YELLOW}⚠️  WARNING: SECRET_KEY not set in docker-compose.yml${NC}"
    echo "Consider adding SECRET_KEY environment variable for production security"
fi

# Step 4: Get public IP for display
echo -e "${YELLOW}[4/10] Detecting public IP...${NC}"
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")
echo "Using public IP: $PUBLIC_IP"
echo "✓ API will be accessible at: http://$PUBLIC_IP:3002/api"

# Step 5: Stop existing SimpleNote containers
echo -e "${YELLOW}[5/10] Stopping existing SimpleNote containers...${NC}"
docker compose down 2>/dev/null || true
echo "✓ Containers stopped"

# Step 6: Clean up old images
echo -e "${YELLOW}[6/10] Cleaning Docker (keeping other projects)...${NC}"
docker images | grep simplenote | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true
echo "✓ Old SimpleNote images removed"

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

