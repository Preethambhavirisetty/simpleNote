#!/bin/sh
# Frontend container entrypoint - copies built files to shared volume

set -e

echo "📦 Copying frontend files to shared volume..."

# Wait a moment for volume to be mounted
sleep 1

# Copy built files to the mounted volume (shared with nginx)
if [ -d "/usr/share/nginx/html" ] && [ -d "/app/dist" ] && [ "$(ls -A /app/dist 2>/dev/null)" ]; then
    echo "📋 Copying files from /app/dist to /usr/share/nginx/html..."
    cp -rf /app/dist/* /usr/share/nginx/html/ 2>/dev/null || true
    echo "✅ Files copied successfully"
    ls -la /usr/share/nginx/html/ | head -10
else
    echo "⚠️  Using built-in files (volume not mounted or empty)"
    # Fallback: copy to default location if volume not available
    if [ -d "/app/dist" ] && [ "$(ls -A /app/dist 2>/dev/null)" ]; then
        cp -rf /app/dist/* /usr/share/nginx/html/ 2>/dev/null || true
    fi
fi

# Start nginx to serve files (for internal access if needed)
exec nginx -g "daemon off;"

