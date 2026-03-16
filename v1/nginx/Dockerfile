FROM nginx:alpine

# Install certbot and openssl for SSL certificate management
RUN apk add --no-cache certbot certbot-nginx openssl wget

# Remove default nginx config
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy custom nginx configuration
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/conf.d/default-dev.conf /etc/nginx/conf.d/default-dev.conf

# Copy SSL initialization script
COPY nginx/init-ssl.sh /usr/local/bin/init-ssl.sh
RUN chmod +x /usr/local/bin/init-ssl.sh

# Create directories for SSL and certbot
RUN mkdir -p /var/www/certbot /etc/letsencrypt /etc/nginx/ssl

# Copy entrypoint script
COPY nginx/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Copy renewal script
COPY nginx/renew-certs.sh /usr/local/bin/renew-certs.sh
RUN chmod +x /usr/local/bin/renew-certs.sh

# Copy certificate watcher script
COPY nginx/cert-watcher.sh /usr/local/bin/cert-watcher.sh
RUN chmod +x /usr/local/bin/cert-watcher.sh

# Expose ports
EXPOSE 80 443

# Start nginx with initialization
ENTRYPOINT ["/docker-entrypoint.sh"]

