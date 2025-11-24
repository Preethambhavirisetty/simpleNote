#!/bin/bash

# Stop development servers

echo "🛑 Stopping SimpleNote development servers..."

# Stop backend
if [ -f backend.pid ]; then
    kill $(cat backend.pid) 2>/dev/null || true
    rm backend.pid
    echo "✓ Backend stopped"
fi

# Stop frontend
if [ -f frontend.pid ]; then
    kill $(cat frontend.pid) 2>/dev/null || true
    rm frontend.pid
    echo "✓ Frontend stopped"
fi

# Clean up any remaining processes
pkill -f "python app_auth.py" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

echo "✅ All development servers stopped"

