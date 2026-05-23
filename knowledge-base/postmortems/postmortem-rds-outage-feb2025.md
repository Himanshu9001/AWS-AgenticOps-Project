# Post-Mortem: RDS Connection Exhaustion Outage

**Document Type:** Post-Mortem  
**Domain:** IT Operations  
**Incident ID:** INC-2025-0214  
**Date:** February 14, 2025  
**Duration:** 47 minutes (14:23 – 15:10 UTC)  
**Severity:** P1  
**Status:** Resolved  

---

## Summary

A connection pool misconfiguration in a newly deployed Lambda function caused RDS connection exhaustion on the `agenticops-db` PostgreSQL instance. This resulted in all new database connections being refused, causing 100% error rate on the AgenticOps API for 47 minutes affecting all production users.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 14:18 | New Lambda version `agenticops-pipeline-status:v2.3` deployed via GitHub Actions |
| 14:23 | CloudWatch alarm fires: `RDS-ConnectionsHigh-agenticops-db` (87% threshold) |
| 14:25 | PagerDuty alert sent to on-call engineer (Priya S.) |
| 14:31 | On-call engineer acknowledges, begins investigation |
| 14:35 | API error rate reaches 100% — all requests failing with `FATAL: remaining connection slots are reserved` |
| 14:38 | Root cause identified: new Lambda function creating new connection on every invocation, not reusing pool |
| 14:42 | Decision made: roll back Lambda to v2.2 |
| 14:45 | Lambda rollback executed |
| 14:48 | Connection count begins dropping |
| 15:05 | Connection count returns to normal baseline (42 connections) |
| 15:10 | All alarms resolved, API error rate returns to 0% |
| 15:15 | Incident declared resolved |

---

## Root Cause

The new Lambda function `agenticops-pipeline-status:v2.3` instantiated a new SQLAlchemy engine inside the handler function instead of outside it. In AWS Lambda, code outside the handler is reused across warm invocations (execution context reuse). Code inside the handler runs on every invocation.

**Faulty code (v2.3):**
```python
def handler(event, context):
    # BUG: Engine created on every invocation = new connection pool every time
    engine = create_engine(db_url, pool_size=10, max_overflow=5)
    with engine.connect() as conn:
        result = conn.execute(query)
    return result
```

**Correct code (v2.2 and fix in v2.4):**
```python
# Correct: Engine created once, reused across warm invocations
engine = create_engine(db_url, pool_size=5, max_overflow=2)

def handler(event, context):
    with engine.connect() as conn:
        result = conn.execute(query)
    return result
```

With 150+ concurrent Lambda invocations, each creating a pool of 10 connections, the db.r6g.large instance's `max_connections` of 1365 was exhausted within 5 minutes of deployment.

---

## Contributing Factors

1. **No integration test for connection pool behavior** — unit tests passed, but no load test against real RDS was run pre-deploy
2. **No canary deployment** — new version deployed to 100% traffic immediately
3. **RDS Proxy not yet implemented** — would have absorbed the connection spike
4. **Alarm threshold too high** — alarm at 80% gave only 5 minutes before exhaustion at this connection rate

---

## Impact

- **Duration:** 47 minutes
- **Users affected:** All production users
- **API error rate:** 100% during peak (14:35–14:48)
- **Revenue impact:** Estimated $12,000 based on average transaction value
- **SLA breach:** Yes — 99.9% monthly SLA requires < 43.8 minutes downtime/month

---

## Action Items

| Action | Owner | Due Date | Status |
|---|---|---|---|
| Implement RDS Proxy for all Lambda→RDS connections | DB Team | 2025-03-01 | ✅ Completed |
| Add connection pool placement lint rule to CI | Platform Team | 2025-02-28 | ✅ Completed |
| Lower RDS connection alarm threshold to 60% | On-call Team | 2025-02-17 | ✅ Completed |
| Implement canary deployments for all Lambda functions | Platform Team | 2025-03-15 | 🔄 In Progress |
| Add RDS connection count to deployment runbook checklist | Platform Team | 2025-02-20 | ✅ Completed |

---

## Lessons Learned

1. **Lambda execution context reuse is critical for DB connections** — always initialize DB engines, S3 clients, and Bedrock clients outside the handler
2. **RDS Proxy is mandatory for Lambda→RDS patterns** — it acts as a buffer absorbing connection spikes
3. **Monitor connections at 60%, not 80%** — at high Lambda concurrency, connections can spike from 60% to 100% in under 2 minutes
4. **Canary deployments catch pool issues** — a 10% canary with connection count monitoring would have caught this before full rollout

---

## Related Documents

- `runbook-rds-connection-exhaustion.md`
- `runbook-lambda-errors.md`
- `pipeline-sop-database-pipeline.md`
