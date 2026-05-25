# Operations Runbook — Platform Services

## Overview

This runbook covers common failure modes across Portal X, Billing API, Analytics Dashboard,
Auth Gateway, and Notification Service. Each section describes symptoms, triage steps, and
known resolutions.

---

## AuthService

**Owned by:** Platform Team  
**Depends on:** SessionStore, DatabaseCluster

### Symptoms
- Portal X login error or error 503 on `/auth/token`
- Auth Gateway error 500 on `/sessions/create`
- High latency (> 500 ms) on authentication endpoints

### Triage
1. Check AuthService pod health: `kubectl get pods -n platform -l app=authservice`
2. Inspect logs for `NullPointerException` or JWT validation errors.
3. Check SessionStore connectivity: `redis-cli -h sessionstore ping`
4. Verify DatabaseCluster connectivity and deadlock status.

### Known Resolutions
- **AuthService null pointer (error 503):** Roll back to previous AuthService version.
  AuthService causes error 503 when JWT validation path encounters a null pointer.
- **Memory leak:** AuthService memory leak triggers OOM restart. Increase pod memory limit
  or restart pods as a temporary fix. Root cause: unclosed HTTP client connections.
- **Session store connectivity:** If SessionStore is unreachable, Portal X depends on
  AuthService which in turn depends on SessionStore. Restart SessionStore and verify
  AuthService reconnects.

---

## BillingService

**Owned by:** Backend Team  
**Depends on:** PaymentGateway, DatabaseCluster

### Symptoms
- Billing API timeout or transaction failures
- Error 429 from PaymentGateway (rate limit exceeded)
- BillingService causes timeout on payment processing requests

### Triage
1. Check PaymentGateway health: `curl https://payments.internal/health`
2. Inspect BillingService logs for timeout or error 429.
3. Verify circuit breaker status in BillingService dashboard.

### Known Resolutions
- **PaymentGateway timeout:** BillingService causes timeout when PaymentGateway latency > 2 s.
  Enable circuit breaker via feature flag `BILLING_CIRCUIT_BREAKER=true`.
- **Rate limit (error 429):** Reduce retry frequency; contact PaymentGateway team to raise quota.

---

## CacheLayer

**Owned by:** Platform Team

### Symptoms
- Analytics Dashboard error 500 on query endpoints
- CacheLayer OOM or memory spike
- Slow queries despite warm cache

### Triage
1. Check CacheLayer memory: `redis-cli -h cachelayer info memory`
2. Look for `OOM command not allowed` in CacheLayer logs.
3. Verify result set sizes in Analytics Dashboard query logs.

### Known Resolutions
- **OOM (error 500):** CacheLayer causes error 500 when result set exceeds memory limit.
  Increase `maxmemory` in CacheLayer config. Add `maxmemory-policy allkeys-lru`.
- **Large result bypass:** For queries > 50 MB, Analytics Dashboard should bypass CacheLayer
  and query DatabaseCluster directly.

---

## EmailWorker

**Owned by:** Backend Team  
**Depends on:** SMTP relay (external)

### Symptoms
- Notification Service email delivery failures
- EmailWorker timeout or error 429 from SMTP relay
- Dead-letter queue growth

### Triage
1. Check EmailWorker queue depth: `rabbitmqctl list_queues name messages`
2. Inspect SMTP relay response codes in EmailWorker logs.
3. Verify SMTP quota utilization in relay dashboard.

### Known Resolutions
- **SMTP rate limit (error 429):** EmailWorker causes timeout after retry exhaustion.
  Reduce send rate; increase relay quota for the affected customer tier.
- **Queue overflow:** Notification Service depends on EmailWorker; if EmailWorker is down,
  messages accumulate. Replay from dead-letter queue after resolving EmailWorker.

---

## DatabaseCluster

**Owned by:** Platform Team

### Symptoms
- Error 500 across multiple services (Auth Gateway, BillingService, Analytics Dashboard)
- CPU spike on DatabaseCluster nodes
- Deadlock errors in application logs

### Triage
1. Check active queries: `SELECT * FROM pg_stat_activity WHERE state = 'active';`
2. Look for deadlocks: `SELECT * FROM pg_locks WHERE granted = false;`
3. Verify recent migrations for index changes.

### Known Resolutions
- **Deadlock:** DatabaseCluster deadlock causes cascading error 500 in all dependent services.
  Identify blocking query, add missing index or kill long-running transaction.
- **CPU spike:** Often caused by missing index after migration. Run `EXPLAIN ANALYZE` on slow
  queries; add index as needed.

---

## LoadBalancer

**Owned by:** SRE Team

### Symptoms
- Elevated error rate across all services despite healthy backends
- Health check failures causing premature traffic drain

### Triage
1. Check LoadBalancer access logs for upstream selection failures.
2. Verify health check endpoint for each backend service.

### Known Resolutions
- **Stale health check configuration:** After DatabaseCluster recovery, LoadBalancer may
  continue draining traffic. Reload LoadBalancer config: `nginx -s reload`.
