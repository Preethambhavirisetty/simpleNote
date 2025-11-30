#!/bin/bash
# Setup SSL certificates for production
# Usage: ./scripts/setup-ssl.sh [email]

set -e

DOMAIN="www.notelite.org"
EMAIL="${1:-admin@notelite.org}"

echo "🔐 Setting up SSL certificates for: $DOMAIN"
echo "📧 Email: $EMAIL"
echo ""

# Check if nginx container is running
if ! docker-compose ps | grep -q simplenote-nginx; then
    echo "⚠️  Nginx container is not running. Starting services..."
    docker-compose up -d simplenote-nginx
    echo "⏳ Waiting for Nginx to be ready..."
    sleep 10
fi

# Set environment variables and run certbot
echo "📝 Requesting SSL certificate from Let's Encrypt..."
docker-compose exec -e DOMAIN="$DOMAIN" -e EMAIL="$EMAIL" simplenote-nginx /usr/local/bin/init-ssl.sh

echo ""
echo "✅ SSL setup complete!"
echo "🌐 Your site should now be accessible at:"
echo "   - https://www.notelite.org"
echo "   - https://notelite.org (redirects to www)"
echo ""
echo "📋 To check certificate status:"
echo "   docker-compose exec simplenote-nginx certbot certificates"

