# Runbook: Lambda Function Error Rate Alarm Response

**Document Type:** Runbook  
**Domain:** IT Operations  
**Severity:** High  
**Last Updated:** 2025-03-01  
**Owner:** Platform Engineering Team

---

## Overview

This runbook covers the diagnosis and remediation procedure when a Lambda function error rate alarm fires. Lambda errors can cascade into agent action group failures, async pipeline breakdowns, and user-facing API errors across the AgenticOps platform.

---

## Alarm Definition

- **Alarm Name:** `AgenticOps-Lambda-ErrorRate-{function-name}`
- **Threshold:** Errors / Invocations > 5% over 5 minutes
- **Metrics:** `AWS/Lambda Errors`, `AWS/Lambda Invocations`
- **Action:** SNS → PagerDuty

---

## Lambda Error Types

| Error Type | Cause | Typical Fix |
|---|---|---|
| `Runtime.ExitError` | Process crashed, OOM | Increase memory, fix code |
| `Task timed out` | Execution exceeded timeout | Increase timeout or optimize code |
| `AccessDeniedException` | IAM permissions missing | Update IAM role policy |
| `ResourceNotFoundException` | DynamoDB table/SSM param missing | Check resource exists |
| `TooManyRequestsException` | Throttling (concurrency limit) | Increase reserved concurrency |
| `Runtime.ImportModuleError` | Missing dependency in package | Redeploy with correct dependencies |

---

## Diagnosis Steps

### Step 1: Identify Error Type and Rate

```bash
# Get error count for last 30 minutes
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<function-name> \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum

# Get throttle count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Throttles \
  --dimensions Name=FunctionName,Value=<function-name> \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum
```

### Step 2: Check CloudWatch Logs

```bash
# Get latest log stream
aws logs describe-log-streams \
  --log-group-name /aws/lambda/<function-name> \
  --order-by LastEventTime \
  --descending \
  --max-items 5

# Get log events from latest stream
aws logs get-log-events \
  --log-group-name /aws/lambda/<function-name> \
  --log-stream-name <latest-stream-name> \
  --limit 50

# Search for errors using Logs Insights
aws logs start-query \
  --log-group-name /aws/lambda/<function-name> \
  --start-time $(date -d '30 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20'
```

### Step 3: Check Lambda Configuration

```bash
# Check function configuration
aws lambda get-function-configuration \
  --function-name <function-name> \
  --query '{Memory:MemorySize, Timeout:Timeout, Runtime:Runtime, Role:Role}'

# Check concurrency settings
aws lambda get-function-concurrency \
  --function-name <function-name>
```

---

## Remediation Actions

### Action 1: Increase Memory (for OOM or performance issues)

```bash
# Increase memory to 512MB
aws lambda update-function-configuration \
  --function-name <function-name> \
  --memory-size 512
```

Note: Increasing memory also increases vCPU allocation proportionally. Often fixes both OOM and timeout issues.

### Action 2: Increase Timeout

```bash
# Increase timeout to 5 minutes (300 seconds)
aws lambda update-function-configuration \
  --function-name <function-name> \
  --timeout 300
```

Maximum Lambda timeout is 15 minutes (900 seconds). If your function needs more, redesign using Step Functions.

### Action 3: Fix IAM Permissions

```bash
# Check what the function is trying to access in logs first
# Then attach the missing policy to the execution role

aws iam attach-role-policy \
  --role-name agenticops-lambda-execution-role \
  --policy-arn arn:aws:iam::aws:policy/<required-policy>
```

### Action 4: Increase Reserved Concurrency (for throttling)

```bash
# Set reserved concurrency to 100
aws lambda put-function-concurrency \
  --function-name <function-name> \
  --reserved-concurrent-executions 100
```

### Action 5: Rollback to Previous Version

```bash
# List versions
aws lambda list-versions-by-function \
  --function-name <function-name>

# Update alias to point to previous stable version
aws lambda update-alias \
  --function-name <function-name> \
  --name production \
  --function-version <previous-version-number>
```

---

## AgenticOps-Specific Lambda Functions

| Function Name | Role | Common Failure |
|---|---|---|
| `agenticops-itops-get-alarms` | IT Ops Action Group | CloudWatch API throttling |
| `agenticops-itops-remediate` | IT Ops Action Group | IAM missing EC2 permissions |
| `agenticops-pipeline-status` | Data Pipeline Action Group | Glue API timeout |
| `agenticops-async-consumer` | SQS consumer | DynamoDB write failure |
| `agenticops-api-handler` | API Gateway backend | Bedrock invoke timeout |

---

## Escalation Path

1. **L1:** Check logs, identify error type, apply Action 1–3
2. **L2:** Action 4 or Action 5 (rollback)
3. **L3:** Code-level fix required → dev team engagement

---

## Related Documents

- `runbook-high-cpu-alarm.md`
- `postmortem-lambda-cascade-mar2025.md`
- `pipeline-sop-async-pipeline.md`
