# AgenticOps Platform — Troubleshooting Guide

> A complete record of every issue encountered during the build of the AgenticOps platform, the root cause, and the exact fix applied. Use this as a debugging reference when issues recur.

---

## Table of Contents

- [Phase 2 — Knowledge Base Issues](#phase-2--knowledge-base-issues)
- [Phase 3 — IT Ops Agent Issues](#phase-3--it-ops-agent-issues)
- [Phase 4 — Data Pipeline Agent Issues](#phase-4--data-pipeline-agent-issues)
- [Phase 5 — Supervisor / Multi-Agent Issues](#phase-5--supervisor--multi-agent-issues)
- [Phase 6 — Async Pipeline Issues](#phase-6--async-pipeline-issues)
- [Phase 7 — Step Functions Issues](#phase-7--step-functions-issues)
- [Phase 10 — API Gateway / CORS Issues](#phase-10--api-gateway--cors-issues)
- [Research Agent Phase B — Dockerfile / Docker / ECR Issues](#research-agent-phase-b--dockerfile--docker--ecr-issues)
- [Research Agent Phase C — ECS Fargate Issues](#research-agent-phase-c--ecs-fargate-issues)
- [Research Agent Phase D — Bedrock Wiring Issues](#research-agent-phase-d--bedrock-wiring-issues)
- [General AWS CLI Issues](#general-aws-cli-issues)
- [Quick Diagnostic Commands](#quick-diagnostic-commands)

---

## Phase 2 — Knowledge Base Issues

---

### Issue 1: Model Access Page Retired

**Symptom:**
Navigating to Bedrock Model Access showed "Model access page has been retired" instead of a toggle list.

**Root Cause:**
AWS retired the manual model access page. Serverless foundation models are now automatically enabled on first invocation.

**Fix:**
No action needed. Models are enabled automatically. For Anthropic models, first-time users may need to submit use case details — this is prompted on first invocation via console playground.

**Lesson:**
AWS console UI changes frequently. When a page looks different from documentation, check the AWS blog or changelog before debugging.

---

### Issue 2: S3 Vectors — Filterable Metadata Exceeds 2048 Bytes

**Symptom:**
```
Encountered error: Invalid record for key 'xxx': Filterable metadata must have
at most 2048 bytes (Service: S3Vectors, Status Code: 400)
```

**Root Cause:**
S3 Vectors has a hard 2048-byte limit on filterable metadata per vector record. Bedrock KB's internal serialization of chunk data + metadata exceeded this limit even with minimal metadata (3 short fields). This is a Bedrock + S3 Vectors integration bug — the error occurred even with zero metadata files uploaded.

**What We Tried:**
1. Simplified metadata from typed format to flat key-value → still failed
2. Removed all metadata files entirely → still failed
3. Switched from hierarchical to fixed-size chunking → still failed

**Fix:**
Abandoned S3 Vectors entirely. Deleted S3 vector bucket and index, recreated Knowledge Base with **OpenSearch Serverless** as the vector store.

```bash
aws s3vectors delete-index \
  --vector-bucket-name agenticops-kb-vectors \
  --index-name agenticops-kb-index \
  --region us-east-1

aws s3vectors delete-vector-bucket \
  --vector-bucket-name agenticops-kb-vectors \
  --region us-east-1

# Recreate KB via console with AOSS
# Bedrock → Knowledge Bases → Create → Quick create OpenSearch Serverless
```

**Lesson:**
S3 Vectors is a brand-new service (launched late 2025). Bedrock's integration with it has rough edges. In production, use OpenSearch Serverless — it's battle-tested with Bedrock KB and supports metadata filtering, hybrid search, and has no per-record size limits.

---

### Issue 3: KB Creation Failing Silently — Missing AOSS Permissions

**Symptom:**
KB creation showed "in progress" for 10+ minutes then silently failed. `list-knowledge-bases` returned `[]`.

**Root Cause:**
`agenticops-kb-role` was missing OpenSearch Serverless permissions. Bedrock KB needs to create AOSS data access policies on your behalf.

**Diagnosis:**
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateKnowledgeBase \
  --region us-east-1 \
  --query 'Events[0].CloudTrailEvent' \
  --output text | python3 -m json.tool
```

CloudTrail showed `ValidationException`:
```
User: agenticops-kb-role is not authorized to perform: s3vectors:QueryVectors
```

**Fix:**
```bash
aws iam attach-role-policy \
  --role-name agenticops-kb-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonOpenSearchServiceFullAccess

aws iam attach-role-policy \
  --role-name agenticops-kb-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonOpenSearchIngestionFullAccess

aws iam put-role-policy \
  --role-name agenticops-kb-role \
  --policy-name agenticops-kb-aoss-inline \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "aoss:APIAccessAll",
        "aoss:BatchGetCollection",
        "aoss:CreateCollection",
        "aoss:CreateAccessPolicy",
        "aoss:UpdateAccessPolicy",
        "aoss:GetSecurityPolicy",
        "aoss:CreateSecurityPolicy"
      ],
      "Resource": "*"
    }]
  }'
```

**Lesson:**
`AmazonBedrockFullAccess` does NOT include OpenSearch Serverless permissions. AOSS uses its own IAM namespace (`aoss:*`) that must be explicitly granted. Always check CloudTrail when AWS resource creation fails silently — the console UI masks the real error.

---

### Issue 4: KB Ingestion Failed — Wrong Metadata JSON Format

**Symptom:**
```
Ignored 9 files as metadata file is not in valid JSON format
```

**Root Cause:**
Metadata files used DynamoDB-style typed format instead of Bedrock KB's flat key-value format.

**Wrong format:**
```json
{
  "metadataAttributes": {
    "doc_type": {"value": {"stringValue": "runbook"}, "type": "STRING"}
  }
}
```

**Correct format:**
```json
{
  "metadataAttributes": {
    "doc_type": "runbook",
    "domain": "itops",
    "severity": "high"
  }
}
```

**Fix:**
Regenerated all 9 metadata files with flat format and re-uploaded to S3.

```bash
# Re-upload metadata files only
aws s3 cp knowledge-base/ s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --exclude "*" \
  --include "*.metadata.json" \
  --region us-east-1
```

**Lesson:**
Bedrock KB metadata format is flat key-value only. Always test with one document before bulk uploading.

---

### Issue 5: S3 Bucket Accidentally Emptied

**Symptom:**
After running `aws s3 rm` to remove metadata files, all 9 `.md` documents were also deleted.

**Root Cause:**
`aws s3 rm --include "*.metadata.json"` without `--exclude "*"` first defaults to deleting ALL files.

**Wrong command:**
```bash
aws s3 rm s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --include "*.metadata.json"   # BUG: deletes everything
```

**Correct command:**
```bash
aws s3 rm s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --exclude "*" \               # exclude all first
  --include "*.metadata.json"   # then include only metadata
```

**Fix:**
```bash
aws s3 cp knowledge-base/ s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --exclude "*" \
  --include "*.md" \
  --region us-east-1
```

**Lesson:**
`aws s3 rm/cp` flag order is critical. `--exclude` must always come before `--include`. Always do a dry-run check with `aws s3 ls` before destructive S3 operations.

---

### Issue 6: Ingestion Complete but 0 Documents Indexed

**Symptom:**
```json
{"Status": "COMPLETE", "Scanned": 0, "Indexed": 0, "Failed": 0}
```

**Root Cause:**
The S3 bucket was empty when the ingestion ran (from Issue 5 above).

**Fix:**
Re-upload documents, trigger new ingestion job.

**Lesson:**
`COMPLETE` with `Scanned: 0` means the job ran but found no files. Always verify S3 bucket contents before triggering ingestion.

---

### Issue 7: Inference Profile Required for Newer Claude Models

**Symptom:**
```
Invocation of model ID anthropic.claude-sonnet-4-5-20250929-v1:0 with on-demand
throughput isn't supported. Retry your request with the ID or ARN of an inference profile.
```

**Root Cause:**
Newer Claude models require inference profiles (cross-region routing) instead of direct model IDs.

**Fix:**
```bash
# Wrong
"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5..."

# Correct
"modelArn": "arn:aws:bedrock:us-east-1:011528270076:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# List available inference profiles
aws bedrock list-inference-profiles \
  --region us-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude-sonnet')].{ID:inferenceProfileId}"
```

**Lesson:**
Always use the versioned inference profile ARN (`us.*` prefix) in production — never the short alias or foundation model ID directly.

---

## Phase 3 — IT Ops Agent Issues

---

### Issue 8: Action Group Creation — "Must specify roleArn and roleSessionName"

**Symptom:**
```
ValidationException: You must specify a value for roleArn and roleSessionName
```

**Root Cause:**
The agent role hadn't been explicitly saved/associated with the agent before creating action groups.

**Fix:**
```bash
# Save agent with explicit role ARN first
aws bedrock-agent update-agent \
  --agent-id "UQINWRUDBC" \
  --agent-name "agenticops-itops-agent" \
  --agent-resource-role-arn "arn:aws:iam::011528270076:role/agenticops-bedrock-agent-role" \
  --foundation-model "us.anthropic.claude-sonnet-4-6" \
  --instruction "..." \
  --region us-east-1

# Add Lambda invoke permission to agent role
aws iam put-role-policy \
  --role-name agenticops-bedrock-agent-role \
  --policy-name agenticops-agent-lambda-invoke \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:us-east-1:011528270076:function:agenticops-*"
    }]
  }'

# Add Lambda resource-based policy
aws lambda add-permission \
  --function-name agenticops-itops-get-alarms \
  --statement-id bedrock-agent-invoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn "arn:aws:bedrock:us-east-1:011528270076:agent/UQINWRUDBC" \
  --region us-east-1
```

**Lesson:**
Bedrock Agents need permissions at two levels — identity-based policy on the agent role AND resource-based policy on the Lambda. Both are required.

---

### Issue 9: Console — "Must save agent with Agent Resource Role before adding Action Group from S3"

**Symptom:**
Console showed error when trying to add Action Group with S3 schema before the agent role was explicitly saved.

**Root Cause:**
The agent was created without explicitly associating the IAM role via the console form.

**Fix:**
Use `update-agent` CLI command to explicitly set the role ARN, then retry Action Group creation.

---

## Phase 4 — Data Pipeline Agent Issues

---

### Issue 10: Pipeline Lambda — AccessDeniedException on ListStateMachines

**Symptom:**
```
ClientError: An error occurred (AccessDeniedException) when calling the
ListStateMachines operation: User: agenticops-lambda-execution-role is not
authorized to perform: states:ListStateMachines
```

**Root Cause:**
`agenticops-lambda-execution-role` did NOT include Step Functions, Glue, EC2, RDS, or SSM permissions.

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-lambda-execution-role \
  --policy-name agenticops-lambda-pipeline-permissions \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "states:ListStateMachines", "states:ListExecutions",
        "states:StartExecution", "states:DescribeExecution",
        "glue:GetJobs", "glue:GetJobRuns", "glue:StartJobRun",
        "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricStatistics",
        "ec2:DescribeInstances", "rds:DescribeDBInstances",
        "ssm:SendCommand", "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:SetDesiredCapacity"
      ],
      "Resource": "*"
    }]
  }'
```

**Lesson:**
`AWSLambdaBasicExecutionRole` only grants CloudWatch Logs access. Every AWS API needs explicit IAM permission. Test Lambda functions individually before wiring to agents.

---

### Issue 11: Pipeline Lambda — Read Timeout from Empty Step Functions Account

**Symptom:**
```
urllib3.exceptions.ReadTimeoutError: AWSHTTPSConnectionPool: Read timed out.
```

**Root Cause:**
`list_state_machines()` returned no results — no Step Functions in the account. The Bedrock agent ReAct loop stalled waiting for meaningful data.

**Fix:**
```python
if pipeline_type in ["all", "stepfunctions"]:
    try:
        response = sfn.list_state_machines(maxResults=20)
        for sm in response["stateMachines"]:
            pipelines.append({...})
    except Exception as e:
        pipelines.append({"type": "stepfunctions", "error": str(e)})

return {
    "messageVersion": "1.0",
    "response": {
        "body": json.dumps({
            "pipelineCount": len(pipelines),
            "pipelines": pipelines,
            "note": "No pipelines found" if not pipelines else ""
        })
    }
}
```

**Lesson:**
Action Group Lambdas must always return a response quickly — even if the result is empty. Handle empty/no-resource scenarios gracefully with an informative message rather than hanging.

---

## Phase 5 — Supervisor / Multi-Agent Issues

---

### Issue 12: SUPERVISOR_ROUTER Mode on Specialist Agents

**Symptom:**
```
ValidationException: This agent cannot be prepared. The AgentCollaboration
attribute is set to SUPERVISOR_ROUTER but no agent collaborators are added.
```

**Root Cause:**
Set both specialist agents to `SUPERVISOR_ROUTER` collaboration mode — this mode is for agents that ARE supervisors, not agents being supervised.

**Fix:**
```bash
# Specialist agents → DISABLED
aws bedrock-agent update-agent --agent-id "UQINWRUDBC" --agent-collaboration "DISABLED" ...

# Supervisor only → SUPERVISOR
aws bedrock-agent update-agent --agent-id "45BDFFSGGZ" --agent-collaboration "SUPERVISOR" ...
```

**Collaboration modes:**
| Mode | Used By | Meaning |
|---|---|---|
| `DISABLED` | Specialist agents | Can be called as collaborator, cannot delegate further |
| `SUPERVISOR` | Supervisor agent | Can delegate to registered collaborators |
| `SUPERVISOR_ROUTER` | Not used in this project | Supervisor that only routes, does no work itself |

---

### Issue 13: Invalid Service Principal `bedrock-agent.amazonaws.com`

**Symptom:**
```
MalformedPolicyDocument: Invalid principal in policy: "SERVICE":"bedrock-agent.amazonaws.com"
```

**Root Cause:**
`bedrock-agent.amazonaws.com` does not exist as a service principal.

**Fix:**
```json
{
  "Principal": {"Service": "bedrock.amazonaws.com"},
  "Action": "sts:AssumeRole"
}
```

**Lesson:**
`bedrock.amazonaws.com` is the single service principal for all Bedrock services including agents.

---

## Phase 6 — Async Pipeline Issues

---

### Issue 14: DynamoDB Reserved Keyword `result`

**Symptom:**
```
ClientError: An error occurred (ValidationException) when calling the UpdateItem
operation: Invalid UpdateExpression: Attribute name is a reserved keyword;
reserved keyword: result
```

**Root Cause:**
`result` is one of 570+ DynamoDB reserved keywords.

**Fix:**
```python
# Wrong
table.update_item(
    Key={"taskId": task_id},
    UpdateExpression="SET #s = :s, result = :r",   # BUG: 'result' is reserved
    ...
)

# Correct
table.update_item(
    Key={"taskId": task_id},
    UpdateExpression="SET #s = :s, #r = :r",
    ExpressionAttributeNames={"#s": "status", "#r": "result"},
    ExpressionAttributeValues={":s": "completed", ":r": agent_result}
)
```

**Common reserved keywords:** `name`, `status`, `result`, `value`, `data`, `type`, `key`, `size`, `count`, `date`, `time`, `index`, `range`, `table`

**Lesson:**
Always use `ExpressionAttributeNames` for attribute names. Better: prefix all attribute names with your app (`ag_result`, `ag_status`) to avoid conflicts entirely.

---

### Issue 15: Async Task Showing `not_found` Immediately

**Symptom:**
Task submitted successfully (got `taskId`) but status poll returned `{"status": "not_found"}` even after 30 seconds.

**Root Cause:**
Polling started before consumer Lambda had written the initial `queued` status to DynamoDB.

**Fix:**
```python
time.sleep(5)  # wait for initial write

for i in range(36):  # poll up to 3 minutes
    item = table.get_item(Key={"taskId": task_id}).get("Item", {})
    status = item.get("status", "not_found")
    if status in ["completed", "failed"]:
        break
    time.sleep(5)
```

---

## Phase 7 — Step Functions Issues

---

### Issue 16: Step Functions Role Missing Lambda Invoke Permission

**Symptom:**
```
ExecutionFailed: Lambda.AWSLambdaException: User: agenticops-stepfunctions-role
is not authorized to perform: lambda:InvokeFunction
```

**Root Cause:**
`AWSStepFunctionsFullAccess` grants management plane permissions but NOT the ability to invoke Lambda functions.

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-stepfunctions-role \
  --policy-name agenticops-sfn-lambda-invoke \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:us-east-1:011528270076:function:agenticops-*"
    }]
  }'
```

**Lesson:**
`AWSStepFunctionsFullAccess` only manages Step Functions resources. Each service integration needs its own IAM permission on the execution role.

---

### Issue 17: `States.ReferencePathConflict` After Parallel State

**Symptom:**
```
ExecutionFailed: States.ReferencePathConflict: Unable to apply step
"aggregatedResult" to input [array output from Parallel state]
```

**Root Cause:**
`Parallel` state outputs an **array**. `AggregateResults` tried to use `ResultPath: "$.aggregatedResult"` to merge into the original input — but the original input was now an array, not an object.

**Wrong state definition:**
```json
"AggregateResults": {
  "Parameters": {
    "sessionId.$": "$[0].sessionId"   // BUG: JSONPath into array
  },
  "ResultPath": "$.aggregatedResult"  // BUG: can't write to array root
}
```

**Fix:**
Add a `Pass` state between `Parallel` and `AggregateResults` to reshape the array into an object:

```json
"ReshapeParallelOutput": {
  "Type": "Pass",
  "Parameters": {
    "parallelResults.$": "$",
    "sessionId": "sfn-session"
  },
  "Next": "AggregateResults"
},
"AggregateResults": {
  "Type": "Task",
  "Parameters": {
    "FunctionName": "agenticops-aggregate-results",
    "Payload.$": "$"
  },
  "Next": "WorkflowComplete"
}
```

**Lesson:**
The `Parallel` state ALWAYS outputs an array — one element per branch. Always add a `Pass` state to reshape before the next `Task` state.

---

### Issue 18: Unreachable `WorkflowFailed` State

**Symptom:**
```
The state cannot be reached. It must be referenced by at least one other state.
```

**Root Cause:**
After removing `Catch` blocks that previously routed to `WorkflowFailed`, the state became unreachable.

**Fix:**
Delete the `WorkflowFailed` state entirely from the JSON definition.

**Lesson:**
Step Functions validates at save time that every non-start state is reachable. Remove states that lose all incoming transitions.

---

### Issue 19: EventBridge UI Confusion — Scheduler vs Rules

**Symptom:**
Clicking "Create" in EventBridge opened the Scheduler canvas instead of Rules form.

**Fix:**
Navigate explicitly to **EventBridge → Rules** in the left sidebar or use:
```
https://us-east-1.console.aws.amazon.com/events/home?region=us-east-1#/rules/create
```

| Construct | Use For |
|---|---|
| **Rules** | Event pattern matching → trigger targets (our use case) |
| **Scheduler** | Time-based scheduling (cron/rate) |
| **Pipes** | Point-to-point with filtering/enrichment |

---

## Phase 10 — API Gateway / CORS Issues

---

### Issue 20: API Gateway Sync Timeout — `Failed to fetch`

**Symptom:**
Sync API call hung for 29 seconds then returned `Failed to fetch` in browser.

**Root Cause:**
API Gateway has a hard maximum timeout of 29 seconds. Agent invocations take 45-60 seconds.

**Fix:**
Always use `async: true` for agent queries through API Gateway:

```javascript
// Wrong — will timeout
const response = await fetch(`${API_URL}/invoke`, {
  body: JSON.stringify({task: "...", async: false})
});

// Correct — returns immediately with taskId
const response = await fetch(`${API_URL}/invoke`, {
  body: JSON.stringify({task: "...", async: true})
});
const {taskId} = await response.json();
// Poll /status/{taskId} until completed
```

**Lesson:**
API Gateway's 29-second timeout cannot be increased. Always design with async pattern for LLM-backed endpoints.

---

### Issue 21: CORS `Failed to fetch` from Browser

**Symptom:**
Chat UI showed `Error: Failed to fetch` when calling API Gateway from browser. curl worked fine.

**Root Cause:**
1. Opening `chat-ui.html` via `file://` protocol triggers stricter browser CORS enforcement
2. API Gateway OPTIONS method response was not returning CORS headers

**Diagnosis:**
```bash
curl -X OPTIONS https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev/invoke \
  -H "Origin: http://localhost:8080" \
  -H "Access-Control-Request-Method: POST" \
  -v 2>&1 | grep "access-control"
# If no access-control-* headers → integration response not configured
```

**Fix — Serve via HTTP:**
```bash
cd flows && python3 -m http.server 8080
# Open http://localhost:8080/chat-ui.html
```

**Fix — Configure CORS integration response:**
```bash
aws apigateway put-integration-response \
  --rest-api-id ipm0lawtc7 \
  --resource-id 8wu6r9 \
  --http-method OPTIONS \
  --status-code 200 \
  --response-parameters '{
    "method.response.header.Access-Control-Allow-Headers": "'"'"'Content-Type,Authorization'"'"'",
    "method.response.header.Access-Control-Allow-Methods": "'"'"'POST,GET,OPTIONS'"'"'",
    "method.response.header.Access-Control-Allow-Origin": "'"'"'*'"'"'"
  }' \
  --region us-east-1

aws apigateway create-deployment --rest-api-id ipm0lawtc7 --stage-name dev --region us-east-1
```

**CORS requires 3 configuration layers:**
1. OPTIONS method response (declares which headers are allowed)
2. OPTIONS integration response (sets the actual header values)
3. Lambda response headers (for actual POST/GET responses)

**Lesson:**
Never open HTML files via `file://` for API testing — always serve via `http://localhost`.

---

### Issue 22: Console "Enable CORS" Button Failed

**Symptom:**
```
Failed to update CORS headers on 2 methods
```

**Root Cause:**
OPTIONS methods already existed from a previous attempt. The button tried to create method responses that already existed.

**Fix:**
```bash
aws apigateway update-integration-response \
  --rest-api-id ipm0lawtc7 \
  --resource-id 8wu6r9 \
  --http-method OPTIONS \
  --status-code 200 \
  --patch-operations \
    '[{"op":"replace","path":"/responseParameters/method.response.header.Access-Control-Allow-Origin","value":"'"'"'*'"'"'"}]' \
  --region us-east-1
```

**Lesson:**
Use `update-integration-response` instead of `put-integration-response` when the resource already exists.

---

## Research Agent Phase B — Dockerfile / Docker / ECR Issues

---

### Issue 26: Docker Build Failed — Dependency Version Conflict

**Symptom:**
```
ERROR: Cannot install langgraph 0.2.0 and langchain-core==0.3.0 because
these package versions have conflicting dependencies.
langgraph 0.2.0 depends on langchain-core<0.3 and >=0.2.27
```

**Root Cause:**
Pinned exact versions (`==`) caused a conflict between `langgraph` and `langchain-core`.

**Fix:**
Switch from exact pins to minimum version constraints:

```
# Wrong
langgraph==0.2.0
langchain-core==0.3.0

# Correct
langgraph>=0.2.0
langchain-aws>=0.2.0
langchain-core>=0.2.27
fastapi==0.115.0
uvicorn==0.30.0
tavily-python>=0.5.0
boto3>=1.35.0
```

**Lesson:**
LangChain ecosystem packages have tight inter-dependencies that change frequently. Use `>=` not `==` for LangChain/LangGraph packages. Only pin exact versions for packages with stable APIs (fastapi, uvicorn).

---

### Issue 27: Docker buildx No Network Access — DNS Failure

**Symptom:**
```
WARNING: Retrying (Retry(total=4...)) after connection broken by
'NewConnectionError': Failed to establish a new connection: [Errno -2]
Name or service not known
ERROR: Could not find a version that satisfies the requirement fastapi==0.115.0
```

**Root Cause:**
Colima (Docker runtime on Mac) was stopped and restarted, losing DNS configuration inside the buildx container. buildx uses a separate builder container that doesn't inherit the host network DNS settings.

**Fix:**
```bash
# Restart Colima with explicit DNS
colima stop
colima start --dns 8.8.8.8

# Use regular docker build instead of buildx for Colima compatibility
docker build \
  --platform linux/amd64 \
  --tag 011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:latest \
  --no-cache \
  .
```

**Lesson:**
buildx uses a separate builder container — DNS issues in the host don't automatically fix it. For Colima, restart with `--dns 8.8.8.8` or use regular `docker build --platform` which shares the host network.

---

### Issue 28: ECS Task Permission Denied on Uvicorn Startup

**Symptom:**
```
/usr/local/bin/python3.12: can't open file '/root/.local/bin/uvicorn':
[Errno 13] Permission denied
```

**Root Cause:**
The original multi-stage Dockerfile used `pip install --user` in the builder stage, which installs packages to `/root/.local`. The final image switched to a non-root user `agenticops` (UID 1000) who cannot access `/root/.local` which is owned by root.

**Wrong Dockerfile:**
```dockerfile
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir --user -r requirements.txt  # installs to /root/.local

FROM python:3.12-slim
COPY --from=builder /root/.local /root/.local   # owned by root
USER agenticops                                  # can't access /root/.local
```

**Fix:**
Remove multi-stage build. Install packages system-wide (no `--user` flag):

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # system-wide to /usr/local

COPY app/ ./app/

RUN useradd -m -u 1000 agenticops && chown -R agenticops:agenticops /app
USER agenticops

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
```

**Lesson:**
Multi-stage builds with `--user` pip install break when switching to non-root in the final stage. For non-root containers, always install packages system-wide or explicitly set ownership with `COPY --chown`.

---

### Issue 29: ECR Push Failing — Wrong Repository Name (Shell Variable Stale)

**Symptom:**
```
error from registry: The repository with name 'agenticops-research-agentatest'
does not exist in the registry with id '011528270076'
```

**Root Cause:**
Shell variable `$ECR_URI` had a stale wrong value (`agenticops-research-agentatest`) from an earlier failed attempt. Docker built and tagged the image with the wrong repository name using this variable.

**Diagnosis:**
```bash
echo "Current ECR_URI: '$ECR_URI'"
# Showed: agenticops-research-agentatest (wrong — should be agenticops-research-agent)

docker images | grep agenticops
# Showed the wrong tag was applied to the built image
```

**Fix — Retag existing image without rebuilding:**
```bash
# Retag to correct URI
docker tag \
  011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agentatest:latest \
  011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:latest

# Push with correct tag
docker push 011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:latest
```

**Prevention — Always hardcode ECR URI:**
```bash
# Wrong — relies on shell variable
docker build --tag $ECR_URI:latest .

# Correct — hardcoded URI
docker build \
  --tag 011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:v2 \
  --platform linux/amd64 .
```

**Lesson:**
Never use shell variables for ECR URI in docker build/tag/push commands. Hardcode the full URI. A stale variable is invisible and causes exactly this failure.

---

## Research Agent Phase C — ECS Fargate Issues

---

### Issue 30: ECS Task Definition Baked Wrong Image URI (Revisions 1-3)

**Symptom:**
```
(service agenticops-research-agent) was unable to place a task.
Reason: CannotPullContainerError: pull image manifest has been retried 7 time(s):
failed to resolve ref agenticops-research-agentatest:latest: not found.
```

**Root Cause:**
Task definition revisions 1-3 were registered while `$ECR_URI` had the wrong value, baking `agenticops-research-agentatest` into the container definition. ECS was trying to pull from a repository that didn't exist.

**Diagnosis:**
```bash
# Check what image URI is in the current task definition
aws ecs describe-task-definition \
  --task-definition agenticops-research-agent \
  --region us-east-1 \
  --query "taskDefinition.containerDefinitions[0].image"
# Returned: "agenticops-research-agentatest:latest" -- wrong
```

**Fix:**
Register a new task definition revision with the correct hardcoded URI:

```bash
aws ecs register-task-definition \
  --family agenticops-research-agent \
  --network-mode awsvpc \
  --requires-compatibilities FARGATE \
  --cpu 512 --memory 1024 \
  --execution-role-arn arn:aws:iam::011528270076:role/agenticops-ecs-task-execution-role \
  --task-role-arn arn:aws:iam::011528270076:role/agenticops-ecs-task-role \
  --container-definitions '[{"name":"research-agent","image":"011528270076.dkr.ecr.us-east-1.amazonaws.com/agenticops-research-agent:v2",...}]' \
  --region us-east-1 \
  --query "taskDefinition.{Revision:revision, Image:containerDefinitions[0].image}"

# Update service to new revision
aws ecs update-service \
  --cluster agenticops-cluster \
  --service agenticops-research-agent \
  --task-definition agenticops-research-agent:5 \
  --force-new-deployment \
  --region us-east-1
```

**Lesson:**
Always verify the image URI in the task definition before deploying. Add this check to any deployment script:
```bash
aws ecs describe-task-definition --task-definition agenticops-research-agent \
  --query "taskDefinition.containerDefinitions[0].image"
```

---

### Issue 31: ECS Task Stuck Pending — No Default VPC

**Symptom:**
```bash
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" ...)
VPC: None
# Subnets: (empty)
```

**Root Cause:**
The default VPC had been previously deleted from the account. Without a VPC, ECS tasks cannot be placed.

**Fix:**
```bash
# Recreate the default VPC
aws ec2 create-default-vpc --region us-east-1

# Wait for subnets to be created
sleep 10

VPC_ID="vpc-054fbd3d56cb3761a"
SUBNET_IDS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[0:2].SubnetId" \
  --output text --region us-east-1 | tr '\t' ',')

echo "VPC: $VPC_ID"
echo "Subnets: $SUBNET_IDS"

aws ssm put-parameter --name "/agenticops/vpc/id" --value "$VPC_ID" --type String --region us-east-1 --overwrite
aws ssm put-parameter --name "/agenticops/vpc/subnet-ids" --value "$SUBNET_IDS" --type String --region us-east-1 --overwrite
```

**Lesson:**
`aws ec2 describe-vpcs` returning `None` for the default VPC means it was deleted. This is common in accounts that have had cleanup scripts run. `create-default-vpc` recreates it with the standard `172.31.0.0/16` CIDR and auto-creates subnets in each AZ.

---

### Issue 32: ECS Service Stuck — `CannotPullContainerError` Due to ECS Service Linked Role

**Symptom:**
```
An error occurred (InvalidParameterException) when calling the CreateCluster
operation: Unable to assume the service linked role. Please verify that the
ECS service linked role exists.
```

**Root Cause:**
The ECS service-linked role `AWSServiceRoleForECS` appeared to be missing. However, it actually existed — the error was misleading.

**Fix:**
Skip the `--capacity-providers` flag when creating the cluster:

```bash
# Wrong — triggers service linked role check
aws ecs create-cluster \
  --cluster-name agenticops-cluster \
  --capacity-providers FARGATE \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1

# Correct — Fargate support is built-in without explicit capacity providers
aws ecs create-cluster \
  --cluster-name agenticops-cluster \
  --region us-east-1
```

If the role genuinely doesn't exist:
```bash
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com
```

**Lesson:**
ECS clusters support Fargate by default without specifying `--capacity-providers`. The explicit capacity provider flag triggers additional validation that can fail even when the cluster would work fine without it.

---

## Research Agent Phase D — Bedrock Wiring Issues

---

### Issue 33: Supervisor Agent Cannot Have Action Groups

**Symptom:**
```
ValidationException: Failed to create OpenAPI 3 model from the JSON/YAML object
that you provided for action: web-research
```
(Same error for every schema variation tried — minimal schema, GET vs POST, no requestBody, etc.)

**Root Cause:**
`SUPERVISOR` mode agents in Bedrock cannot have Action Groups. This is a fundamental architectural constraint — Supervisor agents can only delegate to collaborators, they cannot call tools directly. The `ValidationException` error message was misleading and did not indicate the real cause.

**How We Discovered This:**
- Same schema (`get-alarms-schema.json`) that worked on IT Ops agent failed on Supervisor
- Tried 8+ different schema variations — all failed with identical error
- Confirmed by checking: Supervisor had `SUPERVISOR` collaboration mode set

**Fix:**
Create a dedicated **Research Bedrock Agent** (separate from Supervisor) and attach the action group to it. Register it as a collaborator on the Supervisor.

```bash
# Create dedicated Research Bedrock Agent
RESEARCH_AGENT_ID=$(aws bedrock-agent create-agent \
  --agent-name "agenticops-research-agent-bedrock" \
  --agent-resource-role-arn "arn:aws:iam::011528270076:role/agenticops-bedrock-agent-role" \
  --foundation-model "us.anthropic.claude-sonnet-4-6" \
  --instruction "You are the AgenticOps Research Agent. Your job is to find current information from the web about AWS services, Bedrock features, and operational topics. Use the web-research action to search for information. Always cite your sources. Be concise and focus on actionable information." \
  --region us-east-1 \
  --query "agent.agentId" --output text)

# Add Lambda permission for this new agent
aws lambda add-permission \
  --function-name agenticops-research-agent-action \
  --statement-id bedrock-research-agent-invoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn "arn:aws:bedrock:us-east-1:011528270076:agent/$RESEARCH_AGENT_ID" \
  --region us-east-1

# Create action group on Research Agent (not Supervisor)
aws bedrock-agent create-agent-action-group \
  --agent-id "$RESEARCH_AGENT_ID" \
  --agent-version "DRAFT" \
  --action-group-name "web-research" \
  --description "Research a topic on the web" \
  --action-group-executor '{"lambda": "arn:aws:lambda:us-east-1:011528270076:function:agenticops-research-agent-action"}' \
  --api-schema '{"s3": {"s3BucketName": "agenticops-artifacts", "s3ObjectKey": "schemas/research-agent/schema.json"}}' \
  --region us-east-1
```

**Lesson:**
SUPERVISOR mode agents = routing only, no Action Groups. Specialist agents = Action Groups only. This is a fundamental Bedrock design constraint.

---

### Issue 34: OpenAPI Schema Validation Failure — IAM ImplicitDeny on S3

**Symptom:**
```
ValidationException: Failed to create OpenAPI 3 model from the JSON/YAML object
that you provided for action: web-research
```
(Same error even with valid schema, on the Research Agent — not Supervisor)

**Root Cause:**
`agenticops-bedrock-agent-role` had `implicitDeny` on `s3:GetObject` for `agenticops-artifacts` bucket. The production hardening phase scoped S3 access to `agenticops-knowledge-base-docs` only. When Bedrock tried to read the schema file from S3 to validate it, the read failed silently.

**Diagnosis:**
```bash
# This is the key diagnostic step
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::011528270076:role/agenticops-bedrock-agent-role \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::agenticops-artifacts/schemas/research-agent/schema.json \
  --query "EvaluationResults[0].EvalDecision"
# Returned: "implicitDeny"  <-- this was the actual issue all along
```

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-bedrock-agent-role \
  --policy-name agenticops-agent-s3-artifacts \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::agenticops-artifacts",
        "arn:aws:s3:::agenticops-artifacts/*"
      ]
    }]
  }'
```

**Lesson:**
Always run `aws iam simulate-principal-policy` before assuming a schema or config problem. IAM scoping in production hardening can silently break downstream functionality with misleading error messages.

---

### Issue 35: AssociateAgentCollaborator — Missing `bedrock:GetAgentAlias`

**Symptom:**
```
ValidationException: You do not have sufficient permissions to collaborate with
this agent alias, or the agent alias does not exist.
```
(Persisted even after waiting for IAM propagation and verifying both agent and alias were PREPARED)

**Root Cause:**
`agenticops-bedrock-agent-role` had `bedrock:InvokeAgent` but was missing `bedrock:GetAgentAlias`. Bedrock performs a pre-flight check using `GetAgentAlias` to validate the alias exists and is accessible before registering the collaborator. Both permissions are required.

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-bedrock-agent-role \
  --policy-name agenticops-research-agent-invoke \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeAgent",
        "bedrock:GetAgentAlias"
      ],
      "Resource": "arn:aws:bedrock:us-east-1:011528270076:agent-alias/QB1F9WH47O/*"
    }]
  }'

