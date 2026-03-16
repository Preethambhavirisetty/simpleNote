#!/bin/sh
# Initialize SSL certificates for Nginx with Certbot
# This script should be run once to set up SSL certificates

set -e

DOMAIN="${DOMAIN:-www.notelite.org}"
EMAIL="${EMAIL:-admin@notelite.org}"

echo "🔐 Initializing SSL certificates for domain: $DOMAIN"

# Check if certificates already exist
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "✅ SSL certificates already exist for $DOMAIN"
    echo "🔄 Reloading Nginx..."
    nginx -s reload || true
    exit 0
fi

# Wait for nginx to be running (for webroot validation)
echo "⏳ Waiting for Nginx to be ready..."
sleep 5

# Request certificate from Let's Encrypt
echo "📝 Requesting SSL certificate from Let's Encrypt..."
echo "   Domain: $DOMAIN"
echo "   Email: $EMAIL"

# Use webroot method (nginx must be running)
certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN" \
    -d "notelite.org" \
    || {
    echo "⚠️  Certificate request failed. This is normal on first run if:"
    echo "   1. Domain DNS is not pointing to this server yet"
    echo "   2. Port 80 is not accessible from internet"
    echo "   3. Let's Encrypt rate limits (wait 1 hour)"
    echo ""
    echo "🔧 Generating self-signed certificate for now..."
    mkdir -p /etc/nginx/ssl
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/key.pem \
        -out /etc/nginx/ssl/cert.pem \
        -subj "/C=US/ST=State/L=City/O=NoteLite/CN=$DOMAIN"
    
    # Update nginx config to use self-signed cert temporarily
    sed -i "s|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|ssl_certificate /etc/nginx/ssl/cert.pem;|" /etc/nginx/conf.d/default.conf
    sed -i "s|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|ssl_certificate_key /etc/nginx/ssl/key.pem;|" /etc/nginx/conf.d/default.conf
    
    echo "✅ Self-signed certificate created"
    echo "   You can request Let's Encrypt certificate later when DNS is configured"
}

# If Let's Encrypt certificate was obtained, use it
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "✅ Let's Encrypt certificate obtained successfully!"
    # Ensure nginx config uses the correct paths (should already be correct)
fi

echo "🔄 Reloading Nginx..."
nginx -s reload || nginx -t

echo "✅ SSL setup complete"
echo "🌐 Your site should be accessible at https://$DOMAIN"

