# Runbook: RDS Connection Exhaustion Response

**Document Type:** Runbook  
**Domain:** IT Operations  
**Severity:** Critical  
**Last Updated:** 2025-02-10  
**Owner:** Database Engineering Team

---

## Overview

This runbook covers the response procedure when RDS DatabaseConnections metric approaches or exceeds the max_connections limit. Connection exhaustion causes new connection attempts to fail with `Too many connections` error, leading to application-wide failures.

---

## Alarm Definition

- **Alarm Name:** `AgenticOps-RDS-ConnectionsHigh-{db-identifier}`
- **Threshold:** DatabaseConnections > 80% of max_connections for 3 minutes
- **Metric:** `AWS/RDS DatabaseConnections`
- **Critical Threshold:** > 95% — treat as P0 incident immediately

---

## Max Connections Reference

| RDS Instance Class | max_connections |
|---|---|
| db.t3.micro | 66 |
| db.t3.medium | 312 |
| db.r6g.large | 1365 |
| db.r6g.xlarge | 2730 |
| db.r6g.2xlarge | 5460 |

Formula: `max_connections = DBInstanceClassMemory / 12582880`

---

## Diagnosis Steps

### Step 1: Check Current Connection Count

```bash
# Get current DatabaseConnections metric
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=agenticops-db \
  --start-time $(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average,Maximum
```

### Step 2: Connect to RDS and Inspect Active Connections

```sql
-- Connect to the database
-- psql -h <rds-endpoint> -U admin -d agenticops

-- Count connections by state
SELECT state, count(*) 
FROM pg_stat_activity 
GROUP BY state;

-- Show connections by application and user
SELECT usename, application_name, client_addr, state, count(*)
FROM pg_stat_activity
GROUP BY usename, application_name, client_addr, state
ORDER BY count DESC;

-- Show long-running queries (> 5 minutes)
SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes'
AND state != 'idle';
```

### Step 3: Identify Connection Source

```sql
-- Check which application is leaking connections
SELECT client_addr, count(*) as connection_count
FROM pg_stat_activity
GROUP BY client_addr
ORDER BY connection_count DESC
LIMIT 10;
```

---

## Remediation Actions

### Action 1: Terminate Idle Connections

```sql
-- Terminate idle connections older than 10 minutes
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
AND query_start < now() - interval '10 minutes'
AND pid <> pg_backend_pid();
```

**Risk:** Low. Idle connections are not processing queries. Applications will reconnect.

### Action 2: Enable RDS Proxy (recommended long-term fix)

RDS Proxy pools and multiplexes connections, reducing the number of direct connections to RDS.

```bash
# Create RDS Proxy via CLI
aws rds create-db-proxy \
  --db-proxy-name agenticops-rds-proxy \
  --engine-family POSTGRESQL \
  --auth '[{"AuthScheme":"SECRETS","SecretArn":"arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:rds-credentials","IAMAuth":"DISABLED"}]' \
  --role-arn arn:aws:iam::ACCOUNT:role/agenticops-rds-proxy-role \
  --vpc-subnet-ids subnet-xxx subnet-yyy \
  --region us-east-1
```

### Action 3: Restart Application Connection Pool

If a specific application is leaking connections, restart its connection pool:

```bash
# Restart the application service to reset pool
sudo systemctl restart agenticops-app

# Verify connection count drops after restart
watch -n 5 'aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=agenticops-db \
  --start-time $(date -u -d "5 minutes ago" +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average'
```

### Action 4: Increase max_connections (emergency only)

```bash
# Modify RDS parameter group
aws rds modify-db-parameter-group \
  --db-parameter-group-name agenticops-pg-params \
  --parameters "ParameterName=max_connections,ParameterValue=1000,ApplyMethod=pending-reboot"

# Reboot required — coordinate downtime window
aws rds reboot-db-instance \
  --db-instance-identifier agenticops-db
```

**Risk:** High — requires reboot, causes ~60 seconds downtime. Use only as last resort.

---

## Prevention

- Always use connection pooling (PgBouncer or RDS Proxy) in front of RDS
- Set `connection_timeout` and `idle_timeout` in application pool config
- Alert at 70% (warning) and 85% (critical) — never wait for 100%
- Review `pg_stat_activity` weekly for idle connection trends

---

## Escalation Path

1. **L1:** Action 1 (terminate idle connections)
2. **L2:** Action 2 or Action 3
3. **L3 DBA:** Action 4 or instance class upgrade

---

## Related Documents

- `runbook-high-cpu-alarm.md`
- `postmortem-rds-outage-feb2025.md`
- `pipeline-sop-database-pipeline.md`
