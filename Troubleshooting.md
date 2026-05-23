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
- [Phase 8 — Guardrails Issues](#phase-8--guardrails-issues)
- [Phase 10 — API Gateway / CORS Issues](#phase-10--api-gateway--cors-issues)
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
# Delete S3 vector index and bucket
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

CloudTrail showed `ValidationException` with the message:
```
User: agenticops-kb-role is not authorized to perform: s3vectors:QueryVectors
```

**Fix:**
```bash
# Add OpenSearch managed policies
aws iam attach-role-policy \
  --role-name agenticops-kb-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonOpenSearchServiceFullAccess

aws iam attach-role-policy \
  --role-name agenticops-kb-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonOpenSearchIngestionFullAccess

# Add inline AOSS data plane policy
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
# Regenerate metadata
bash /tmp/fix-metadata.sh

# Re-upload metadata files only
aws s3 cp knowledge-base/ s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --exclude "*" \
  --include "*.metadata.json" \
  --region us-east-1
```

**Lesson:**
Bedrock KB metadata format is flat key-value — not DynamoDB's typed format, not JSON Schema, not any other structured format. Always test with one document before bulk uploading.

---

### Issue 5: S3 Bucket Accidentally Emptied

**Symptom:**
After running `aws s3 rm` to remove metadata files, all 9 `.md` documents were also deleted.

**Root Cause:**
`aws s3 rm --include "*.metadata.json"` without `--exclude "*"` first defaults to deleting ALL files then including only metadata — the flag order matters.

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
Re-uploaded all documents:
```bash
aws s3 cp knowledge-base/ s3://agenticops-knowledge-base-docs/ \
  --recursive \
  --exclude "*" \
  --include "*.md" \
  --region us-east-1
```

**Lesson:**
`aws s3 rm/cp` flag order is critical. `--exclude` must always come before `--include`. Always do a dry-run check with `aws s3 ls` before destructive S3 operations. Versioning was enabled on the KB bucket — in future, use `aws s3api list-object-versions` to recover accidentally deleted objects.

---

### Issue 6: Ingestion Complete but 0 Documents Indexed

**Symptom:**
```json
{"Status": "COMPLETE", "Scanned": 0, "Indexed": 0, "Failed": 0}
```

**Root Cause:**
The S3 bucket was empty when the ingestion ran (from Issue 5 above). The job completed successfully but found nothing to index.

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
Use inference profile ID instead of foundation model ID:

```bash
# Wrong
"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5..."

# Correct
"modelArn": "arn:aws:bedrock:us-east-1:011528270076:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

List available inference profiles:
```bash
aws bedrock list-inference-profiles \
  --region us-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude-sonnet')].{ID:inferenceProfileId, Name:inferenceProfileName}"
```

**Lesson:**
AWS Bedrock inference profiles (`us.*` prefix) route across multiple US regions for higher availability and throughput. Always use the versioned inference profile ARN in production — never the short alias or foundation model ID directly.

---

## Phase 3 — IT Ops Agent Issues

---

### Issue 8: Action Group Creation — "Must specify roleArn and roleSessionName"

**Symptom:**
```
ValidationException: You must specify a value for roleArn and roleSessionName
```

**Root Cause:**
Two sub-issues:
1. The `agenticops-bedrock-agent-role` trust policy only had `bedrock.amazonaws.com` — missing the agents service principal
2. The role hadn't been saved/associated with the agent before creating action groups

**Fix:**

First, save the agent with explicit role ARN:
```bash
aws bedrock-agent update-agent \
  --agent-id "UQINWRUDBC" \
  --agent-name "agenticops-itops-agent" \
  --agent-resource-role-arn "arn:aws:iam::011528270076:role/agenticops-bedrock-agent-role" \
  --foundation-model "us.anthropic.claude-sonnet-4-6" \
  --instruction "..." \
  --region us-east-1
```

Then add Lambda invoke permission to agent role:
```bash
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
```

Then add Lambda resource-based policy:
```bash
aws lambda add-permission \
  --function-name agenticops-itops-get-alarms \
  --statement-id bedrock-agent-invoke \
  --action lambda:InvokeFunction \
  --principal bedrock.amazonaws.com \
  --source-arn "arn:aws:bedrock:us-east-1:011528270076:agent/UQINWRUDBC" \
  --region us-east-1
```

**Lesson:**
Bedrock Agents need permissions at two levels:
- **Identity-based policy** on the agent role → `lambda:InvokeFunction`
- **Resource-based policy** on the Lambda → allows `bedrock.amazonaws.com` principal

Both are required. Missing either one causes the cryptic "roleArn and roleSessionName" error.

---

### Issue 9: Console Error — "Must save agent with Agent Resource Role before adding Action Group from S3"

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
`agenticops-lambda-execution-role` was created with broad managed policies (`AmazonSQSFullAccess`, `AmazonDynamoDBFullAccess`) but did NOT include Step Functions, Glue, EC2, RDS, or SSM permissions needed by the action group Lambdas.

**Fix:**
```bash
aws iam put-role-policy \
  --role-name agenticops-lambda-execution-role \
  --policy-name agenticops-lambda-pipeline-permissions \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "states:ListStateMachines",
          "states:ListExecutions",
          "states:StartExecution",
          "states:DescribeExecution",
          "states:DescribeStateMachine",
          "glue:GetJobs",
          "glue:GetJobRuns",
          "glue:StartJobRun",
          "glue:GetJobRun",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:GetMetricStatistics",
          "ec2:DescribeInstances",
          "rds:DescribeDBInstances",
          "ssm:SendCommand",
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:SetDesiredCapacity"
        ],
        "Resource": "*"
      }
    ]
  }'
