# SOP: Database Pipeline Operations

**Document Type:** Pipeline SOP  
**Domain:** Data Pipeline Operations  
**Pipeline Name:** `agenticops-database-pipeline`  
**Last Updated:** 2025-04-01  
**Owner:** Data Engineering Team

---

## Overview

This SOP covers the operation, monitoring, and troubleshooting of the AgenticOps database pipeline. This pipeline handles data quality checks, schema migrations, backup verification, and performance monitoring for the `agenticops-db` RDS PostgreSQL instance used by all platform components.

---

## Pipeline Components

| Component | Purpose | Schedule |
|---|---|---|
| `db-health-check` Lambda | Checks connections, replication lag, query performance | Every 5 minutes |
| `db-backup-verifier` Lambda | Verifies automated RDS backup completion | Daily 06:00 UTC |
| `db-data-quality` Lambda | Runs DQ checks on key tables | Every hour |
| `db-schema-migrator` Lambda | Applies pending Flyway migrations | On deploy |
| `db-metrics-collector` Lambda | Pushes custom DB metrics to CloudWatch | Every 1 minute |

---

## Database Schema Overview

| Table | Purpose | Row Count (approx) | Retention |
|---|---|---|---|
| `agent_sessions` | Active agent session state | ~500 | 24 hours TTL |
| `task_results` | Async task outputs (mirror of DynamoDB) | ~10,000 | 7 days |
| `audit_log` | All agent actions for compliance | ~1M/month | 90 days |
| `pipeline_runs` | Data pipeline execution history | ~50,000 | 30 days |
| `knowledge_base_sync` | KB sync job history and status | ~1,000 | 90 days |

---

## Running Health Checks

### Manual Health Check (CLI)

```bash
# Invoke health check Lambda directly
aws lambda invoke \
  --function-name agenticops-db-health-check \
  --payload '{"check_type": "full"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/health-check-result.json

cat /tmp/health-check-result.json
```

### Expected Healthy Response

```json
{
  "status": "healthy",
  "checks": {
    "connection_count": {"value": 42, "threshold": 800, "status": "ok"},
    "replication_lag_seconds": {"value": 0, "threshold": 30, "status": "ok"},
    "longest_running_query_seconds": {"value": 1.2, "threshold": 60, "status": "ok"},
    "table_bloat_percent": {"value": 3.2, "threshold": 20, "status": "ok"},
    "backup_age_hours": {"value": 6.3, "threshold": 26, "status": "ok"}
  }
}
```

---

## Data Quality Checks

The `db-data-quality` Lambda runs these checks every hour:

| Check | Table | Query | Alert If |
|---|---|---|---|
| Null session IDs | `agent_sessions` | COUNT WHERE session_id IS NULL | > 0 |
| Orphaned task results | `task_results` | Tasks with no matching session | > 100 |
| Audit log gaps | `audit_log` | Gaps > 5 min in timestamps | Any gap |
| Stale pipeline runs | `pipeline_runs` | Runs in RUNNING state > 2 hours | > 0 |
| Failed sync jobs | `knowledge_base_sync` | Status = FAILED in last 24h | > 0 |

### Running DQ Checks Manually

```bash
# Run specific DQ check
aws lambda invoke \
  --function-name agenticops-db-data-quality \
  --payload '{"check": "orphaned_task_results", "dry_run": true}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/dq-result.json

cat /tmp/dq-result.json
```

---

## Schema Migration Procedure

All schema changes go through Flyway migrations. Never apply DDL directly to production.

### Migration File Naming Convention

```
V{version}__{description}.sql
Example: V20250401_001__add_pipeline_run_duration_column.sql
```

### Applying Migrations

```bash
# Dry run (show what will be applied)
aws lambda invoke \
  --function-name agenticops-db-schema-migrator \
  --payload '{"action": "validate"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/migration-validate.json

# Apply pending migrations
aws lambda invoke \
  --function-name agenticops-db-schema-migrator \
  --payload '{"action": "migrate"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/migration-result.json
```

### Rollback Procedure

Flyway does not support automatic rollback. For rollback:
1. Write a new migration `V{version+1}__rollback_{description}.sql` that reverts the change
2. Apply via the migration procedure above
3. Never delete or modify existing migration files

---

## Backup Verification

RDS automated backups run daily. The `db-backup-verifier` Lambda confirms:
1. Latest automated snapshot exists and is not older than 26 hours
2. Snapshot status is `available`
3. Snapshot is encrypted

```bash
# Manually verify backup status
aws rds describe-db-snapshots \
  --db-instance-identifier agenticops-db \
  --snapshot-type automated \
  --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1].{Status:Status, Created:SnapshotCreateTime, Encrypted:Encrypted}' \
  --region us-east-1
```

---

## Troubleshooting

### Issue: High replication lag

**Cause:** Heavy write workload or read replica under-provisioned.

**Diagnosis:**
```sql
-- Check replication lag on read replica
SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;

-- Check write-heavy tables
SELECT schemaname, tablename, n_tup_ins + n_tup_upd + n_tup_del as total_writes
FROM pg_stat_user_tables
ORDER BY total_writes DESC
LIMIT 10;
```

**Fix:** Scale up read replica instance class or reduce write frequency.

---

### Issue: Table bloat > 20%

**Cause:** Dead tuples not cleaned up — VACUUM not running or too slow.

**Fix:**
```sql
-- Run VACUUM ANALYZE on bloated table
VACUUM ANALYZE agent_sessions;

-- Check autovacuum is running
SELECT schemaname, tablename, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
WHERE last_autovacuum < now() - interval '1 day'
ORDER BY last_autovacuum;
```

---

### Issue: Migration FAILED in production

**Cause:** DDL statement failed (constraint violation, lock timeout, etc.)

**Fix:**
1. Check Flyway schema history table:
```sql
SELECT * FROM flyway_schema_history ORDER BY installed_on DESC LIMIT 5;
```
2. Fix the failed migration file (do not delete it — update it)
3. Manually resolve the failed state:
```sql
DELETE FROM flyway_schema_history WHERE success = false;
```
4. Re-apply after fixing

---

## SLA / Performance Targets

| Metric | Target |
|---|---|
| DB connection count | < 60% of max_connections |
| Query p99 latency | < 100ms |
| Replication lag | < 5 seconds |
| Backup age | < 26 hours |
| Migration apply time | < 5 minutes |
| DQ check pass rate | 100% |

---

## Related Documents

- `runbook-rds-connection-exhaustion.md`
- `postmortem-rds-outage-feb2025.md`
- `pipeline-sop-kb-ingestion.md`
- `pipeline-sop-async-pipeline.md`
