#!/bin/bash

# Finance Tracker - Low Memory EC2 Deployment Script
# Optimized for instances with < 1GB RAM (t2.micro, t3.micro, etc.)

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Low Memory Deployment ===${NC}"
echo "Optimized for EC2 instances with limited RAM"
echo ""

# Step 1: Setup swap (CRITICAL for low memory)
echo -e "${YELLOW}[1/7] Setting up swap space...${NC}"
if [ ! -f /swapfile ]; then
    echo "Creating 2GB swap file (this takes ~2 minutes)..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo "Swap created and activated!"
else
    sudo swapon /swapfile 2>/dev/null || echo "Swap already active"
fi
free -h

# Step 2: Stop everything
echo -e "${YELLOW}[2/7] Stopping existing containers...${NC}"
docker compose down 2>/dev/null || true

# Step 3: Aggressive cleanup
echo -e "${YELLOW}[3/7] Freeing memory (cleaning Docker)...${NC}"
docker system prune -af --volumes
sudo sync && sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'

# Step 4: Pull pre-built images (if available) or build backend
echo -e "${YELLOW}[4/7] Building backend...${NC}"
docker compose build --no-cache backend

# Wait for memory to stabilize
echo "Waiting 10 seconds for memory to stabilize..."
sleep 10

# Step 5: Build frontend with strict limits
echo -e "${YELLOW}[5/7] Building frontend (this takes 5-10 minutes)...${NC}"
echo "⚠️  System will slow down. DO NOT interrupt!"

export NODE_OPTIONS="--max_old_space_size=400"
docker compose build --no-cache --build-arg NODE_OPTIONS="--max_old_space_size=400" frontend || {
    echo -e "${YELLOW}Build failed. Retrying with even lower memory limit...${NC}"
    export NODE_OPTIONS="--max_old_space_size=300"
    docker compose build --no-cache --build-arg NODE_OPTIONS="--max_old_space_size=300" frontend
}

# Step 6: Start services
echo -e "${YELLOW}[6/7] Starting services...${NC}"
docker compose up -d

# Step 7: Wait and verify
echo -e "${YELLOW}[7/7] Waiting for services (60 seconds)...${NC}"
sleep 60

echo ""
echo -e "${GREEN}=== Deployment Complete! ===${NC}"
docker compose ps

echo ""
echo "Access your app:"
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")
echo "  http://$PUBLIC_IP"
echo ""
echo "Keep swap enabled: sudo swapon /swapfile"
echo "Make swap permanent: Add to /etc/fstab:"
echo "  /swapfile swap swap defaults 0 0"