```

**Lesson:**
`AWSLambdaBasicExecutionRole` only grants CloudWatch Logs access. Every AWS API your Lambda calls needs explicit IAM permission. Always test Lambda functions individually before wiring them to agents to catch permission issues early.

---

### Issue 11: Pipeline Lambda — Read Timeout from Empty Step Functions Account

**Symptom:**
```
urllib3.exceptions.ReadTimeoutError: AWSHTTPSConnectionPool: Read timed out.
```

**Root Cause:**
The `agenticops-pipeline-list` Lambda called `list_state_machines()` which returned no results (no Step Functions in the account). The Bedrock agent ReAct loop stalled waiting for meaningful data, eventually causing the boto3 client to timeout.

**Fix:**
Added try/except with graceful empty response so the Lambda always returns quickly:

```python
if pipeline_type in ["all", "stepfunctions"]:
    try:
        response = sfn.list_state_machines(maxResults=20)
        for sm in response["stateMachines"]:
            pipelines.append({...})
    except Exception as e:
        pipelines.append({"type": "stepfunctions", "error": str(e)})

# Always return something even if empty
return {
    "messageVersion": "1.0",
    "response": {
        ...
        "body": json.dumps({
            "pipelineCount": len(pipelines),
            "pipelines": pipelines,
            "note": "No pipelines found" if not pipelines else ""
        })
    }
}
```

Also added longer timeout to boto3 client:
```python
from botocore.config import Config
config = Config(read_timeout=120, connect_timeout=10)
client = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=config)
```

**Lesson:**
Action Group Lambdas must always return a response quickly — even if the result is empty. The Bedrock agent cannot proceed until the Lambda responds. Design Lambdas to handle empty/no-resource scenarios gracefully with an informative message rather than hanging.

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
Set both specialist agents to `SUPERVISOR_ROUTER` collaboration mode — but this mode is for agents that ARE supervisors, not for agents that ARE being supervised.

**Fix:**
Specialist agents should remain `DISABLED`. Only the Supervisor gets `SUPERVISOR` mode.

```bash
# Revert specialist agents to DISABLED
aws bedrock-agent update-agent \
  --agent-id "UQINWRUDBC" \
  --agent-collaboration "DISABLED" \
  ... other params ...

# Supervisor gets SUPERVISOR mode
aws bedrock-agent update-agent \
  --agent-id "45BDFFSGGZ" \
  --agent-collaboration "SUPERVISOR" \
  ... other params ...
