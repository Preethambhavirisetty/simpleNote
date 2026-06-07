#!/bin/sh
# Watch for certificate changes and reload nginx
# This runs in the nginx container

set -e

CERT_PATH="/etc/letsencrypt/live/www.notelite.org/fullchain.pem"
LAST_MODIFIED=0

echo "👀 Watching for certificate changes..."

while true; do
    if [ -f "$CERT_PATH" ]; then
        CURRENT_MODIFIED=$(stat -c %Y "$CERT_PATH" 2>/dev/null || stat -f %m "$CERT_PATH" 2>/dev/null || echo 0)
        
        if [ "$CURRENT_MODIFIED" -gt "$LAST_MODIFIED" ]; then
            echo "🔄 Certificate updated, reloading Nginx..."
            nginx -s reload || true
            LAST_MODIFIED=$CURRENT_MODIFIED
        fi
    fi
    
    sleep 3600  # Check every hour
done

