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
| `agenticops-lambda-dlq` | 30s | 1 day | Dead letter — Lambda invocation failures |

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
| Status | ⚠️ Deleted to save ~$350/month AOSS cost — config persists, recreate when needed |

### Agents

| Agent | ID | Alias ID | Version | Role |
|---|---|---|---|---|
| `agenticops-supervisor` | `45BDFFSGGZ` | `U4A49NOUEK` | 2 | Orchestrator — routes to 3 specialist agents |
| `agenticops-itops-agent` | `UQINWRUDBC` | `4414KWRLQ8` | 1 | IT Ops — CloudWatch, EC2, RDS, remediation |
| `agenticops-datapipeline-agent` | `YGZ3D0T7HC` | `VDLDYWNPDK` | 1 | Data Pipeline — SFN, Glue, SQS monitoring |
| `agenticops-research-agent` | `QB1F9WH47O` | `RJ4NBYODD7` | 1 | Research — web search via LangGraph on ECS |

**Model:** `us.anthropic.claude-sonnet-4-6` (all agents)
**Collaboration:** Supervisor → IT Ops + Pipeline + Research (multi-agent, 3 collaborators)

### Multi-Agent Collaborators (Supervisor)

| Collaborator | ID | Collaboration Instruction |
|---|---|---|
| IT Ops Agent | registered | CloudWatch alarms, EC2/RDS issues, Lambda errors, remediation |
| Pipeline Agent | registered | SFN failures, Glue errors, SQS depth, pipeline retries |
| Research Agent | `JCU8X79K3W` | Web search for recent AWS features, external docs, anything not in internal KB |

### Guardrail

| Resource | Value |
|---|---|
| Guardrail ID | `nwnzhu0xw8xg` |
| Published Version | `1` (pinned on all agents — DRAFT not used in production) |
| PII | EMAIL, PHONE, AWS_ACCESS_KEY, PASSWORD → BLOCK |
| Word Filters | `drop database`, `rm -rf`, `delete all`, `format disk` |
| Denied Topics | `competitor-discussion`, `destructive-actions` |
| Content Filters | Hate: Medium, Violence: Medium, Sexual: High, Misconduct: Medium, Prompt Attack: High |
| Applied To | All 4 agents |

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
| `agenticops-research-agent-action` | `handler.lambda_handler` | 130s | 128MB | Research Action Group — bridges Bedrock to ECS FastAPI |

**X-Ray:** Active on all Lambda functions
**Runtime:** Python 3.12
**Execution Role:** `agenticops-lambda-execution-role`
**DLQ:** `agenticops-lambda-dlq` attached to api-handler, async-consumer, invoke-agent, aggregate-results

---

## 6. Container — ECS Fargate (LangGraph Research Agent)

| Resource | Value |
|---|---|
| Cluster | `agenticops-cluster` |
| Service | `agenticops-research-agent` |
| Task Definition | `agenticops-research-agent:5` |
| Image | `011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:v2` |
| ECR Repository | `agenticops-research-agent` |
| CPU | 512 vCPU |
| Memory | 1024 MB |
| Launch Type | FARGATE |
| Desired Count | 1 |
| Public IP | ENABLED (dev — use private subnet + VPC endpoints in prod) |
| Health Check | GET /health every 30s, startPeriod 60s |
| Log Group | `/ecs/agenticops-research-agent` (30 day retention) |
| Task IP | `172.31.85.250` (dynamic — changes on task restart) |

### ECS IAM Roles

| Role | Trusted By | Purpose |
|---|---|---|
| `agenticops-ecs-task-execution-role` | `ecs-tasks.amazonaws.com` | Pull ECR image, write CloudWatch logs |
| `agenticops-ecs-task-role` | `ecs-tasks.amazonaws.com` | SSM read, Bedrock retrieve, ECR pull |

### LangGraph Agent Stack

