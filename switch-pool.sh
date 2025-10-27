#!/bin/bash

# Script to switch active pool and reload Nginx configuration
# Usage: ./switch-pool.sh [blue|green]

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 [blue|green]"
    echo "Current active pool: $(grep ACTIVE_POOL .env | cut -d'=' -f2)"
    exit 1
fi

NEW_POOL=$1

if [ "$NEW_POOL" != "blue" ] && [ "$NEW_POOL" != "green" ]; then
    echo "Error: Pool must be 'blue' or 'green'"
    exit 1
fi

echo "Switching active pool to: $NEW_POOL"

# Update .env file
sed -i "s/ACTIVE_POOL=.*/ACTIVE_POOL=$NEW_POOL/" .env

# Determine backup pool
if [ "$NEW_POOL" = "blue" ]; then
    BACKUP_POOL="green"
else
    BACKUP_POOL="blue"
fi

echo "Active pool: $NEW_POOL"
echo "Backup pool: $BACKUP_POOL"

# Check if nginx container is running
if docker-compose ps nginx | grep -q "Up"; then
    echo "Regenerating and reloading Nginx configuration..."
    
    # Generate new config and reload
    docker-compose exec nginx sh -c "
        export ACTIVE_POOL=$NEW_POOL &&
        export BACKUP_POOL=$BACKUP_POOL &&
        envsubst '\$ACTIVE_POOL \$BACKUP_POOL' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf &&
        nginx -t &&
        nginx -s reload
    "
    
    echo "✅ Pool switched successfully!"
    echo "New configuration active. Test with: curl http://localhost:8080/version"
else
    echo "⚠️  Nginx container not running. Start services with: docker-compose up -d"
    echo "The new configuration will be applied when services start."
fi