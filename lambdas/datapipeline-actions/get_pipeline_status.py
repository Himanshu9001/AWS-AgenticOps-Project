import boto3
import json

sfn = boto3.client("stepfunctions", region_name="us-east-1")
glue = boto3.client("glue", region_name="us-east-1")

def lambda_handler(event, context):
    """
    Action Group Lambda — gets execution status of a specific pipeline
    Returns last 5 executions with status, duration, and errors
    """
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    pipeline_name = parameters.get("pipelineName", "")
    pipeline_type = parameters.get("pipelineType", "stepfunctions")

    result = {}

    if pipeline_type == "stepfunctions":
        # Get state machine ARN from name
        machines = sfn.list_state_machines(maxResults=50)
        arn = next(
            (sm["stateMachineArn"] for sm in machines["stateMachines"]
             if sm["name"] == pipeline_name), None
        )

        if not arn:
            return _response(event, 404, {"error": f"Pipeline {pipeline_name} not found"})

        # Get last 5 executions
        executions = sfn.list_executions(
            stateMachineArn=arn,
            maxResults=5
        )

        runs = []
        for ex in executions["executions"]:
            duration = None
            if ex.get("stopDate"):
                duration = int((ex["stopDate"] - ex["startDate"]).total_seconds())

            runs.append({
                "executionArn": ex["executionArn"],
                "status": ex["status"],
                "startedAt": ex["startDate"].isoformat(),
                "stoppedAt": ex.get("stopDate", ""),
                "durationSeconds": duration
            })

        result = {
            "pipelineName": pipeline_name,
            "pipelineType": "stepfunctions",
            "stateMachineArn": arn,
            "recentExecutions": runs
        }

    elif pipeline_type == "glue":
        # Get last 5 Glue job runs
        runs_response = glue.get_job_runs(
            JobName=pipeline_name,
            MaxResults=5
        )

        runs = []
        for run in runs_response["JobRuns"]:
            runs.append({
                "jobRunId": run["Id"],
                "status": run["JobRunState"],
                "startedAt": run["StartedOn"].isoformat(),
                "completedAt": run.get("CompletedOn", ""),
                "errorMessage": run.get("ErrorMessage", ""),
                "durationSeconds": run.get("ExecutionTime", 0)
            })

        result = {
            "pipelineName": pipeline_name,
            "pipelineType": "glue",
            "recentRuns": runs
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
                    "body": json.dumps(body)
                }
            }
        }
    }