| Component | Technology |
|---|---|
| Agent Framework | LangGraph StateGraph (ReAct loop) |
| LLM | Claude Sonnet 4.6 via Bedrock Converse API |
| Web Search | Tavily API (search_depth=advanced, max_results=5) |
| KB Retrieval | Bedrock retrieve() API |
| API Server | FastAPI + uvicorn (2 workers) |
| Base Image | python:3.12-slim |

### ECS Cost Control

```bash
# Stop service when not testing (saves ~$15/month)
aws ecs update-service --cluster agenticops-cluster \
  --service agenticops-research-agent --desired-count 0 --region us-east-1

# Restart service
aws ecs update-service --cluster agenticops-cluster \
  --service agenticops-research-agent --desired-count 1 --region us-east-1
```

---

## 7. Orchestration — Step Functions

| Resource | Value |
|---|---|
| State Machine | `agenticops-workflow` |
| ARN | `arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow` |
| Type | Standard |
| Timeout | 600s |
| Pattern | Parallel (IT Ops + Pipeline) → ReshapeOutput → Aggregate → Succeed |

**Trigger:** EventBridge rule `agenticops-alarm-trigger` on CloudWatch `ALARM` state change

---

## 8. API — API Gateway

| Resource | Value |
|---|---|
| API ID | `ipm0lawtc7` |
| API Name | `agenticops-api` |
| Type | REST, Regional |
| Stage | `dev` |
| Base URL | `https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev` |
| WAF ACL | `63a0086a-b7ef-45d3-b6a2-873866006ed3` (attached) |
| API Key Required | Yes — `x-api-key` header on all endpoints |
| Usage Plan | 5 req/sec rate, 10 burst, 1000 req/day quota |

### Endpoints

| Method | Path | Lambda | Purpose |
|---|---|---|---|
| POST | `/invoke` | `agenticops-api-handler` | Submit sync or async agent task |
| GET | `/status/{taskId}` | `agenticops-status-handler` | Poll async task result |
| OPTIONS | `/invoke` | Mock | CORS preflight |
| OPTIONS | `/status/{taskId}` | Mock | CORS preflight |

---

## 9. Security — WAF

| Resource | Value |
|---|---|
| ACL ID | `63a0086a-b7ef-45d3-b6a2-873866006ed3` |
| ACL Name | `agenticops-waf` |
| Scope | REGIONAL |
| Attached To | API Gateway `dev` stage |

| Rule | Priority | Action | Purpose |
|---|---|---|---|
| `RateLimitRule` | 1 | Block | > 100 requests per IP per 5 minutes |
| `AWSManagedRulesCommonRuleSet` | 2 | Block | OWASP Top 10, SQL injection, XSS |
| `AWSManagedRulesKnownBadInputsRuleSet` | 3 | Block | Known malicious payloads |

---

## 10. Networking — VPC

| Resource | Value |
|---|---|
| VPC ID | `vpc-054fbd3d56cb3761a` |
| CIDR | `172.31.0.0/16` |
| Type | Default VPC (recreated) |
| Subnet 1 | `subnet-038c3a0c2d9207068` |
| Subnet 2 | `subnet-07677aebf2a9f8fb1` |
| ECS Security Group | `agenticops-research-agent-sg` |
| SG Inbound | Port 8080 from 172.31.0.0/16 (VPC only) + 0.0.0.0/0 (Lambda access) |
| SG Outbound | All traffic (for ECR pull, Bedrock, SSM, Tavily) |

---

## 11. IAM — Roles and Policies

| Role | Trusted By | Inline Policies |
|---|---|---|
| `agenticops-bedrock-agent-role` | `bedrock.amazonaws.com` | agenticops-bedrock-agent-scoped, agenticops-agent-lambda-invoke, agenticops-agent-s3-artifacts, agenticops-research-agent-invoke, agenticops-inference-profile |
| `agenticops-lambda-execution-role` | `lambda.amazonaws.com` | agenticops-lambda-scoped, agenticops-lambda-dlq-send |
| `agenticops-stepfunctions-role` | `states.amazonaws.com` | agenticops-sfn-lambda-invoke |
| `agenticops-kb-role` | `bedrock.amazonaws.com` | agenticops-kb-aoss-inline |
| `agenticops-ecs-task-execution-role` | `ecs-tasks.amazonaws.com` | AmazonECSTaskExecutionRolePolicy (managed) |
| `agenticops-ecs-task-role` | `ecs-tasks.amazonaws.com` | agenticops-research-agent-permissions |

