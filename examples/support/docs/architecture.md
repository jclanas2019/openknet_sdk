# Platform Architecture

## Service Dependency Map

Portal X depends on AuthService for authentication and SessionStore for session persistence.
Portal X depends on Notification Service for sending login alerts and account emails.
Auth Gateway depends on DatabaseCluster for session storage and AuthService for token validation.
Billing API depends on BillingService for payment processing. BillingService depends on
PaymentGateway and DatabaseCluster. BillingService owned by Backend Team.
Analytics Dashboard depends on CacheLayer for query acceleration. Analytics Dashboard
depends on DatabaseCluster for raw data. CacheLayer owned by Platform Team.
Notification Service depends on EmailWorker for outbound email delivery. EmailWorker owned
by Backend Team.

## Ownership

| Component        | Team          |
|------------------|---------------|
| AuthService      | Platform Team |
| SessionStore     | Platform Team |
| DatabaseCluster  | Platform Team |
| CacheLayer       | Platform Team |
| LoadBalancer     | SRE Team      |
| BillingService   | Backend Team  |
| EmailWorker      | Backend Team  |
| PaymentGateway   | Backend Team  |

## SLA Targets

- Portal X: 99.9% uptime, < 300 ms p99 login latency
- Billing API: 99.95% uptime, < 2 s transaction time
- Auth Gateway: 99.99% uptime, < 100 ms p99
- Notification Service: best-effort; email delivery within 60 s

## Known Risk Areas

AuthService is a single point of failure for Portal X and Auth Gateway. Any AuthService
deployment that causes error 503 will produce a P1 incident. DatabaseCluster is shared by
Auth Gateway, BillingService, and Analytics Dashboard; a deadlock or CPU spike on
DatabaseCluster causes cascading error 500 across all three. CacheLayer OOM causes error 500
in Analytics Dashboard. PaymentGateway rate limits (error 429) cause BillingService timeout,
making Billing API unavailable to customers such as Globex and TechCorp.

## Incident History Summary

INC-1001: ACME / Portal X / AuthService null pointer → error 503. Resolved.
INC-1002: Globex / Billing API / BillingService circuit breaker → timeout. Resolved.
INC-1003: TechCorp / Analytics Dashboard / CacheLayer OOM → error 500. Resolved.
INC-1004: Umbrella / Notification Service / EmailWorker retry → error 429. Resolved.
INC-1005: Initech / Auth Gateway / DatabaseCluster deadlock → error 500. Resolved.
INC-1006: ACME / Portal X / AuthService memory leak → intermittent login error. Open.
