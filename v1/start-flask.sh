#!/bin/bash

# SimpleNote Startup Script (Flask Backend)

echo "🚀 Starting SimpleNote with Flask Backend..."
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+"
    exit 1
fi

# Check if virtual environment exists in backend_flask
if [ ! -d "backend_flask/venv" ]; then
    echo "📦 Creating Python virtual environment..."
    cd backend_flask && python3 -m venv venv && cd ..
fi

# Install backend dependencies
if [ ! -f "backend_flask/venv/bin/activate" ]; then
    echo "❌ Virtual environment not created properly"
    exit 1
fi

echo "📦 Installing Python dependencies..."
cd backend_flask
source venv/bin/activate
pip install -q -r requirements.txt
cd ..

# Check if node_modules exists in frontend
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

echo ""
echo "✅ Dependencies installed!"
echo ""
echo "Starting servers..."
echo "🔹 Backend (Flask): http://localhost:3001"
echo "🔹 Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all servers"
echo ""

# Start Flask backend
cd backend_flask
source venv/bin/activate
python app.py &
BACKEND_PID=$!
cd ..

# Start frontend
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT

wait