sleep 10  # wait for IAM propagation

aws bedrock-agent associate-agent-collaborator \
  --agent-id "45BDFFSGGZ" \
  --agent-version "DRAFT" \
  --agent-descriptor '{"aliasArn": "arn:aws:bedrock:us-east-1:011528270076:agent-alias/QB1F9WH47O/RJ4NBYODD7"}' \
  --collaborator-name "ResearchAgent" \
  --collaboration-instruction "Route to this agent for any query requiring current web information, recent AWS announcements, latest Bedrock features, external documentation, or anything not available in internal runbooks and SOPs." \
  --relay-conversation-history "TO_COLLABORATOR" \
  --region us-east-1
```

**Lesson:**
Bedrock collaborator association requires BOTH `bedrock:InvokeAgent` AND `bedrock:GetAgentAlias`. The error message "does not exist" is misleading — the alias existed, the permission was missing.

---

### Issue 36: accessDeniedException on InvokeAgent — Inference Profile ARN Not in Policy

**Symptom:**
```
botocore.exceptions.EventStreamError: An error occurred (accessDeniedException)
when calling the InvokeAgent operation: Access denied when calling Bedrock.
Check your request permissions and retry the request.
```
(User had `AmazonBedrockFullAccess`. Error was on the AGENT role, not user role.)

**Root Cause:**
`agenticops-bedrock-agent-scoped` policy only allowed `bedrock:InvokeModel` on `arn:aws:bedrock:us-east-1::foundation-model/*`. The Research Agent uses `us.anthropic.claude-sonnet-4-6` which is a cross-region inference profile — its ARN pattern is `inference-profile/*`, not `foundation-model/*`. Additionally `bedrock:GetInferenceProfile` was missing, which is required for cross-region profile invocation.

**Diagnosis:**
```bash
aws iam get-role-policy \
  --role-name agenticops-bedrock-agent-role \
  --policy-name agenticops-bedrock-agent-scoped \
  --query "PolicyDocument.Statement[?Sid=='BedrockModelInvoke'].Resource"
# Showed only: "arn:aws:bedrock:us-east-1::foundation-model/*"
# Missing: inference-profile/* ARNs
```

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-bedrock-agent-role \
  --policy-name agenticops-bedrock-agent-scoped \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "BedrockModelInvoke",
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        "Resource": [
          "arn:aws:bedrock:us-east-1::foundation-model/*",
          "arn:aws:bedrock:us-east-1:011528270076:inference-profile/*",
          "arn:aws:bedrock:*::foundation-model/*"
        ]
      },
      {
        "Sid": "BedrockInferenceProfile",
        "Effect": "Allow",
        "Action": ["bedrock:GetInferenceProfile", "bedrock:ListInferenceProfiles"],
        "Resource": "*"
      }
    ]
  }'
```

**Lesson:**
`foundation-model/*` and `inference-profile/*` are different resource types in IAM. Cross-region inference profiles (`us.*` prefix) require BOTH ARN patterns. `bedrock:GetInferenceProfile` is also required but not prominently documented. Use IAM policy simulator after any scoping change.

---

### Issue 37: Supervisor Alias Pointing to Old Version — Research Agent Not Invoked

**Symptom:**
Research queries returned "Sorry, the model cannot answer this question." No Lambda logs for `agenticops-research-agent-action` existed (Lambda never invoked).

**Root Cause:**
Supervisor alias `U4A49NOUEK` was routing to version `1` — created before the Research Agent collaborator was added. The DRAFT version had the Research Agent registered, but the alias pointed to the immutable version 1 snapshot which cannot include new collaborators.

**Diagnosis:**
```bash
aws bedrock-agent get-agent-alias \
  --agent-id "45BDFFSGGZ" --agent-alias-id "U4A49NOUEK" \
  --region us-east-1 \
  --query "agentAlias.routingConfiguration"
# Returned: [{"agentVersion": "1"}]  <-- version 1 has no Research Agent
```

**Fix:**
Create version 2 from current DRAFT via console (boto3/CLI `create_agent_version` not available in this CLI version):

```
Bedrock Console
→ Agents → agenticops-supervisor
→ Aliases → dev → Edit
→ Select "Create a new version and associate it to this alias"
→ Save
```

Verify via CLI:
```bash
aws bedrock-agent get-agent-alias \
  --agent-id "45BDFFSGGZ" --agent-alias-id "U4A49NOUEK" \
  --region us-east-1 \
  --query "agentAlias.routingConfiguration"
# Should now show: [{"agentVersion": "2"}]
```

**Lesson:**
After adding a collaborator to a Supervisor, always create a new agent version and update the alias routing. Agent versions are immutable snapshots — the old version cannot retroactively include new collaborators. When an agent alias points to an old version, new capabilities are completely invisible to callers.

---

## General AWS CLI Issues

---

### Issue 23: Zsh Multi-line Command Pasting Breaks

**Symptom:**
```
zsh: command not found: #
zsh: command not found: --name
aws: [ERROR]: the following arguments are required: --name, --value
```

**Root Cause:**
Pasting multi-line commands with inline comments (`#`) or line continuations (`\`) into zsh. Zsh treats each line as a separate command when pasted from clipboard.

**Fix — Run as single line:**
```bash
aws ssm put-parameter --name "/agenticops/bedrock/kb-id" --value "NLHMUXZM4R" --type String --region us-east-1
```

**Fix — Save to script file:**
```bash
cat > /tmp/cmd.sh << 'EOF'
aws ssm put-parameter \
  --name "/agenticops/bedrock/kb-id" \
  --value "NLHMUXZM4R" \
  --type String \
  --region us-east-1
EOF
bash /tmp/cmd.sh
```

---

### Issue 24: Wrong Working Directory for Git Commands

**Symptom:**
```
fatal: not a git repository (or any of the parent directories): .git
```

**Fix:**
```bash
git rev-parse --show-toplevel   # verify repo root
cd ~/Documents/MyProjects/AWS-AgenticOps-Project
git status
```

---

### Issue 25: Placeholder Values in CLI Commands

**Symptom:**
```
ValidationException: Value '<DS_ID>' at 'dataSourceId' failed to satisfy
constraint: Member must satisfy regular expression pattern: [0-9a-zA-Z]{10}
```

**Fix:**
```bash
# Verify variable is set before using
echo $DS_ID   # must show actual ID, not empty

# Or hardcode the real value
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "NLHMUXZM4R" \
  --data-source-id "B3QL9TOORM" \
  --region us-east-1
```

---

## Quick Diagnostic Commands

### Check All Agent Statuses

```bash
aws bedrock-agent list-agents --region us-east-1 \
  --query "agentSummaries[].{Name:agentName, ID:agentId, Status:agentStatus}" \
  --output table
```

### Check Supervisor Alias Version

```bash
aws bedrock-agent get-agent-alias \
  --agent-id "45BDFFSGGZ" --agent-alias-id "U4A49NOUEK" \
  --region us-east-1 --query "agentAlias.routingConfiguration"
```

### Check Supervisor Collaborators

```bash
aws bedrock-agent list-agent-collaborators \
  --agent-id "45BDFFSGGZ" --agent-version "DRAFT" \
  --region us-east-1 \
  --query "agentCollaboratorSummaries[].{Name:collaboratorName, ID:collaboratorId}"
```

### Check Lambda Never Invoked

```bash
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/agenticops" \
  --region us-east-1 \
  --query "logGroups[].logGroupName" --output table
# If agenticops-research-agent-action missing -> Lambda never invoked -> issue is upstream
```

### Check ECS Service Health

```bash
aws ecs describe-services --cluster agenticops-cluster \
  --services agenticops-research-agent --region us-east-1 \
  --query "services[0].{Running:runningCount, Pending:pendingCount, Event:events[0].message}"
```

### Check ECS Logs

```bash
aws logs tail /ecs/agenticops-research-agent --since 10m --region us-east-1
```

### Check IAM Permission Before Testing

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::011528270076:role/agenticops-bedrock-agent-role \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::agenticops-artifacts/schemas/research-agent/schema.json \
  --query "EvaluationResults[0].EvalDecision"
```

### Check Lambda Errors

```bash
aws logs tail /aws/lambda/agenticops-async-consumer --since 10m --region us-east-1
```

### Check All DLQ Depths

```bash
for queue in agenticops-async-tasks-dlq agenticops-lambda-dlq; do
  COUNT=$(aws sqs get-queue-attributes \
    --queue-url https://sqs.us-east-1.amazonaws.com/011528270076/$queue \
    --attribute-names ApproximateNumberOfMessagesVisible \
    --region us-east-1 \
    --query "Attributes.ApproximateNumberOfMessagesVisible" --output text)
  echo "$queue: $COUNT messages"
done
```

### Check Step Functions Execution

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow \
  --region us-east-1 \
  --query "executions[0:5].{Name:name, Status:status, Start:startDate}" --output table
```

### Test API Gateway CORS

```bash
curl -X OPTIONS https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev/invoke \
  -H "Origin: http://localhost:8080" -H "Access-Control-Request-Method: POST" \
  -v 2>&1 | grep "access-control"
# Should show: access-control-allow-origin: *
```

### Verify All SSM Parameters

```bash
aws ssm get-parameters-by-path --path "/agenticops" --recursive \
  --region us-east-1 --query "Parameters[].{Name:Name, Value:Value}" --output table
```

### Check CloudTrail for Failed API Calls

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateAgentActionGroup \
  --region us-east-1 \
  --query 'Events[0].CloudTrailEvent' \
  --output text | python3 -m json.tool | grep -A3 '"errorCode"'
```

---

## Issue Frequency Summary

| Category | Issues | Most Common Root Cause |
|---|---|---|
| IAM Permissions | 8 | Missing cross-service perms, inference-profile ARN, GetAgentAlias |
| Bedrock / S3 Vectors | 3 | New service integration bugs, format mismatches |
| Step Functions | 4 | JSONPath with Parallel state output, unreachable states |
| API Gateway / CORS | 3 | 29s timeout, CORS 3-layer config, file:// vs http:// |
| ECS / Docker / ECR | 5 | Shell variable typos, buildx DNS, uvicorn permissions, missing VPC |
| Bedrock Multi-Agent | 5 | Supervisor cannot have action groups, alias version, collaborator perms |
| DynamoDB | 1 | Reserved keyword `result` |
| CLI / Shell | 3 | Zsh pasting, wrong directory, placeholder values |
| Knowledge Base | 4 | Metadata format, S3 delete flags, ingestion failures |

**Top 5 lessons from this entire build:**
1. **Use IAM policy simulator first** — `simulate-principal-policy` would have caught Issues 34, 35, 36 immediately
2. **SUPERVISOR agents cannot have Action Groups** — Bedrock's most confusing architectural constraint
3. **Hardcode ECR URIs** — shell variables for container image references cause silent failures
4. **foundation-model/* does NOT cover inference-profile/*** — add both when scoping Bedrock IAM
5. **Always check CloudTrail** when AWS resource creation fails silently — the console masks real errors

---

*Last Updated: May 2026 | AgenticOps Platform v1.0 | 37 issues documented*