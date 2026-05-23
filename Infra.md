# AgenticOps Platform — Infrastructure Reference

**Account:** `011528270076`
**Region:** `us-east-1`
**Repo:** `AWS-AgenticOps-Project`

---

## 1. Storage — S3 Buckets

| Bucket | Purpose | Versioning |
|---|---|---|
| `agenticops-knowledge-base-docs` | Raw KB documents (runbooks, SOPs, post-mortems) | ✅ Enabled |
| `agenticops-artifacts` | OpenAPI schemas, agent outputs | ❌ |
| `agenticops-tf-state` | Future Terraform state | ❌ |

---

## 2. Database — DynamoDB

| Table | Partition Key | TTL | Purpose |
|---|---|---|---|
| `agenticops-task-results` | `taskId` (S) | `ttl` (1 hour) | Async task results, status tracking |
| `agenticops-session-state` | `sessionId` (S) | — | Agent session context |

---

## 3. Messaging — SQS

| Queue | Visibility Timeout | Retention | Purpose |
|---|---|---|---|
| `agenticops-async-tasks` | 330s | 4 hours | Main async task queue |
| `agenticops-async-tasks-dlq` | 30s | 1 day | Dead letter — tasks failing after 3 retries |

**Redrive policy:** maxReceiveCount = 3 → routes to DLQ

---

## 4. AI — Amazon Bedrock

### Knowledge Base

| Resource | Value |
|---|---|
| KB ID | `NLHMUXZM4R` |
| Data Source ID | `B3QL9TOORM` |
| Vector Store | OpenSearch Serverless (AOSS) |
| Embedding Model | `amazon.titan-embed-text-v2` (1024 dims) |
| Chunking | Fixed-size, 300 tokens, 10% overlap |
| Documents | 9 (3 runbooks, 3 post-mortems, 3 pipeline SOPs) |

### Agents

| Agent | ID | Alias ID | Role |
|---|---|---|---|
| `agenticops-supervisor` | `45BDFFSGGZ` | `U4A49NOUEK` | Orchestrator — routes to specialist agents |
| `agenticops-itops-agent` | `UQINWRUDBC` | `4414KWRLQ8` | IT Ops — CloudWatch, EC2, RDS, remediation |
| `agenticops-datapipeline-agent` | `YGZ3D0T7HC` | `VDLDYWNPDK` | Data Pipeline — SFN, Glue, SQS monitoring |

**Model:** `us.anthropic.claude-sonnet-4-6` (all agents)
**Collaboration:** Supervisor → IT Ops + Pipeline (multi-agent)

### Guardrail

| Resource | Value |
|---|---|
| Guardrail ID | `nwnzhu0xw8xg` |
| PII | EMAIL, PHONE, AWS_ACCESS_KEY, PASSWORD → BLOCK |
| Word Filters | `drop database`, `rm -rf`, `delete all`, `format disk` |
| Denied Topics | `competitor-discussion`, `destructive-actions` |
| Content Filters | Hate/Violence/Sexual/Misconduct/Prompt Attack |
| Applied To | All 3 agents |

---

## 5. Compute — Lambda Functions

| Function | Handler | Timeout | Memory | Purpose |
|---|---|---|---|---|
| `agenticops-api-handler` | `handler.lambda_handler` | 60s | 256MB | API entry point — sync/async routing |
| `agenticops-status-handler` | `status.lambda_handler` | 10s | 128MB | Task status polling from DynamoDB |
| `agenticops-async-consumer` | `consumer.lambda_handler` | 300s | 256MB | SQS consumer — invokes supervisor agent |
| `agenticops-itops-get-alarms` | `get_cloudwatch_alarms.lambda_handler` | 30s | 128MB | IT Ops Action Group — CloudWatch alarms |
| `agenticops-itops-describe-resource` | `describe_resource.lambda_handler` | 30s | 128MB | IT Ops Action Group — EC2/RDS state |
| `agenticops-itops-trigger-remediation` | `trigger_remediation.lambda_handler` | 60s | 128MB | IT Ops Action Group — restart/scale/reboot |
| `agenticops-pipeline-list` | `list_pipelines.lambda_handler` | 30s | 128MB | Pipeline Action Group — list SFN/Glue |
| `agenticops-pipeline-status` | `get_pipeline_status.lambda_handler` | 30s | 128MB | Pipeline Action Group — execution history |
| `agenticops-pipeline-trigger` | `trigger_pipeline.lambda_handler` | 60s | 128MB | Pipeline Action Group — start/retry |
| `agenticops-invoke-agent` | `invoke_agent.lambda_handler` | 300s | 256MB | Step Functions — invokes specific agent |
| `agenticops-aggregate-results` | `aggregate_results.lambda_handler` | 300s | 256MB | Step Functions — synthesizes parallel results |

