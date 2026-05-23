import boto3
import json
import uuid
import time
from botocore.config import Config

ssm = boto3.client("ssm", region_name="us-east-1")
sqs = boto3.client("sqs", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

def get_param(name):
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

QUEUE_URL = get_param("/agenticops/sqs/async-tasks-url")
RESULTS_TABLE = get_param("/agenticops/dynamodb/results-table")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,GET,OPTIONS"
}

def lambda_handler(event, context):
    # Handle CORS preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    body = json.loads(event.get("body", "{}"))
    task_text = body.get("task", "")
    async_mode = body.get("async", False)
    session_id = body.get("sessionId", f"session-{uuid.uuid4().hex[:8]}")

    if not task_text:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "task field is required"})
        }

    task_id = f"task-{uuid.uuid4().hex[:12]}"

    if async_mode:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "taskId": task_id,
                "sessionId": session_id,
                "task": task_text,
                "submittedAt": int(time.time())
            })
        )

        table = dynamodb.Table(RESULTS_TABLE)
        table.put_item(Item={
            "taskId": task_id,
            "status": "queued",
            "task": task_text,
            "sessionId": session_id,
            "submittedAt": int(time.time()),
            "ttl": int(time.time()) + 3600
        })

        return {
            "statusCode": 202,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "taskId": task_id,
                "status": "queued",
                "pollUrl": f"/status/{task_id}"
            })
        }

    else:
        config = Config(read_timeout=120, connect_timeout=10)
        bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=config)
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
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "taskId": task_id,
                "status": "completed",
                "result": result
            })
        }