```

**Collaboration modes explained:**
| Mode | Used By | Meaning |
|---|---|---|
| `DISABLED` | Specialist agents | Can be called as collaborator but cannot delegate further |
| `SUPERVISOR` | Supervisor agent | Can delegate to registered collaborators |
| `SUPERVISOR_ROUTER` | Not used in this project | Supervisor that only routes, does no work itself |

---

### Issue 13: Invalid Service Principal `bedrock-agent.amazonaws.com`

**Symptom:**
```
MalformedPolicyDocument: Invalid principal in policy: "SERVICE":"bedrock-agent.amazonaws.com"
```

**Root Cause:**
Attempted to add `bedrock-agent.amazonaws.com` as a separate trust policy statement — this service principal does not exist.

**Fix:**
The correct trust policy uses only `bedrock.amazonaws.com` which covers all Bedrock services including agents:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": "bedrock.amazonaws.com"
    },
    "Action": "sts:AssumeRole"
  }]
}
```

**Lesson:**
`bedrock.amazonaws.com` is the single service principal for all Bedrock services. There is no separate `bedrock-agent.amazonaws.com` principal.

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
`result` is one of 570+ DynamoDB reserved keywords. Using it directly in `UpdateExpression` causes a parse error.

**Fix:**
Use `ExpressionAttributeNames` to alias reserved keywords:

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
    ExpressionAttributeNames={
        "#s": "status",
        "#r": "result"    # alias for reserved word
    },
    ExpressionAttributeValues={
        ":s": "completed",
        ":r": agent_result
    }
)
```

**Common reserved DynamoDB keywords to watch out for:**
`name`, `status`, `result`, `value`, `data`, `type`, `key`, `size`, `count`, `date`, `time`, `index`, `range`, `table`

**Lesson:**
Always use `ExpressionAttributeNames` for any attribute that might be a reserved word. Better practice: prefix all attribute names with your app name (`ag_result`, `ag_status`) to avoid conflicts entirely.

---

### Issue 15: Async Task Showing `not_found` Immediately

**Symptom:**
Task submitted successfully (got `taskId`) but status poll returned `{"status": "not_found"}` even after 30 seconds.

**Root Cause:**
The polling script started checking before the consumer Lambda had written the initial `queued` status to DynamoDB. The timing between SQS delivery and DynamoDB write was slower than expected.

**Fix:**
Wait at least 5 seconds before first poll, and use a polling interval of 5 seconds minimum:

```python
time.sleep(5)  # wait for initial write

for i in range(36):  # poll up to 3 minutes
    item = table.get_item(Key={"taskId": task_id}).get("Item", {})
    status = item.get("status", "not_found")
    if status in ["completed", "failed"]:
        break
    time.sleep(5)