**X-Ray:** Active on all 10 functions
**Runtime:** Python 3.12
**Execution Role:** `agenticops-lambda-execution-role`

---

## 6. Orchestration — Step Functions

| Resource | Value |
|---|---|
| State Machine | `agenticops-workflow` |
| ARN | `arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow` |
| Type | Standard |
| Timeout | 600s |
| Pattern | Parallel (IT Ops + Pipeline) → ReshapeOutput → Aggregate → Succeed |

**Trigger:** EventBridge rule `agenticops-alarm-trigger` on CloudWatch `ALARM` state change

---

## 7. API — API Gateway

| Resource | Value |
|---|---|
| API ID | `ipm0lawtc7` |
| API Name | `agenticops-api` |
| Type | REST, Regional |
| Stage | `dev` |
| Base URL | `https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev` |

### Endpoints

| Method | Path | Lambda | Purpose |
|---|---|---|---|
| POST | `/invoke` | `agenticops-api-handler` | Submit sync or async agent task |
| GET | `/status/{taskId}` | `agenticops-status-handler` | Poll async task result |
| OPTIONS | `/invoke` | Mock | CORS preflight |
| OPTIONS | `/status/{taskId}` | Mock | CORS preflight |

---

## 8. IAM — Roles

| Role | Trusted By | Purpose |
|---|---|---|
| `agenticops-bedrock-agent-role` | `bedrock.amazonaws.com` | Bedrock Agents execution role |
| `agenticops-lambda-execution-role` | `lambda.amazonaws.com` | All Lambda functions execution role |
| `agenticops-stepfunctions-role` | `states.amazonaws.com` | Step Functions execution role |
| `agenticops-kb-role` | `bedrock.amazonaws.com` | Knowledge Base — S3 + AOSS access |

### Key Inline Policies

| Role | Policy | Grants |
|---|---|---|
| `agenticops-lambda-execution-role` | `agenticops-lambda-pipeline-permissions` | SFN, Glue, CloudWatch, EC2, RDS, SSM, AutoScaling |
| `agenticops-bedrock-agent-role` | `agenticops-agent-lambda-invoke` | `lambda:InvokeFunction` on all `agenticops-*` functions |
| `agenticops-stepfunctions-role` | `agenticops-sfn-lambda-invoke` | `lambda:InvokeFunction` on all `agenticops-*` functions |
| `agenticops-kb-role` | `agenticops-kb-aoss-inline` | AOSS collection and index operations |

---

## 9. Observability

### CloudWatch Dashboard

**Name:** `AgenticOps-Platform`

| Widget | Metrics |
|---|---|
| Agent Invocation Errors | Lambda Errors — api-handler, async-consumer, invoke-agent, aggregate-results |
| Lambda Duration p99 | Duration p99 — async-consumer, invoke-agent, aggregate-results |
| SQS Queue Depth | ApproximateNumberOfMessagesVisible — main queue + DLQ |
| Step Functions Executions | ExecutionsStarted, ExecutionsSucceeded, ExecutionsFailed |
| Bedrock Token Usage | InputTokenCount, OutputTokenCount |
| Bedrock Latency p99 | InvocationLatency p99 (30s threshold annotation) |
| DynamoDB Latency | PutItem/GetItem p99 on task-results table |
| Guardrail Interventions | GuardrailInvocationCount, GuardrailBlockedCount |

