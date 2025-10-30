# 📖 Backend.im Monitoring Runbook

## Alert Types & Response Procedures

### 🔄 Failover Detected

**What it means:**
Traffic has switched from one pool (blue/green) to another due to the primary pool becoming unhealthy.

**Example Alert:**
🔄 Failover Detected
Pool switched: blue → green

**Immediate Actions:**
1. Check the health of the failed pool:
```bash
   # Check container status
   docker-compose ps
   
   # Check logs for the failed pool
   docker-compose logs app_blue --tail=100  # or app_green
   
   # Test health endpoint directly
   curl http://localhost:8081/healthz  # 8081=blue, 8082=green
```

2. Verify the backup pool is handling traffic correctly:
```bash
   # Test through nginx
   curl -i http://localhost:8080/version
   
   # Check X-App-Pool header matches the new pool
```

3. Investigate the root cause:
   - Memory/CPU exhaustion?
   - Application crash?
   - External dependency failure?

**Recovery Steps:**
1. Fix the underlying issue (restart, scale, fix code)
2. Verify the fixed pool is healthy:
```bash
   curl http://localhost:8081/healthz
```
3. Monitor for stability (5-10 minutes)
4. Optionally switch back to original pool:
```bash
   # Update .env
   ACTIVE_POOL=blue  # or green
   
   # Regenerate config and restart
   ./switch-nginx-config.sh
   docker-compose restart nginx
```

---

### 🚨 High Error Rate Detected

**What it means:**
More than X% of requests in the last N requests resulted in 5xx errors.

**Example Alert:**
🚨 High Error Rate Detected
Error rate: 5.50% (threshold: 2.0%)
Errors: 11/200 requests

**Immediate Actions:**
1. Check which pool is serving errors:
```bash
   # View recent nginx logs
   docker-compose logs nginx --tail=50
   
   # Check both app logs
   docker-compose logs app_blue app_green --tail=100
```

2. Identify the error pattern:
   - Is it one endpoint or all endpoints?
   - Is it timing out or returning 500?
   - Is it upstream dependency?

3. Check system resources:
```bash
   docker stats
```

**Recovery Options:**

**Option A: Manual Failover**
If one pool is consistently failing:
```bash
# Switch to the healthy pool
ACTIVE_POOL=green  # in .env
./switch-nginx-config.sh
docker-compose restart nginx
```

**Option B: Restart Unhealthy Container**
```bash
docker-compose restart app_blue  # or app_green
```

**Option C: Rollback**
If a recent deployment caused issues:
```bash
# Update .env with previous image
BLUE_IMAGE=previous-image:tag

# Restart
docker-compose up -d app_blue
```

---

### ✅ Recovery Alert

**What it means:**
The system has returned to normal operation.

**Actions:**
1. Monitor for 15-30 minutes to ensure stability
2. Review incident timeline
3. Update incident log
4. Consider post-mortem if major incident

---

## 🔧 Maintenance Procedures

### Planned Deployment (Suppress Alerts)

When doing planned maintenance or deployments:
```bash
# 1. Enable maintenance mode
echo "MAINTENANCE_MODE=true" >> .env

# 2. Restart watcher
docker-compose restart watcher

# 3. Perform your changes
# ... deploy, test, etc ...

# 4. Disable maintenance mode
sed -i 's/MAINTENANCE_MODE=true/MAINTENANCE_MODE=false/' .env
docker-compose restart watcher
```

### Testing Failover

To test the monitoring system:
```bash
# 1. Induce failure on blue
curl -X POST http://localhost:8081/chaos/start?mode=error

# 2. Generate traffic
for i in {1..50}; do curl http://localhost:8080/version; done

# 3. Check Slack for failover alert

# 4. Stop chaos
curl -X POST http://localhost:8081/chaos/stop
```

### Viewing Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f watcher
docker-compose logs -f nginx
docker-compose logs -f app_blue

# Last N lines
docker-compose logs --tail=100 watcher
```

---

## 📊 Monitoring Dashboard

### Key Metrics to Watch

1. **Active Pool**: Which pool is currently serving traffic
2. **Error Rate**: Percentage of 5xx responses
3. **Request Latency**: Response times from upstreams
4. **Container Health**: CPU, memory, restart count

### Manual Health Check Commands
```bash
# System overview
docker-compose ps

# Resource usage
docker stats --no-stream

# Test endpoints
curl -i http://localhost:8080/version      # Through nginx
curl -i http://localhost:8081/version      # Blue direct
curl -i http://localhost:8082/version      # Green direct

# Nginx status
docker-compose exec nginx nginx -t         # Test config
docker-compose exec nginx nginx -s reload  # Reload config
```

---

## 🆘 Emergency Contacts

- **Slack Channel**: #devops-alerts
- **On-Call**: [Your on-call rotation]
- **Escalation**: [Manager/Team Lead contact]

---

## 📝 Incident Template

When an alert fires, document:
Incident: [Brief description]
Time Started: [Timestamp]
Alert Type: [Failover/Error Rate/Other]
Active Pool: [blue/green]
Actions Taken:

[Action 1]
[Action 2]
Root Cause: [After investigation]
Resolution: [How it was fixed]
Time Resolved: [Timestamp]
Follow-up: [Preventive measures]


---

## 🔍 Troubleshooting Tips

### Watcher Not Sending Alerts
```bash
# Check watcher logs
docker-compose logs watcher

# Verify webhook URL
docker-compose exec watcher env | grep SLACK

# Test webhook manually
curl -X POST $SLACK_WEBHOOK_URL -H 'Content-Type: application/json' -d '{"text":"test"}'
```

### Nginx Logs Not Appearing
```bash
# Check volume mount
docker-compose exec nginx ls -la /var/log/nginx/

# Check nginx is writing logs
docker-compose exec nginx tail -f /var/log/nginx/access.log

# Verify log format
docker-compose exec nginx nginx -T | grep log_format
```

### False Positives
If getting too many alerts:
- Increase `ERROR_RATE_THRESHOLD` (e.g., 5.0)
- Increase `WINDOW_SIZE` (e.g., 500)
- Increase `ALERT_COOLDOWN_SEC` (e.g., 600)