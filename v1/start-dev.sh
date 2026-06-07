#!/bin/bash

# Development startup script for SimpleNote

set -e

echo "🚀 Starting SimpleNote in Development Mode..."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Check if ports are available
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${RED}❌ Port $port is already in use!${NC}"
        echo "   Please stop the service using this port or choose a different port."
        return 1
    fi
    return 0
}

echo -e "${BLUE}[1/4] Checking ports...${NC}"
if ! check_port 5002; then
    echo "Backend port 5002 is in use"
    exit 1
fi
if ! check_port 5173; then
    echo "Frontend port 5173 is in use"
    exit 1
fi
echo -e "${GREEN}✓ Ports available${NC}"

# Start backend
echo -e "${BLUE}[2/4] Starting Flask backend on port 5002...${NC}"
cd backend_flask

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install -q -r requirements.txt

# Set environment variables
export FLASK_ENV=development
export PORT=5002
export DATABASE_URL=${DATABASE_URL:-"postgresql://simplenote_user:simplenote_secure_password_2024@localhost:5433/simplenote"}
export SECRET_KEY=${SECRET_KEY:-"simplenote-jwt-secret-key-change-in-production-2024"}

# Start backend in background
echo -e "${GREEN}✓ Starting backend server...${NC}"
python app_auth.py > ../backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > ../backend.pid

cd ..

# Wait for backend to be ready
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    if curl -sf http://localhost:5002/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready!${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ Backend failed to start${NC}"
        echo "Check backend.log for details"
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Start frontend
echo -e "${BLUE}[3/4] Starting React frontend on port 5173...${NC}"
cd frontend

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing Node dependencies...${NC}"
    npm install
fi

# Start frontend in background
echo -e "${GREEN}✓ Starting frontend server...${NC}"
npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../frontend.pid

cd ..

# Wait for frontend to be ready
echo -e "${YELLOW}Waiting for frontend to be ready...${NC}"
for i in {1..30}; do
    if curl -sf http://localhost:5173 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Frontend is ready!${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ Frontend failed to start${NC}"
        echo "Check frontend.log for details"
        kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                        ║${NC}"
echo -e "${GREEN}║   SimpleNote Development Server        ║${NC}"
echo -e "${GREEN}║                                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Frontend:${NC}  http://localhost:5173"
echo -e "${BLUE}Backend:${NC}   http://localhost:5002"
echo -e "${BLUE}Health:${NC}    http://localhost:5002/api/health"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  Backend:  tail -f backend.log"
echo "  Frontend: tail -f frontend.log"
echo ""
echo -e "${YELLOW}To stop:${NC}"
echo "  kill \$(cat backend.pid frontend.pid)"
echo "  or run: ./stop-dev.sh"
echo ""
echo -e "${GREEN}🎉 Development server is running!${NC}"

