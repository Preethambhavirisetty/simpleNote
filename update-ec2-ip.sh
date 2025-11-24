#!/bin/bash

# Script to update EC2 IP in docker-compose.yml

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Update EC2 IP for SimpleNote        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Get current public IP automatically
echo -e "${YELLOW}Detecting public IP...${NC}"
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com || curl -s http://ifconfig.me || curl -s http://ipinfo.io/ip)

if [ -z "$PUBLIC_IP" ]; then
    echo -e "${RED}❌ Could not detect public IP automatically${NC}"
    read -p "Enter your EC2 public IP: " PUBLIC_IP
fi

echo -e "${GREEN}Using IP: $PUBLIC_IP${NC}"
echo ""

# Confirm
read -p "Update docker-compose.yml with this IP? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cancelled${NC}"
    exit 0
fi

# Update docker-compose.yml
echo -e "${YELLOW}Updating docker-compose.yml...${NC}"

# Backup original
cp docker-compose.yml docker-compose.yml.backup

# Update ALLOWED_ORIGINS
if grep -q "ALLOWED_ORIGINS" docker-compose.yml; then
    # Update existing line
    sed -i.tmp "s|ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=http://$PUBLIC_IP:3002,http://localhost:3002,http://localhost:5173|" docker-compose.yml
    rm docker-compose.yml.tmp 2>/dev/null || true
    echo -e "${GREEN}✓ Updated existing ALLOWED_ORIGINS${NC}"
else
    # Add new line
    echo -e "${YELLOW}⚠️  ALLOWED_ORIGINS not found in docker-compose.yml${NC}"
    echo "Please add manually:"
    echo "  - ALLOWED_ORIGINS=http://$PUBLIC_IP:3002,http://localhost:3002"
fi

echo ""
echo -e "${GREEN}Configuration updated!${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review the changes: cat docker-compose.yml"
echo "2. Rebuild: docker compose build --no-cache"
echo "3. Restart: docker compose up -d"
echo "4. Test: http://$PUBLIC_IP:3002"
echo ""
echo -e "${BLUE}Backup saved to: docker-compose.yml.backup${NC}"

