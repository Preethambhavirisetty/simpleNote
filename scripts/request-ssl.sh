#!/bin/bash
# Request Let's Encrypt SSL certificates
# Usage: ./scripts/request-ssl.sh [email]

set -e

DOMAIN="www.notelite.org"
EMAIL="${1:-admin@notelite.org}"

echo "🔐 Requesting Let's Encrypt SSL certificates for: $DOMAIN"
echo "📧 Email: $EMAIL"
echo ""

# Check if nginx is running
if ! docker compose ps | grep -q "simplenote-nginx.*Up"; then
    echo "❌ Nginx container is not running. Please start it first:"
    echo "   docker compose up -d simplenote-nginx"
    exit 1
fi

# Check if port 80 is accessible
echo "🔍 Verifying domain and port 80 accessibility..."
if ! curl -s -o /dev/null -w "%{http_code}" http://$DOMAIN/.well-known/acme-challenge/test | grep -q "404\|200"; then
    echo "⚠️  Warning: Port 80 might not be accessible from the internet"
    echo "   Make sure:"
    echo "   1. DNS for $DOMAIN points to this server"
    echo "   2. Port 80 is open in firewall"
    echo "   3. No other service is blocking port 80"
fi

echo ""
echo "📝 Requesting certificate from Let's Encrypt..."
echo "   This may take a minute..."

# Use certbot container to request certificates (it has write access to volumes)
docker compose run --rm \
    -e DOMAIN="$DOMAIN" \
    -e EMAIL="$EMAIL" \
    simplenote-certbot \
    certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --non-interactive \
    -d "$DOMAIN" \
    -d "notelite.org" \
    || {
    echo ""
    echo "❌ Certificate request failed!"
    echo ""
    echo "Common reasons:"
    echo "  1. Domain DNS not pointing to this server yet"
    echo "  2. Port 80 not accessible from internet"
    echo "  3. Let's Encrypt rate limits (wait 1 hour)"
    echo "  4. Domain already has certificates that need renewal"
    echo ""
    echo "To check DNS: nslookup $DOMAIN"
    echo "To check port 80: curl -I http://$DOMAIN"
    exit 1
}

echo ""
echo "✅ Certificate obtained successfully!"
echo ""

# Check if certificates exist now
if docker compose exec simplenote-nginx test -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem; then
    echo "🔄 Updating nginx to use Let's Encrypt certificates..."
    
    # Update nginx config to use Let's Encrypt certificates
    docker compose exec simplenote-nginx sh -c '
        if grep -q "/etc/nginx/ssl/cert.pem" /etc/nginx/conf.d/default.conf; then
            echo "📝 Updating nginx config to use Let'\''s Encrypt certificates..."
            sed -i.bak \
                -e "s|ssl_certificate /etc/nginx/ssl/cert.pem;|ssl_certificate /etc/letsencrypt/live/www.notelite.org/fullchain.pem;|g" \
                -e "s|ssl_certificate_key /etc/nginx/ssl/key.pem;|ssl_certificate_key /etc/letsencrypt/live/www.notelite.org/privkey.pem;|g" \
                /etc/nginx/conf.d/default.conf
            
            # Test nginx config
            nginx -t || exit 1
            
            # Reload nginx
            nginx -s reload
            echo "✅ Nginx updated and reloaded"
        else
            echo "✅ Nginx config already uses Let'\''s Encrypt certificates"
            nginx -s reload
        fi
    '
    
    echo ""
    echo "✅ SSL setup complete!"
    echo ""
    echo "🌐 Your site should now be accessible with a trusted certificate at:"
    echo "   - https://www.notelite.org"
    echo "   - https://notelite.org (redirects to www)"
    echo ""
    echo "📋 To verify certificates:"
    echo "   docker compose exec simplenote-nginx certbot certificates"
else
    echo "⚠️  Warning: Certificates requested but not found in nginx container"
    echo "   They may be in a different location. Check:"
    echo "   docker compose exec simplenote-nginx ls -la /etc/letsencrypt/live/"
fi

