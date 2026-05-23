import boto3
import json

sfn = boto3.client("stepfunctions", region_name="us-east-1")
glue = boto3.client("glue", region_name="us-east-1")

def lambda_handler(event, context):
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    pipeline_type = parameters.get("pipelineType", "all")
    pipelines = []

    if pipeline_type in ["all", "stepfunctions"]:
        try:
            response = sfn.list_state_machines(maxResults=20)
            for sm in response["stateMachines"]:
                pipelines.append({
                    "name": sm["name"],
                    "arn": sm["stateMachineArn"],
                    "type": "stepfunctions",
                    "createdAt": sm["creationDate"].isoformat()
                })
        except Exception as e:
            pipelines.append({"type": "stepfunctions", "error": str(e)})

    if pipeline_type in ["all", "glue"]:
        try:
            response = glue.get_jobs(MaxResults=20)
            for job in response["Jobs"]:
                pipelines.append({
                    "name": job["Name"],
                    "type": "glue",
                    "createdAt": job.get("CreatedOn", "")
                })
        except Exception as e:
            pipelines.append({"type": "glue", "error": str(e)})

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
                        "pipelineCount": len(pipelines),
                        "pipelines": pipelines,
                        "note": "No pipelines found" if not pipelines else ""
                    })
                }
            }
        }
    }