### Key Policy: agenticops-bedrock-agent-scoped

```json
{
  "BedrockModelInvoke": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": [
    "arn:aws:bedrock:us-east-1::foundation-model/*",
    "arn:aws:bedrock:us-east-1:011528270076:inference-profile/*",
    "arn:aws:bedrock:*::foundation-model/*"
  ]
}
```

> Note: Both `foundation-model/*` AND `inference-profile/*` required for cross-region inference profiles (us.* prefix).

### Key Policy: agenticops-inference-profile

```json
{
  "Actions": ["bedrock:GetInferenceProfile", "bedrock:ListInferenceProfiles"],
  "Resource": "*"
}
```

> Required for cross-region inference profile invocation — commonly missed.

---

## 12. Observability

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

### CloudWatch Alarms → SNS → Email

| Alarm | Metric | Threshold | Severity |
|---|---|---|---|
| `AgenticOps-AsyncConsumer-ErrorRate` | Lambda Errors — async-consumer | > 3 in 5 min | High |
| `AgenticOps-DLQ-MessageCount` | SQS Visible — async-tasks-dlq | > 0 in 1 min | P0 |
| `AgenticOps-LambdaDLQ-MessageCount` | SQS Visible — lambda-dlq | > 0 in 1 min | P0 |
| `AgenticOps-StepFunctions-Failures` | SFN ExecutionsFailed | >= 1 in 5 min | High |
| `AgenticOps-Bedrock-HighLatency` | Bedrock InvocationLatency p99 | > 30,000ms | High |

### SNS Topic

`arn:aws:sns:us-east-1:011528270076:agenticops-alerts` — all alarms send to this topic.

### Cost Budget

| Budget | Service | Limit | Alerts |
|---|---|---|---|
| `agenticops-bedrock-monthly` | Amazon Bedrock | $50/month | 80% actual + 100% forecasted |

### X-Ray Tracing

Active (`Mode=Active`) on all Lambda functions. View at CloudWatch → X-Ray traces → Service map.

### ECS Logs

```bash
aws logs tail /ecs/agenticops-research-agent --since 10m --region us-east-1
```

---

## 13. SSM Parameter Store — All Parameters

