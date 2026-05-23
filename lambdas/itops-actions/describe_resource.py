import boto3
import json

ec2 = boto3.client("ec2", region_name="us-east-1")
rds = boto3.client("rds", region_name="us-east-1")
cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

def lambda_handler(event, context):
    """
    Action Group Lambda — describes AWS resource state
    Supports EC2 instances and RDS instances
    """
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    resource_type = parameters.get("resourceType", "ec2")
    resource_id = parameters.get("resourceId", "")

    result = {}

    if resource_type == "ec2":
        # Get EC2 instance details
        response = ec2.describe_instances(InstanceIds=[resource_id])
        instance = response["Reservations"][0]["Instances"][0]

        # Get CPU metric for last 5 minutes
        cw = cloudwatch.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
            StartTime=__import__("datetime").datetime.utcnow() - __import__("datetime").timedelta(minutes=5),
            EndTime=__import__("datetime").datetime.utcnow(),
            Period=300,
            Statistics=["Average", "Maximum"]
        )

        cpu = cw["Datapoints"][0] if cw["Datapoints"] else {}
        result = {
            "instanceId": instance["InstanceId"],
            "instanceType": instance["InstanceType"],
            "state": instance["State"]["Name"],
            "privateIp": instance.get("PrivateIpAddress", ""),
            "cpuAvg": round(cpu.get("Average", 0), 2),
            "cpuMax": round(cpu.get("Maximum", 0), 2)
        }

    elif resource_type == "rds":
        # Get RDS instance details
        response = rds.describe_db_instances(DBInstanceIdentifier=resource_id)
        db = response["DBInstances"][0]
        result = {
            "dbIdentifier": db["DBInstanceIdentifier"],
            "dbClass": db["DBInstanceClass"],
            "engine": db["Engine"],
            "status": db["DBInstanceStatus"],
            "endpoint": db.get("Endpoint", {}).get("Address", ""),
            "multiAZ": db["MultiAZ"]
        }

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "apiPath": event["apiPath"],
            "httpMethod": event["httpMethod"],
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(result)
                }
            }
        }
    }