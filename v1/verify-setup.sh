#!/bin/bash

# SimpleNote Setup Verification Script

echo "🔍 SimpleNote Setup Verification"
echo "================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Node.js
echo -n "Checking Node.js... "
if command -v node &> /dev/null; then
    NODE_VERSION=$(node -v)
    echo -e "${GREEN}✓${NC} Found: $NODE_VERSION"
else
    echo -e "${RED}✗${NC} Node.js not found. Please install Node.js 16+"
    exit 1
fi

# Check npm
echo -n "Checking npm... "
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm -v)
    echo -e "${GREEN}✓${NC} Found: v$NPM_VERSION"
else
    echo -e "${RED}✗${NC} npm not found"
    exit 1
fi

echo ""
echo "📁 Verifying Project Structure"
echo "------------------------------"

# Check backend files
echo -n "Backend server.js... "
if [ -f "backend/server.js" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "Backend package.json... "
if [ -f "backend/package.json" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Check frontend files
echo -n "Frontend App.jsx... "
if [ -f "frontend/src/App.jsx" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "Frontend package.json... "
if [ -f "frontend/package.json" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "Frontend index.html... "
if [ -f "frontend/index.html" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Check components
echo -n "Components directory... "
if [ -d "frontend/src/components" ]; then
    COMPONENT_COUNT=$(ls -1 frontend/src/components/*.jsx 2>/dev/null | wc -l)
    echo -e "${GREEN}✓${NC} ($COMPONENT_COUNT components)"
else
    echo -e "${RED}✗${NC}"
fi

echo ""
echo "📦 Checking Dependencies"
echo "------------------------"

# Check backend dependencies
echo -n "Backend node_modules... "
if [ -d "backend/node_modules" ]; then
    echo -e "${GREEN}✓${NC} Installed"
else
    echo -e "${YELLOW}⚠${NC} Not installed. Run: cd backend && npm install"
fi

# Check frontend dependencies
echo -n "Frontend node_modules... "
if [ -d "frontend/node_modules" ]; then
    echo -e "${GREEN}✓${NC} Installed"
else
    echo -e "${YELLOW}⚠${NC} Not installed. Run: cd frontend && npm install"
fi

echo ""
echo "📚 Checking Documentation"
echo "-------------------------"

docs=("README.md" "QUICKSTART.md" "ARCHITECTURE.md" "AI_INTEGRATION_GUIDE.md" "PROJECT_SUMMARY.md" "CHANGELOG.md")
for doc in "${docs[@]}"; do
    echo -n "$doc... "
    if [ -f "$doc" ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi
done

echo ""
echo "🔧 Configuration Files"
echo "----------------------"

configs=("frontend/vite.config.js" "frontend/tailwind.config.js" "frontend/postcss.config.js" ".gitignore" "start.sh")
for config in "${configs[@]}"; do
    echo -n "$config... "
    if [ -f "$config" ]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi
done

echo ""
echo "🎯 Next Steps"
echo "-------------"
echo ""

if [ -d "backend/node_modules" ] && [ -d "frontend/node_modules" ]; then
    echo -e "${GREEN}✓ All dependencies installed!${NC}"
    echo ""
    echo "Start the application with:"
    echo "  ${YELLOW}./start.sh${NC}"
    echo ""
    echo "Or manually:"
    echo "  Terminal 1: ${YELLOW}cd backend && npm start${NC}"
    echo "  Terminal 2: ${YELLOW}cd frontend && npm run dev${NC}"
else
    echo -e "${YELLOW}⚠ Install dependencies first:${NC}"
    echo ""
    echo "  ${YELLOW}cd backend && npm install${NC}"
    echo "  ${YELLOW}cd ../frontend && npm install${NC}"
    echo "  ${YELLOW}npm install -D @tailwindcss/typography${NC}"
    echo ""
    echo "Then run: ${YELLOW}./start.sh${NC}"
fi

echo ""
echo "📖 Documentation:"
echo "  Quick Start: ${YELLOW}cat QUICKSTART.md${NC}"
echo "  Full Guide:  ${YELLOW}cat README.md${NC}"
echo ""
echo "✨ Verification Complete!"