| Parameter | Type | Value |
|---|---|---|
| `/agenticops/region` | String | `us-east-1` |
| `/agenticops/s3/kb-docs-bucket` | String | `agenticops-knowledge-base-docs` |
| `/agenticops/s3/artifacts-bucket` | String | `agenticops-artifacts` |
| `/agenticops/dynamodb/session-table` | String | `agenticops-session-state` |
| `/agenticops/dynamodb/results-table` | String | `agenticops-task-results` |
| `/agenticops/sqs/async-tasks-url` | String | `https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks` |
| `/agenticops/sqs/async-tasks-dlq-url` | String | `https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks-dlq` |
| `/agenticops/sqs/lambda-dlq-arn` | String | `arn:aws:sqs:us-east-1:011528270076:agenticops-lambda-dlq` |
| `/agenticops/bedrock/kb-id` | String | `NLHMUXZM4R` |
| `/agenticops/bedrock/kb-datasource-id` | String | `B3QL9TOORM` |
| `/agenticops/bedrock/model-id` | String | `us.anthropic.claude-sonnet-4-6` |
| `/agenticops/bedrock/guardrail-id` | String | `nwnzhu0xw8xg` |
| `/agenticops/bedrock/guardrail-version` | String | `1` |
| `/agenticops/bedrock/itops-agent-id` | String | `UQINWRUDBC` |
| `/agenticops/bedrock/itops-agent-alias-id` | String | `4414KWRLQ8` |
| `/agenticops/bedrock/pipeline-agent-id` | String | `YGZ3D0T7HC` |
| `/agenticops/bedrock/pipeline-agent-alias-id` | String | `VDLDYWNPDK` |
| `/agenticops/bedrock/supervisor-agent-id` | String | `45BDFFSGGZ` |
| `/agenticops/bedrock/supervisor-agent-alias-id` | String | `U4A49NOUEK` |
| `/agenticops/bedrock/research-agent-id` | String | `QB1F9WH47O` |
| `/agenticops/bedrock/research-agent-alias-id` | String | `RJ4NBYODD7` |
| `/agenticops/stepfunctions/workflow-arn` | String | `arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow` |
| `/agenticops/apigateway/api-id` | String | `ipm0lawtc7` |
| `/agenticops/apigateway/api-url` | String | `https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev` |
| `/agenticops/apigateway/usage-plan-id` | String | `<usage-plan-id>` |
| `/agenticops/apigateway/api-key-id` | String | `<api-key-id>` |
| `/agenticops/apigateway/api-key-value` | SecureString | `<api-key — retrieve with --with-decryption>` |
| `/agenticops/waf/acl-id` | String | `63a0086a-b7ef-45d3-b6a2-873866006ed3` |
| `/agenticops/sns/alerts-arn` | String | `arn:aws:sns:us-east-1:011528270076:agenticops-alerts` |
| `/agenticops/ecr/research-agent-uri` | String | `011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent` |
| `/agenticops/vpc/id` | String | `vpc-054fbd3d56cb3761a` |
| `/agenticops/vpc/subnet-ids` | String | `subnet-038c3a0c2d9207068,subnet-07677aebf2a9f8fb1` |
| `/agenticops/vpc/research-agent-sg-id` | String | `<security-group-id>` |
| `/agenticops/ecs/research-agent-ip` | String | `172.31.85.250` (dynamic) |
| `/agenticops/tavily/api-key` | SecureString | `<rotate regularly at app.tavily.com>` |

---

## 14. Architecture Summary

```
User / EventBridge Alarm
        |
    AWS WAF (agenticops-waf)
        |
API Gateway (ipm0lawtc7) + API Key + Usage Plan
        |
agenticops-api-handler Lambda
    |-- Sync  --> Supervisor Agent directly
    |-- Async --> SQS --> async-consumer Lambda --> Supervisor Agent
                                                          |
                                     +--------------------+--------------------+
                                     |                    |                    |
                              IT Ops Agent        Pipeline Agent       Research Agent
                              (Bedrock)           (Bedrock)            (Bedrock)
                                     |                    |                    |
                              Action Groups        Action Groups        web-research AG
                              + KB (RAG)           + KB (RAG)                  |
                                     |                    |            Lambda bridge
                              CloudWatch, EC2      SFN, Glue                   |
                              RDS, SSM, ASG        SQS                ECS Fargate
                                                                      LangGraph + Tavily
                                                          |
                                         Step Functions (parallel)
                                          |-- IT Ops Agent
                                          |-- Pipeline Agent
                                                  |
                                         aggregate-results Lambda
                                                  |
                                         DynamoDB: agenticops-task-results
                                                  |
                                         GET /status/{taskId}
```

---

## 15. Request Flow

```
POST /invoke (async: true)
    --> api-handler: publish to SQS, write "queued" to DynamoDB --> return taskId (202)
    --> async-consumer: pick from SQS, invoke supervisor, write "completed" to DynamoDB
    --> GET /status/{taskId}: read from DynamoDB --> return result

Research query flow:
    --> Supervisor --> Research Agent (Bedrock)
    --> web-research Action Group --> agenticops-research-agent-action Lambda
    --> ECS FastAPI POST /research --> LangGraph ReAct loop
    --> Tavily web search / Bedrock KB retrieve --> synthesized answer
    --> returned up the chain to Supervisor --> user
```

---

*Generated: May 2026 | AgenticOps Platform v1.0 | Production Readiness: 7/10*