import boto3
import json
import uuid
import time

# Read config from SSM at cold start — not per invocation
ssm = boto3.client("ssm", region_name="us-east-1")
sqs = boto3.client("sqs", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

def get_param(name):
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

# Load config once at cold start
QUEUE_URL = get_param("/agenticops/sqs/async-tasks-url")
RESULTS_TABLE = get_param("/agenticops/dynamodb/results-table")

def lambda_handler(event, context):
    """
    API Handler Lambda — entry point for all agent requests
    Sync path: short tasks returned directly
    Async path: long tasks queued, taskId returned immediately
    """
    body = json.loads(event.get("body", "{}"))
    task_text = body.get("task", "")
    async_mode = body.get("async", False)
    session_id = body.get("sessionId", f"session-{uuid.uuid4().hex[:8]}")

    if not task_text:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "task field is required"})
        }

    task_id = f"task-{uuid.uuid4().hex[:12]}"

    if async_mode:
        # Async path — publish to SQS and return taskId immediately
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "taskId": task_id,
                "sessionId": session_id,
                "task": task_text,
                "submittedAt": int(time.time())
            }),
            MessageGroupId=session_id  # not used for standard queue but good practice
        )

        # Write initial status to DynamoDB
        table = dynamodb.Table(RESULTS_TABLE)
        table.put_item(Item={
            "taskId": task_id,
            "status": "queued",
            "task": task_text,
            "sessionId": session_id,
            "submittedAt": int(time.time()),
            "ttl": int(time.time()) + 3600  # expire after 1 hour
        })

        return {
            "statusCode": 202,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "taskId": task_id,
                "status": "queued",
                "pollUrl": f"/status/{task_id}"
            })
        }

    else:
        # Sync path — invoke supervisor agent directly and wait
        bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
        agent_id = get_param("/agenticops/bedrock/supervisor-agent-id")
        alias_id = get_param("/agenticops/bedrock/supervisor-agent-alias-id")

        response = bedrock.invoke_agent(
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=session_id,
            inputText=task_text
        )

        result = ""
        for event in response["completion"]:
            if "chunk" in event:
                result += event["chunk"]["bytes"].decode("utf-8")

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "taskId": task_id,
                "status": "completed",
                "result": result
            })
        }