### CloudWatch Alarms

| Alarm | Metric | Threshold | Action |
|---|---|---|---|
| `AgenticOps-AsyncConsumer-ErrorRate` | Lambda Errors — async-consumer | > 3 in 5 min | Alert |
| `AgenticOps-DLQ-MessageCount` | SQS Visible — DLQ | > 0 in 1 min | Alert |
| `AgenticOps-StepFunctions-Failures` | SFN ExecutionsFailed | ≥ 1 in 5 min | Alert |
| `AgenticOps-Bedrock-HighLatency` | Bedrock InvocationLatency p99 | > 30,000ms | Alert |

### X-Ray Tracing

Active on all 10 Lambda functions — mode: `Active`

---

## 10. SSM Parameter Store — All Parameters

| Parameter | Value |
|---|---|
| `/agenticops/region` | `us-east-1` |
| `/agenticops/s3/kb-docs-bucket` | `agenticops-knowledge-base-docs` |
| `/agenticops/s3/artifacts-bucket` | `agenticops-artifacts` |
| `/agenticops/dynamodb/session-table` | `agenticops-session-state` |
| `/agenticops/dynamodb/results-table` | `agenticops-task-results` |
| `/agenticops/sqs/async-tasks-url` | `https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks` |
| `/agenticops/sqs/async-tasks-dlq-url` | `https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks-dlq` |
| `/agenticops/bedrock/kb-id` | `NLHMUXZM4R` |
| `/agenticops/bedrock/kb-datasource-id` | `B3QL9TOORM` |
| `/agenticops/bedrock/kb-vector-index-arn` | `arn:aws:s3vectors:us-east-1:011528270076:bucket/agenticops-kb-vectors/index/agenticops-kb-index` |
| `/agenticops/bedrock/model-id` | `us.anthropic.claude-sonnet-4-6` |
| `/agenticops/bedrock/guardrail-id` | `nwnzhu0xw8xg` |
| `/agenticops/bedrock/itops-agent-id` | `UQINWRUDBC` |
| `/agenticops/bedrock/itops-agent-alias-id` | `4414KWRLQ8` |
| `/agenticops/bedrock/pipeline-agent-id` | `YGZ3D0T7HC` |
| `/agenticops/bedrock/pipeline-agent-alias-id` | `VDLDYWNPDK` |
| `/agenticops/bedrock/supervisor-agent-id` | `45BDFFSGGZ` |
| `/agenticops/bedrock/supervisor-agent-alias-id` | `U4A49NOUEK` |
| `/agenticops/stepfunctions/workflow-arn` | `arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow` |
| `/agenticops/apigateway/api-id` | `ipm0lawtc7` |
| `/agenticops/apigateway/api-url` | `https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev` |

---

## 11. Architecture Summary

```
User / EventBridge Alarm
        ↓
API Gateway (ipm0lawtc7)
        ↓
agenticops-api-handler Lambda
    ├── Sync  → Supervisor Agent directly
    └── Async → SQS → async-consumer Lambda → Supervisor Agent
                                                      ↓
                                         Step Functions (parallel)
                                          ├── IT Ops Agent
                                          │     ├── KB: NLHMUXZM4R
                                          │     ├── get-cloudwatch-alarms Lambda
                                          │     ├── describe-resource Lambda
                                          │     └── trigger-remediation Lambda
                                          └── Pipeline Agent
                                                ├── KB: NLHMUXZM4R
                                                ├── list-pipelines Lambda
                                                ├── get-pipeline-status Lambda
                                                └── trigger-pipeline Lambda
                                                      ↓
                                         aggregate-results Lambda
                                                      ↓
                                         DynamoDB: agenticops-task-results
```

---

## 12. Request Flow

```
POST /invoke (async: true)
    → api-handler: publish to SQS, write "queued" to DynamoDB → return taskId (202)
    → async-consumer: pick from SQS, invoke supervisor, write "completed" to DynamoDB
    → GET /status/{taskId}: read from DynamoDB → return result
```

---

*Generated: May 2026 | AgenticOps Platform v1.0*