import boto3
import json

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
ssm = boto3.client("ssm", region_name="us-east-1")

RESULTS_TABLE = ssm.get_parameter(
    Name="/agenticops/dynamodb/results-table"
)["Parameter"]["Value"]

def lambda_handler(event, context):
    """
    Status Lambda — polls DynamoDB for async task result
    Called by GET /status/{taskId}
    """
    task_id = event.get("pathParameters", {}).get("taskId", "")

    if not task_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "taskId is required"})
        }

    table = dynamodb.Table(RESULTS_TABLE)
    item = table.get_item(Key={"taskId": task_id}).get("Item")

    if not item:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "taskId": task_id,
                "status": "not_found"
            })
        }

    # Return result if completed
    response_body = {
        "taskId": task_id,
        "status": item.get("status"),
        "submittedAt": item.get("submittedAt"),
        "completedAt": item.get("completedAt")
    }

    if item.get("status") == "completed":
        response_body["result"] = item.get("result", "")

    if item.get("status") == "failed":
        response_body["errorMessage"] = item.get("errorMessage", "")

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(response_body, default=str)
    }