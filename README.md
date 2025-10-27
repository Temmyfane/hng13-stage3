# Blue/Green Deployment with Nginx Auto-Failover

This project implements a Blue/Green deployment system using Docker Compose and Nginx with automatic failover capabilities.

## Overview

- **Blue/Green Services**: Two identical Node.js applications running in separate containers
- **Nginx Proxy**: Load balancer with automatic failover from Blue (primary) to Green (backup)
- **Zero Downtime**: Automatic failover with zero failed client requests
- **Manual Toggle**: Support for switching active pools via configuration

## Architecture

```
Client → Nginx (8080) → Blue (8081) [Primary]
                     → Green (8082) [Backup]
```

## Quick Start

1. **Clone and Setup**:
   ```bash
   git clone <your-repo-url>
   cd <repo-directory>
   cp .env.example .env
   ```

2. **Configure Environment**:
   Edit `.env` file with your actual image URLs:
   ```bash
   BLUE_IMAGE=your-registry/app:blue-tag
   GREEN_IMAGE=your-registry/app:green-tag
   ```

3. **Start Services**:
   ```bash
   docker-compose up -d
   ```

4. **Verify Deployment**:
   ```bash
   curl http://localhost:8080/version
   ```

## Endpoints

### Public Endpoint (via Nginx)
- `http://localhost:8080/version` - Main application endpoint with automatic failover

### Direct Service Access
- `http://localhost:8081/version` - Blue service direct access
- `http://localhost:8082/version` - Green service direct access

### Chaos Testing
- `POST http://localhost:8081/chaos/start?mode=error` - Trigger Blue service errors
- `POST http://localhost:8081/chaos/start?mode=timeout` - Trigger Blue service timeouts
- `POST http://localhost:8081/chaos/stop` - Stop chaos mode

### Health Checks
- `http://localhost:8081/healthz` - Blue service health
- `http://localhost:8082/healthz` - Green service health

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BLUE_IMAGE` | Docker image for Blue service | Required |
| `GREEN_IMAGE` | Docker image for Green service | Required |
| `ACTIVE_POOL` | Primary service (blue/green) | `blue` |
| `RELEASE_ID_BLUE` | Blue service release identifier | `blue-v1.0.0` |
| `RELEASE_ID_GREEN` | Green service release identifier | `green-v1.0.0` |
| `PORT` | Application internal port | `3000` |

### Switching Active Pool

#### Option 1: Using the Helper Script (Recommended)
```bash
./switch-pool.sh green
```

#### Option 2: Manual Process
1. Update `.env`:
   ```bash
   ACTIVE_POOL=green
   ```

2. Regenerate and reload Nginx config:
   ```bash
   docker-compose exec nginx sh -c "
     export ACTIVE_POOL=green &&
     export BACKUP_POOL=blue &&
     envsubst '\$ACTIVE_POOL \$BACKUP_POOL' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf &&
     nginx -s reload
   "
   ```

## Testing

### Automated Testing
Run the comprehensive test suite:
```bash
./test-failover.sh
```

### Manual Testing

1. **Baseline Test**:
   ```bash
   curl -i http://localhost:8080/version
   # Should return X-App-Pool: blue
   ```

2. **Trigger Failover**:
   ```bash
   curl -X POST http://localhost:8081/chaos/start?mode=error
   curl -i http://localhost:8080/version
   # Should return X-App-Pool: green
   ```

3. **Stress Test**:
   ```bash
   for i in {1..20}; do curl -s http://localhost:8080/version | grep pool; done
   # All requests should return 200 with green pool
   ```

4. **Recovery Test**:
   ```bash
   curl -X POST http://localhost:8081/chaos/stop
   sleep 10
   curl -i http://localhost:8080/version
   # Should return X-App-Pool: blue (recovered)
   ```

## Failover Behavior

### Automatic Failover Triggers
- HTTP 5xx errors from primary service
- Connection timeouts (2s)
- Service unavailability

### Failover Characteristics
- **Detection Time**: ~2 seconds
- **Total Request Time**: <10 seconds maximum
- **Failed Requests**: Zero (requests retry to backup automatically)
- **Recovery**: Automatic when primary service recovers

### Headers Preserved
- `X-App-Pool`: Identifies which service handled the request
- `X-Release-Id`: Service release identifier
- All other upstream headers passed through unchanged

## Troubleshooting

### Common Issues

1. **Services not starting**:
   ```bash
   docker-compose logs
   ```

2. **Nginx config errors**:
   ```bash
   docker-compose exec nginx nginx -t
   ```

3. **Network connectivity**:
   ```bash
   docker-compose exec nginx nslookup app_blue
   docker-compose exec nginx nslookup app_green
   ```

### Logs

- **Nginx Access Logs**: `docker-compose logs nginx`
- **Service Logs**: `docker-compose logs app_blue app_green`
- **All Logs**: `docker-compose logs -f`

## Files Structure

- `docker-compose.yml` - Main orchestration file
- `.env` - Environment configuration (copy from `.env.example`)
- `.env.example` - Template for environment variables
- `nginx.conf.template` - Nginx configuration template with variable substitution
- `nginx.conf` - Generated Nginx configuration (auto-created)
- `switch-pool.sh` - Helper script for switching active pools
- `test-failover.sh` - Comprehensive test suite
- `DECISION.md` - Architecture decisions and reasoning
- `README.md` - This file

## Architecture Decisions

See [DECISION.md](DECISION.md) for detailed explanations of implementation choices and trade-offs.

## Requirements Met

- ✅ Zero failed client requests during failover
- ✅ Automatic detection and retry within same request
- ✅ Primary/backup pattern with Blue default active
- ✅ Header forwarding (X-App-Pool, X-Release-Id)
- ✅ Configurable via environment variables
- ✅ Direct Blue/Green access for chaos testing
- ✅ Fast failover (<10 seconds total request time)
- ✅ Docker Compose orchestration
- ✅ Nginx templating support with reload capability