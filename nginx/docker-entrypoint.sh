#!/bin/sh
# Nginx entrypoint - creates self-signed cert if Let's Encrypt certs don't exist

set -e

echo "🚀 Starting Nginx initialization..."

# Generate self-signed certificate if Let's Encrypt certs don't exist
if [ ! -f "/etc/letsencrypt/live/www.notelite.org/fullchain.pem" ]; then
    echo "🔧 Let's Encrypt certificates not found, generating self-signed certificate..."
    mkdir -p /etc/nginx/ssl
    
    # Generate self-signed certificate
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/key.pem \
        -out /etc/nginx/ssl/cert.pem \
        -subj "/C=US/ST=State/L=City/O=NoteLite/CN=www.notelite.org" \
        2>/dev/null || true
    
    # Update nginx config to use self-signed certificates
    if [ -f "/etc/nginx/conf.d/default.conf" ]; then
        sed -i 's|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|ssl_certificate /etc/nginx/ssl/cert.pem;|g' /etc/nginx/conf.d/default.conf
        sed -i 's|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|ssl_certificate_key /etc/nginx/ssl/key.pem;|g' /etc/nginx/conf.d/default.conf
    fi
    
    echo "✅ Self-signed certificate created and nginx config updated"
    echo "⚠️  Note: Replace with Let's Encrypt certificate using: docker-compose exec simplenote-nginx /usr/local/bin/init-ssl.sh"
else
    echo "✅ Let's Encrypt certificates found"
fi

# Test nginx configuration
echo "🔍 Testing Nginx configuration..."
nginx -t || {
    echo "❌ Nginx configuration test failed!"
    echo "📋 Showing error details:"
    nginx -t 2>&1 || true
    exit 1
}

# Start nginx
echo "✅ Starting Nginx..."
exec nginx -g "daemon off;"

