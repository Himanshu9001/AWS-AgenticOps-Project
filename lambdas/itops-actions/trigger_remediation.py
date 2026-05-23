import boto3
import json

ec2 = boto3.client("ec2", region_name="us-east-1")
ssm = boto3.client("ssm", region_name="us-east-1")

# Allowed actions — agent cannot execute anything outside this list
ALLOWED_ACTIONS = [
    "restart-service",
    "scale-out",
    "reboot-instance"
]

def lambda_handler(event, context):
    """
    Action Group Lambda — executes safe remediation actions
    Guardrailed — only ALLOWED_ACTIONS can be executed
    Human approval required for destructive actions
    """
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    action = parameters.get("action", "")
    resource_id = parameters.get("resourceId", "")
    reason = parameters.get("reason", "Agent-triggered remediation")

    # Hard guardrail — reject anything not in allowlist
    if action not in ALLOWED_ACTIONS:
        return _response(event, 403, {
            "status": "rejected",
            "reason": f"Action '{action}' is not in the allowed remediation list",
            "allowedActions": ALLOWED_ACTIONS
        })

    result = {}

    if action == "restart-service":
        # Run SSM command to restart service on EC2
        response = ssm.send_command(
            InstanceIds=[resource_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [
                "sudo systemctl restart agenticops-app",
                "sudo systemctl status agenticops-app"
            ]},
            Comment=reason
        )
        result = {
            "status": "executed",
            "action": action,
            "commandId": response["Command"]["CommandId"],
            "resourceId": resource_id
        }

    elif action == "scale-out":
        # Get current ASG desired capacity and increment by 1
        asg = boto3.client("autoscaling", region_name="us-east-1")
        groups = asg.describe_auto_scaling_groups(
            AutoScalingGroupNames=[resource_id]
        )
        current = groups["AutoScalingGroups"][0]["DesiredCapacity"]
        asg.set_desired_capacity(
            AutoScalingGroupName=resource_id,
            DesiredCapacity=current + 1
        )
        result = {
            "status": "executed",
            "action": action,
            "previousCapacity": current,
            "newCapacity": current + 1,
            "resourceId": resource_id
        }

    elif action == "reboot-instance":
        ec2.reboot_instances(InstanceIds=[resource_id])
        result = {
            "status": "executed",
            "action": action,
            "resourceId": resource_id,
            "note": "Instance reboot initiated"
        }

    return _response(event, 200, result)


def _response(event, status_code, body):
    """Helper — formats Bedrock action group response"""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "apiPath": event["apiPath"],
            "httpMethod": event["httpMethod"],
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(body)
                }
            }
        }
    }