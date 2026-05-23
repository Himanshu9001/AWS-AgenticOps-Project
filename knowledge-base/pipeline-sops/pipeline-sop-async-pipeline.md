# SOP: Async Agent Task Pipeline

**Document Type:** Pipeline SOP  
**Domain:** Data Pipeline Operations / AI Platform  
**Pipeline Name:** `agenticops-async-task-pipeline`  
**Last Updated:** 2025-03-20  
**Owner:** Platform Engineering Team

---

## Overview

This SOP covers the operation and troubleshooting of the async agent task pipeline. This pipeline handles long-running agent tasks that exceed the synchronous API timeout threshold (30 seconds). Tasks are queued via SQS, processed by a consumer Lambda invoking Bedrock Agents, and results stored in DynamoDB for polling.

---

## Pipeline Architecture

```
API Request (long task)
    ↓
agenticops-api-handler Lambda
    ↓ publishes to SQS
SQS: agenticops-async-tasks
    ↓ triggers (batch=1, visibility=330s)
agenticops-async-consumer Lambda
    ↓ invokes Bedrock Agent
Bedrock Agent (multi-tool execution)
    ↓ result
DynamoDB: agenticops-task-results
    ↓ TTL = 1 hour
Client polls /status/{taskId}
```

---

## Task Lifecycle

| State | Stored In | Meaning |
|---|---|---|
| `queued` | SQS | Task received, not yet picked up |
| `processing` | DynamoDB | Consumer Lambda is running |
| `completed` | DynamoDB | Agent finished, result available |
| `failed` | DynamoDB | Agent failed after retries |
| `expired` | — | TTL elapsed, result purged |

---

## Starting a Task (API)

```bash
# Submit async task via API
curl -X POST https://<api-gateway-url>/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Analyze all CloudWatch alarms from last 24 hours and generate a health report",
    "async": true
  }'

# Response
{
  "taskId": "task-abc123",
  "status": "queued",
  "pollUrl": "/status/task-abc123"
}

# Poll for result
curl https://<api-gateway-url>/status/task-abc123

# Response when complete
{
  "taskId": "task-abc123",
  "status": "completed",
  "result": "...",
  "completedAt": "2025-03-20T10:15:43Z"
}
```

---

## SQS Configuration

| Parameter | Value | Reason |
|---|---|---|
| Visibility timeout | 330 seconds | Lambda timeout (300s) + 30s buffer |
| Message retention | 4 hours | Tasks should complete within 1 hour |
| Max receive count | 3 | Retry 3 times before DLQ |
| DLQ | `agenticops-async-tasks-dlq` | Failed tasks for investigation |

**Critical:** Visibility timeout MUST be greater than Lambda timeout. If Lambda runs for 300s but visibility timeout is 30s, the message becomes visible again at 30s causing duplicate execution.

---

## Monitoring the Pipeline

### Key Metrics

| Metric | CloudWatch Namespace | Alarm Threshold |
|---|---|---|
| Queue depth | SQS/NumberOfMessagesSent | > 50 messages |
| Consumer Lambda errors | Lambda/Errors | > 5% |
| DLQ depth | SQS/ApproximateNumberOfMessagesVisible | > 0 |
| Task result age | Custom/AgenticOps | > 55 min (approaching TTL) |
| Bedrock agent duration | Bedrock/AgentInvocationDuration | > 240s |

### CloudWatch Dashboard Queries

```
# Average task completion time (last 1 hour)
fields @timestamp, taskId, duration
| filter status = "completed"
| stats avg(duration) as avg_duration, max(duration) as max_duration
| sort @timestamp desc

# Failed tasks in last 24 hours
fields @timestamp, taskId, errorMessage
| filter status = "failed"
| sort @timestamp desc
| limit 20
```

---

## Troubleshooting

### Issue: Tasks stuck in `queued` state

**Cause:** Consumer Lambda not running — check Lambda errors or concurrency limit hit.

**Diagnosis:**
```bash
# Check SQS queue depth
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/ACCOUNT/agenticops-async-tasks \
  --attribute-names ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible

# Check Lambda concurrency
aws lambda get-function-concurrency \
  --function-name agenticops-async-consumer
```

**Fix:** Increase Lambda reserved concurrency or check Lambda errors.

---

### Issue: Messages in DLQ

**Cause:** Consumer Lambda failed 3 times on the same message.

**Diagnosis:**
```bash
# Read DLQ messages (non-destructive)
aws sqs receive-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/ACCOUNT/agenticops-async-tasks-dlq \
  --max-number-of-messages 10 \
  --visibility-timeout 30
```

**Fix:**
1. Read the message body to understand what task was requested
2. Check CloudWatch logs for the consumer Lambda around the task's timestamp
3. Fix the underlying issue (Bedrock permissions, timeout, etc.)
4. Redrive DLQ messages back to main queue:

```bash
# Redrive DLQ to main queue
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:us-east-1:ACCOUNT:agenticops-async-tasks-dlq \
  --destination-arn arn:aws:sqs:us-east-1:ACCOUNT:agenticops-async-tasks
```

---

### Issue: Task shows `completed` but result is empty

**Cause:** Bedrock agent returned empty completion or Lambda failed to parse streaming response.

**Diagnosis:**
```bash
# Check DynamoDB result item
aws dynamodb get-item \
  --table-name agenticops-task-results \
  --key '{"taskId": {"S": "task-abc123"}}'
```

**Fix:** Check consumer Lambda CloudWatch logs for the specific taskId — look for Bedrock streaming response parsing errors.

---

### Issue: Duplicate task execution

**Cause:** SQS visibility timeout shorter than Lambda execution time.

**Fix:**
```bash
# Update SQS visibility timeout (must be > Lambda timeout)
aws sqs set-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/ACCOUNT/agenticops-async-tasks \
  --attributes VisibilityTimeout=330
```

Also ensure your consumer Lambda is idempotent — check `taskId` in DynamoDB before processing:

```python
def lambda_handler(event, context):
    for record in event["Records"]:
        task = json.loads(record["body"])
        task_id = task["taskId"]

        # Idempotency check — skip if already processing or completed
        existing = dynamodb.get_item(
            TableName="agenticops-task-results",
            Key={"taskId": {"S": task_id}}
        )
        if existing.get("Item"):
            print(f"Task {task_id} already processed, skipping")
            continue

        # Mark as processing
        dynamodb.put_item(
            TableName="agenticops-task-results",
            Item={
                "taskId": {"S": task_id},
                "status": {"S": "processing"},
                "ttl": {"N": str(int(time.time()) + 3600)}
            }
        )
        # ... invoke bedrock agent
```

---

## SLA / Performance Targets

| Metric | Target |
|---|---|
| Task pickup time (queued → processing) | < 30 seconds |
| Simple task completion | < 2 minutes |
| Complex multi-tool task completion | < 10 minutes |
| DLQ depth | 0 (alert on any DLQ messages) |
| Task result availability | 1 hour after completion |

---

## Related Documents

- `runbook-lambda-errors.md`
- `postmortem-lambda-cascade-mar2025.md`
- `pipeline-sop-kb-ingestion.md`
- `pipeline-sop-database-pipeline.md`
