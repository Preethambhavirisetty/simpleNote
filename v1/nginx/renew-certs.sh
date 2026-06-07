#!/bin/sh
# Certificate renewal script for Certbot
# This is called by the certbot container to renew certificates

set -e

echo "🔄 Renewing SSL certificates..."

# Renew certificates using webroot method
certbot renew --quiet --webroot --webroot-path=/var/www/certbot

# Reload nginx to use new certificates
if [ $? -eq 0 ]; then
    echo "✅ Certificates renewed successfully"
    echo "🔄 Reloading Nginx..."
    nginx -s reload || true
else
    echo "⚠️  Certificate renewal failed or not needed"
fi