```

**Also check:** The `api-handler` Lambda writes `queued` status to DynamoDB before returning. If DynamoDB write fails silently, the task appears in SQS but not in DynamoDB. Add logging to confirm.

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
`AWSStepFunctionsFullAccess` managed policy grants Step Functions management plane permissions but NOT the ability to invoke Lambda functions. These are separate IAM actions.

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
`AWSStepFunctionsFullAccess` only manages Step Functions resources — it does not grant cross-service permissions. Each service integration (Lambda, DynamoDB, SNS, etc.) needs its own IAM permission on the Step Functions execution role.

---

### Issue 17: `States.ReferencePathConflict` After Parallel State

**Symptom:**
```
ExecutionFailed: States.ReferencePathConflict: Unable to apply step
"aggregatedResult" to input [array output from Parallel state]
```

**Root Cause:**
The `Parallel` state outputs an **array** (one element per branch). The `AggregateResults` state tried to use `ResultPath: "$.aggregatedResult"` to merge into the original input — but the original input was now an array, not an object. You cannot add a key to an array.

**Wrong state definition:**
```json
"AggregateResults": {
  "Type": "Task",
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
    "parallelResults.$": "$",     // capture the array as a named field
    "sessionId": "sfn-session"    // add static session ID
  },
  "Next": "AggregateResults"
},
"AggregateResults": {
  "Type": "Task",
  "Parameters": {
    "FunctionName": "agenticops-aggregate-results",
    "Payload.$": "$"              // now $ is an object, not an array
  },
  "Next": "WorkflowComplete"
}
```

**Lesson:**
The `Parallel` state always outputs an **array** — one element per branch, in branch order. If you need to use the results downstream as named fields, always add a `Pass` state with `Parameters` to reshape the output before the next `Task` state.

---

### Issue 18: Unreachable `WorkflowFailed` State

**Symptom:**
Console showed red underline on `WorkflowFailed` state with error:
```
The state cannot be reached. It must be referenced by at least one other state.
```

**Root Cause:**
After removing `Catch` blocks that previously routed to `WorkflowFailed`, the state became unreachable.

**Fix:**
Delete the `WorkflowFailed` state entirely from the JSON definition since no state transitioned to it.

**Lesson:**
Step Functions validates at save time that every non-start state is reachable. When refactoring state machines, remove states that lose all incoming transitions.

---

### Issue 19: EventBridge UI Confusion — Scheduler vs Rules

**Symptom:**
Navigating to EventBridge and clicking "Create" opened the EventBridge Scheduler (drag-and-drop canvas) instead of the Rules creation form.

**Root Cause:**
AWS EventBridge now has three separate constructs — Event Buses, Rules, and Pipes/Scheduler — each with its own creation flow. The default landing page changed.

**Fix:**
Navigate explicitly to **EventBridge → Rules** in the left sidebar, then click **Create rule**. Or use direct URL:
```
https://us-east-1.console.aws.amazon.com/events/home?region=us-east-1#/rules/create
```

**When to use which:**
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
Sync API call (`async: false`) hung for 29 seconds then returned `Failed to fetch` in browser.

**Root Cause:**
API Gateway has a hard maximum timeout of 29 seconds. Agent invocations typically take 45-60 seconds. The request timed out before the agent responded.

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
API Gateway's 29-second timeout cannot be increased. For any LLM-backed endpoint, always use the async pattern: submit → get taskId → poll for result.

---

### Issue 21: CORS `Failed to fetch` from Browser

**Symptom:**
Chat UI showed `Error: Failed to fetch` when calling API Gateway from browser. curl worked fine.

**Root Cause:**
Two compounding issues:
1. Opening `chat-ui.html` via `file://` protocol triggers stricter browser CORS enforcement
2. API Gateway OPTIONS method response was not returning CORS headers

**Diagnosis:**
```bash
# Check if CORS headers are present in OPTIONS response
curl -X OPTIONS https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev/invoke \
  -H "Origin: http://localhost:8080" \
  -H "Access-Control-Request-Method: POST" \
  -v 2>&1 | grep "access-control"
```

If no `access-control-*` headers in response → integration response not configured.

**Fix — Serve via HTTP instead of file://**
```bash
cd flows
python3 -m http.server 8080
# Open http://localhost:8080/chat-ui.html
```

**Fix — Configure CORS integration response via CLI**
```bash
# Add integration response with CORS headers
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

# Redeploy
aws apigateway create-deployment \
  --rest-api-id ipm0lawtc7 \
  --stage-name dev \
  --region us-east-1
```

**CORS requires 3 configuration layers in API Gateway:**
1. OPTIONS method response (declares which headers are allowed)
2. OPTIONS integration response (sets the actual header values)
3. Lambda response headers (for actual POST/GET responses)

**Lesson:**
Never open HTML files via `file://` for API testing — always serve via `http://localhost`. CORS is a browser security feature and only applies to browser-originated requests (not curl, Python, Postman).

---

### Issue 22: Console "Enable CORS" Button Failed

**Symptom:**
```
Failed to update CORS headers on 2 methods
```

**Root Cause:**
The console's "Enable CORS" button failed because OPTIONS methods already existed from a previous attempt. The button tries to create method responses that already existed, causing a conflict.

