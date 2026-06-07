#!/bin/sh
# Nginx entrypoint - creates self-signed cert if Let's Encrypt certs don't exist

set -e

echo "🚀 Starting Nginx initialization..."

# Create necessary directories (only writable ones)
mkdir -p /etc/nginx/ssl
# /etc/letsencrypt is mounted as read-only volume, don't try to create it
# /var/www/certbot is mounted as volume, don't try to create it

# Check if Let's Encrypt certificates exist
CERT_FILE="/etc/letsencrypt/live/www.notelite.org/fullchain.pem"
KEY_FILE="/etc/letsencrypt/live/www.notelite.org/privkey.pem"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "🔧 Let's Encrypt certificates not found, generating self-signed certificate..."
    
    # Generate self-signed certificate
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/key.pem \
        -out /etc/nginx/ssl/cert.pem \
        -subj "/C=US/ST=State/L=City/O=NoteLite/CN=www.notelite.org" \
        2>&1
    
    if [ ! -f "/etc/nginx/ssl/cert.pem" ] || [ ! -f "/etc/nginx/ssl/key.pem" ]; then
        echo "❌ Failed to generate self-signed certificate!"
        exit 1
    fi
    
    # Update nginx config to use self-signed certificates
    if [ -f "/etc/nginx/conf.d/default.conf" ]; then
        echo "📝 Updating nginx config to use self-signed certificates..."
        
        # Replace all occurrences of Let's Encrypt cert paths with self-signed paths
        sed -i.bak \
            -e "s|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|ssl_certificate /etc/nginx/ssl/cert.pem;|g" \
            -e "s|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|ssl_certificate_key /etc/nginx/ssl/key.pem;|g" \
            /etc/nginx/conf.d/default.conf
        
        # Verify the replacement worked
        if grep -q "/etc/letsencrypt/live/www.notelite.org" /etc/nginx/conf.d/default.conf; then
            echo "⚠️  Warning: Some Let's Encrypt paths may still be in config"
        fi
    fi
    
    echo "✅ Self-signed certificate created and nginx config updated"
    echo "⚠️  Note: Replace with Let's Encrypt certificate using: docker-compose exec simplenote-nginx /usr/local/bin/init-ssl.sh"
else
    echo "✅ Let's Encrypt certificates found at $CERT_FILE"
    
    # Ensure nginx config uses Let's Encrypt certificates (in case it was changed before)
    if [ -f "/etc/nginx/conf.d/default.conf" ]; then
        # Check if config still has self-signed paths and restore Let's Encrypt paths
        if grep -q "/etc/nginx/ssl/cert.pem" /etc/nginx/conf.d/default.conf; then
            echo "🔄 Updating nginx config to use Let's Encrypt certificates..."
            sed -i.bak \
                -e "s|ssl_certificate /etc/nginx/ssl/cert.pem;|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|g" \
                -e "s|ssl_certificate_key /etc/nginx/ssl/key.pem;|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|g" \
                /etc/nginx/conf.d/default.conf
            echo "✅ Config updated to use Let's Encrypt certificates"
        else
            echo "✅ Config already uses Let's Encrypt certificates"
        fi
    fi
fi

# Wait a bit for certbot to potentially create certificates (if running in background)
# Check again after a short delay in case certbot just created them
sleep 2
if [ ! -f "$CERT_FILE" ] && [ -f "/etc/nginx/ssl/cert.pem" ]; then
    # Still using self-signed, but check if Let's Encrypt certs appeared
    if [ -f "/etc/letsencrypt/live/www.notelite.org/fullchain.pem" ] 2>/dev/null; then
        echo "🔄 Let's Encrypt certificates detected, updating config..."
        sed -i.bak \
            -e "s|ssl_certificate /etc/nginx/ssl/cert.pem;|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|g" \
            -e "s|ssl_certificate_key /etc/nginx/ssl/key.pem;|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|g" \
            /etc/nginx/conf.d/default.conf
    fi
fi

# Test nginx configuration
echo "🔍 Testing Nginx configuration..."
if ! nginx -t; then
    echo "❌ Nginx configuration test failed!"
    echo "📋 Showing error details:"
    nginx -t 2>&1 || true
    exit 1
fi

# Start nginx
echo "✅ Starting Nginx..."
exec nginx -g "daemon off;"

