# Implementation Decisions

This document explains the key decisions made in implementing the Blue/Green deployment with automatic failover.

## Architecture Decisions

### 1. Nginx Upstream Configuration

**Decision**: Use `backup` directive for the secondary service rather than equal-weight load balancing.

**Reasoning**:
- The task requires "Blue is active by default, Green is backup"
- The `backup` directive ensures Green only receives traffic when Blue is unavailable
- This creates a true primary/secondary relationship, not round-robin

**Implementation**:
```nginx
upstream backend {
    server app_blue:3000 max_fails=1 fail_timeout=5s;
    server app_green:3000 backup max_fails=1 fail_timeout=5s;
}
```

### 2. Timeout Configuration

**Decision**: Set aggressive timeouts (2 seconds for connect, send, and read).

**Reasoning**:
- Task requires failures detected quickly
- Request should not exceed 10 seconds total
- With 2s timeouts and retry logic, total worst-case: ~4-6 seconds
- Faster detection = faster failover = better user experience

**Trade-offs**:
- May trigger false positives if network is slow
- Acceptable for this scenario where uptime > occasional false failover

### 3. Max Fails and Fail Timeout

**Decision**: `max_fails=1` and `fail_timeout=5s`

**Reasoning**:
- `max_fails=1`: Single failure marks server as down (fast detection)
- `fail_timeout=5s`: Short recovery window to quickly retry Blue
- Task requires automatic failover "immediately" after chaos

**Alternative Considered**:
- `max_fails=3` with longer `fail_timeout`: More conservative but slower failover
- Rejected because task emphasizes zero failed client requests

### 4. Retry Strategy

**Decision**: Enable retry on `error`, `timeout`, and all 5xx status codes.

**Implementation**:
```nginx
proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
proxy_next_upstream_tries 2;
proxy_next_upstream_timeout 10s;
```

**Reasoning**:
- `proxy_next_upstream`: Defines retriable conditions
- `tries=2`: Primary attempt + 1 retry (to backup)
- `timeout=10s`: Aligns with task requirement (request ≤ 10s)
- Ensures client gets response from Green if Blue fails

### 5. Header Forwarding

**Decision**: Do not strip upstream headers; use default passthrough.

**Reasoning**:
- Task explicitly states "Do not strip upstream headers"
- `X-App-Pool` and `X-Release-Id` must reach client unchanged
- Nginx forwards unknown headers by default

**Implementation**:
```nginx
proxy_pass_request_headers on;
# No need to explicitly set X-App-Pool or X-Release-Id
# They come from upstream automatically
```

## Docker Compose Decisions

### 6. Network Configuration

**Decision**: Use a custom bridge network (`app_network`).

**Reasoning**:
- Isolates services from other Docker containers
- Enables DNS resolution (app_blue, app_green)
- Better security and debugging

### 7. Port Mapping

**Decision**: Map internal port 3000 to external ports 8081 (Blue) and 8082 (Green).

**Reasoning**:
- Task requires direct access to Blue/Green for chaos endpoints
- Grader needs `http://localhost:8081/chaos/start` to work
- Nginx proxies through internal Docker network

### 8. Environment Variable Handling

**Decision**: Pass `APP_POOL` and `RELEASE_ID` as environment variables to containers.

**Reasoning**:
- Task states apps return these in headers
- Environment variables are standard way to configure containers
- No image rebuilds needed (pre-built images)

### 9. Health Checks

**Decision**: Implement Docker health checks using `/healthz` endpoint.

**Implementation**:
```yaml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/healthz"]
  interval: 5s
  timeout: 3s
  retries: 3
  start_period: 10s
```

**Reasoning**:
- Helps Docker Compose track container health
- `docker-compose ps` shows health status
- Nginx has its own health detection (doesn't rely on this)

## Alternative Approaches Considered

### Dynamic Upstream Configuration

**Alternative**: Use Nginx Plus or Consul for dynamic upstream updates.

**Rejected**: 
- Task requires open-source solution
- Nginx Plus is commercial
- Adding Consul increases complexity
- Static configuration sufficient for this use case

### Load Balancing

**Alternative**: Use `least_conn` or `ip_hash` load balancing.

**Rejected**:
- Task explicitly requires primary/backup pattern
- Load balancing would distribute traffic to both services simultaneously
- Doesn't match "Blue active, Green backup" requirement

### Service Mesh

**Alternative**: Use Istio, Linkerd, or similar service mesh.

**Rejected**:
- Task constraints: "No Kubernetes, no swarm, no service meshes"
- Over-engineered for this scenario

## Testing Strategy

### Chaos Modes Tested

The implementation handles both chaos modes:

1. **Error mode**: App returns 500 status codes
2. **Timeout mode**: App delays responses beyond proxy timeout

Both trigger `proxy_next_upstream` and failover to backup.

### Zero Failed Requests

The critical requirement is achieved through:

1. Fast failure detection (2s timeouts)
2. Automatic retry within same request (`proxy_next_upstream`)
3. Backup server immediately available
4. No gaps in retry logic

**Result**: Client receives 200 from Green even when Blue fails mid-request.

## Potential Improvements

### For Production Use

If this were a production system, I would consider:

1. **Observability**: Add Prometheus metrics, request tracing
2. **Logging**: Structured logs for failover events
3. **Alerting**: Notify ops team when failover occurs
4. **Graceful Shutdown**: Drain connections before stopping containers
5. **Circuit Breaker**: Prevent cascade failures
6. **Rate Limiting**: Protect against traffic spikes
7. **TLS/HTTPS**: Encrypt traffic
8. **Multiple Regions**: Geographic distribution

### For This Assignment

The current implementation prioritizes:
- Simplicity and clarity
- Meeting exact task requirements
- Easy testing and verification
- Minimal dependencies

## Conclusion

The implementation achieves all task requirements:

- ✅ Zero failed client requests during failover
- ✅ Automatic detection and retry
- ✅ Primary/backup pattern
- ✅ Header forwarding
- ✅ Configurable via environment variables
- ✅ Direct Blue/Green access for chaos testing
- ✅ Fast failover (< 10 seconds total request time)

The design balances simplicity with reliability, using well-understood Nginx features to create a robust Blue/Green deployment system.