**Fix:**
Use CLI to update the existing integration response directly:

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
When the API Gateway console fails for CORS configuration, use the CLI. The console "Enable CORS" button is a convenience wrapper that fails gracefully when resources already exist. Use `update-integration-response` instead of `put-integration-response` when the resource already exists.

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
Pasting multi-line commands with inline comments (`#`) or line continuations (`\`) into zsh terminal. Zsh treats each line as a separate command when pasted.

**Fix:**
Run commands as single lines without comments:

```bash
# Wrong — paste as multi-line with comments
aws ssm put-parameter \
  --name "/agenticops/bedrock/kb-id" \   # this breaks zsh
  --value "2DPJKUACLU" \
  --type String \
  --region us-east-1

# Correct — single line, no comments
aws ssm put-parameter --name "/agenticops/bedrock/kb-id" --value "2DPJKUACLU" --type String --region us-east-1
```

Or save to a shell script file and execute:
```bash
cat > /tmp/cmd.sh << 'EOF'
aws ssm put-parameter \
  --name "/agenticops/bedrock/kb-id" \
  --value "2DPJKUACLU" \
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

**Root Cause:**
Running git commands from a different directory (`aws-llmops-project`) instead of the correct repo (`AWS-AgenticOps-Project`).

**Fix:**
```bash
# Always verify before committing
git rev-parse --show-toplevel   # shows repo root
pwd                              # shows current directory

# Navigate to correct repo
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

**Root Cause:**
Literally pasting `<DS_ID>` or `<YOUR_KB_ID>` placeholder text into CLI commands instead of replacing with actual values.

**Fix:**
Always replace angle-bracket placeholders before running:

```bash
# Before running, confirm variable is set
echo $DS_ID   # should show actual ID, not empty

# Or hardcode the real value
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "NLHMUXZM4R" \      # real ID
  --data-source-id "B3QL9TOORM" \          # real ID
  --region us-east-1
```

---

## Quick Diagnostic Commands

Use these when something breaks and you need to quickly find the issue.

### Check Agent Status

```bash
aws bedrock-agent list-agents --region us-east-1 \
  --query "agentSummaries[].{Name:agentName, ID:agentId, Status:agentStatus}" \
  --output table
```

### Check KB Ingestion Status

```bash
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id NLHMUXZM4R \
  --data-source-id B3QL9TOORM \
  --region us-east-1 \
  --query "ingestionJobSummaries[].{ID:ingestionJobId, Status:status, Started:startedAt}" \
  --output table
```

### Check Lambda Errors (last 10 minutes)

```bash
aws logs tail /aws/lambda/agenticops-async-consumer --since 10m --region us-east-1
```

### Check SQS Queue Depth

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks \
  --attribute-names ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible \
  --region us-east-1
```

### Check DLQ Depth

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/011528270076/agenticops-async-tasks-dlq \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --region us-east-1
```

### Check Step Functions Execution

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:011528270076:stateMachine:agenticops-workflow \
  --region us-east-1 \
  --query "executions[0:5].{Name:name, Status:status, Start:startDate}" \
  --output table
```

### Check IAM Permissions (simulate)

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::011528270076:role/agenticops-lambda-execution-role \
  --action-names states:ListStateMachines \
  --resource-arns "*"
```

### Check CloudTrail for Failed API Calls

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateKnowledgeBase \
  --region us-east-1 \
  --query 'Events[0].CloudTrailEvent' \
  --output text | python3 -m json.tool | grep -A3 '"errorCode"'
```

### Test API Gateway CORS Preflight

```bash
curl -X OPTIONS https://ipm0lawtc7.execute-api.us-east-1.amazonaws.com/dev/invoke \
  -H "Origin: http://localhost:8080" \
  -H "Access-Control-Request-Method: POST" \
  -v 2>&1 | grep "access-control"
```

### Verify All SSM Parameters

```bash
aws ssm get-parameters-by-path \
  --path "/agenticops" \
  --recursive \
  --region us-east-1 \
  --query "Parameters[].{Name:Name, Value:Value}" \
  --output table
```

---

## Issue Frequency Summary

| Category | Issues | Most Common Root Cause |
|---|---|---|
| IAM Permissions | 5 | Missing cross-service permissions not covered by managed policies |
| Bedrock / S3 Vectors | 3 | New service integration bugs, format mismatches |
| Step Functions | 4 | JSONPath with Parallel state output, unreachable states |
| API Gateway / CORS | 3 | 29s timeout, CORS 3-layer config, file:// vs http:// |
| DynamoDB | 1 | Reserved keyword `result` |
| CLI / Shell | 3 | Zsh pasting, wrong directory, placeholder values |
| Knowledge Base | 4 | Metadata format, S3 delete flags, ingestion failures |

**Top 3 lessons from this build:**
1. **Always check CloudTrail** when AWS resource creation fails silently — the console masks real errors
2. **IAM permissions are additive** — managed policies don't grant cross-service access automatically
3. **S3 Vectors is too new** for production use with Bedrock KB — use OpenSearch Serverless

---

*Last Updated: May 2026 | AgenticOps Platform v1.0*