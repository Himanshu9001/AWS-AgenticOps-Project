import boto3
import json
import time
import logging
from botocore.config import Config

# Structured JSON logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log(level, event, **kwargs):
    logger.log(level, json.dumps({
        "event": event,
        "timestamp": int(time.time()),
        **kwargs
    }))

ssm = boto3.client("ssm", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
config = Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 3, "mode": "adaptive"})
bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=config)

def get_param(name):
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

RESULTS_TABLE = get_param("/agenticops/dynamodb/results-table")
AGENT_ID = get_param("/agenticops/bedrock/supervisor-agent-id")
ALIAS_ID = get_param("/agenticops/bedrock/supervisor-agent-alias-id")

def lambda_handler(event, context):
    table = dynamodb.Table(RESULTS_TABLE)

    for record in event["Records"]:
        task = json.loads(record["body"])
        task_id = task["taskId"]
        session_id = task["sessionId"]
        task_text = task["task"]

        log(logging.INFO, "task_received",
            taskId=task_id,
            sessionId=session_id,
            requestId=context.aws_request_id)

        # Idempotency check
        existing = table.get_item(Key={"taskId": task_id}).get("Item", {})
        if existing.get("status") in ["processing", "completed"]:
            log(logging.INFO, "task_skipped_duplicate",
                taskId=task_id,
                existingStatus=existing["status"])
            continue

        # Mark as processing
        table.update_item(
            Key={"taskId": task_id},
            UpdateExpression="SET #s = :s, startedAt = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "processing", ":t": int(time.time())}
        )

        start_time = time.time()

        try:
            response = bedrock.invoke_agent(
                agentId=AGENT_ID,
                agentAliasId=ALIAS_ID,
                sessionId=session_id,
                inputText=task_text
            )

            agent_result = ""
            for event in response["completion"]:
                if "chunk" in event:
                    agent_result += event["chunk"]["bytes"].decode("utf-8")

            duration_ms = int((time.time() - start_time) * 1000)

            table.update_item(
                Key={"taskId": task_id},
                UpdateExpression="SET #s = :s, #r = :r, completedAt = :t",
                ExpressionAttributeNames={"#s": "status", "#r": "result"},
                ExpressionAttributeValues={
                    ":s": "completed",
                    ":r": agent_result,
                    ":t": int(time.time())
                }
            )

            log(logging.INFO, "task_completed",
                taskId=task_id,
                durationMs=duration_ms,
                resultLength=len(agent_result))

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            table.update_item(
                Key={"taskId": task_id},
                UpdateExpression="SET #s = :s, errorMessage = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": str(e)}
            )

            log(logging.ERROR, "task_failed",
                taskId=task_id,
                durationMs=duration_ms,
                error=str(e))
            raise

    return {"statusCode": 200}
