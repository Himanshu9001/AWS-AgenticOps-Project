import boto3
import json

cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

def lambda_handler(event, context):
    """
    Action Group Lambda — returns active CloudWatch alarms
    Bedrock passes action parameters via event["parameters"]
    """
    # Extract parameters from Bedrock action group invocation
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    state = parameters.get("state", "ALARM")
    namespace = parameters.get("namespace", "")

    # Build filter — namespace is optional
    kwargs = {"StateValue": state, "MaxRecords": 20}
    if namespace:
        kwargs["AlarmNamePrefix"] = namespace

    response = cloudwatch.describe_alarms(**kwargs)

    # Format alarms for agent consumption
    alarms = []
    for alarm in response["MetricAlarms"]:
        alarms.append({
            "alarmName": alarm["AlarmName"],
            "state": alarm["StateValue"],
            "metric": alarm["MetricName"],
            "namespace": alarm["Namespace"],
            "threshold": alarm.get("Threshold"),
            "stateReason": alarm["StateReason"],
            "updatedAt": alarm["StateUpdatedTimestamp"].isoformat()
        })

    # Bedrock action group response format — must follow this exactly
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "apiPath": event["apiPath"],
            "httpMethod": event["httpMethod"],
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {
                    "body": json.dumps({
                        "alarmCount": len(alarms),
                        "alarms": alarms
                    })
                }
            }
        }
    }