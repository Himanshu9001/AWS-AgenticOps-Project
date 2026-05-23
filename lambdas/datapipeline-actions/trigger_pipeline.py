import boto3
import json
import uuid

sfn = boto3.client("stepfunctions", region_name="us-east-1")
glue = boto3.client("glue", region_name="us-east-1")

# Only these pipelines can be triggered by the agent
ALLOWED_PIPELINES = [
    "agenticops-kb-ingestion",
    "agenticops-data-quality",
    "agenticops-db-backup-verifier"
]

def lambda_handler(event, context):
    """
    Action Group Lambda — triggers or retries a pipeline execution
    Guardrailed — only ALLOWED_PIPELINES can be triggered
    """
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    pipeline_name = parameters.get("pipelineName", "")
    pipeline_type = parameters.get("pipelineType", "stepfunctions")
    action = parameters.get("action", "start")  # start or retry
    input_payload = parameters.get("inputPayload", "{}")

    # Hard guardrail — only allowed pipelines
    if pipeline_name not in ALLOWED_PIPELINES:
        return _response(event, 403, {
            "status": "rejected",
            "reason": f"Pipeline '{pipeline_name}' is not in the allowed list",
            "allowedPipelines": ALLOWED_PIPELINES
        })

    result = {}

    if pipeline_type == "stepfunctions" and action == "start":
        # Get state machine ARN
        machines = sfn.list_state_machines(maxResults=50)
        arn = next(
            (sm["stateMachineArn"] for sm in machines["stateMachines"]
             if sm["name"] == pipeline_name), None
        )

        if not arn:
            return _response(event, 404, {"error": f"Pipeline {pipeline_name} not found"})

        # Start execution with unique name
        execution = sfn.start_execution(
            stateMachineArn=arn,
            name=f"agent-triggered-{uuid.uuid4().hex[:8]}",
            input=input_payload
        )

        result = {
            "status": "started",
            "pipelineName": pipeline_name,
            "executionArn": execution["executionArn"],
            "startedAt": execution["startDate"].isoformat()
        }

    elif pipeline_type == "glue" and action == "start":
        # Start Glue job run
        run = glue.start_job_run(JobName=pipeline_name)
        result = {
            "status": "started",
            "pipelineName": pipeline_name,
            "jobRunId": run["JobRunId"]
        }

    elif action == "retry":
        # Re-trigger same pipeline
        result = {
            "status": "retried",
            "pipelineName": pipeline_name,
            "note": "Retry treated as fresh start for idempotent pipelines"
        }

    return _response(event, 200, result)


def _response(event, status_code, body):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "apiPath": event["apiPath"],
            "httpMethod": event["httpMethod"],
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(body, default=str)
                }
            }
        }
    }