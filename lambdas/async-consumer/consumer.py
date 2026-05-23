import boto3
import json
import time

ssm = boto3.client("ssm", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

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

        # Idempotency check
        existing = table.get_item(Key={"taskId": task_id}).get("Item", {})
        if existing.get("status") in ["processing", "completed"]:
            print(f"Task {task_id} already {existing['status']}, skipping")
            continue

        # Mark as processing
        table.update_item(
            Key={"taskId": task_id},
            UpdateExpression="SET #s = :s, startedAt = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "processing", ":t": int(time.time())}
        )

        try:
            # Invoke supervisor agent
            response = bedrock.invoke_agent(
                agentId=AGENT_ID,
                agentAliasId=ALIAS_ID,
                sessionId=session_id,
                inputText=task_text
            )

            # Stream full response
            agent_result = ""
            for event in response["completion"]:
                if "chunk" in event:
                    agent_result += event["chunk"]["bytes"].decode("utf-8")

            # Write completed result — use ExpressionAttributeNames for reserved keyword
            table.update_item(
                Key={"taskId": task_id},
                UpdateExpression="SET #s = :s, #r = :r, completedAt = :t",
                ExpressionAttributeNames={
                    "#s": "status",
                    "#r": "result"      # 'result' is reserved in DynamoDB
                },
                ExpressionAttributeValues={
                    ":s": "completed",
                    ":r": agent_result,
                    ":t": int(time.time())
                }
            )
            print(f"Task {task_id} completed successfully")

        except Exception as e:
            table.update_item(
                Key={"taskId": task_id},
                UpdateExpression="SET #s = :s, errorMessage = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "failed", ":e": str(e)}
            )
            print(f"Task {task_id} failed: {e}")
            raise

    return {"statusCode": 200}
