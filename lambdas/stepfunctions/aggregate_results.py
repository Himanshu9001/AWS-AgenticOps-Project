import boto3
import json
import uuid
import time
from botocore.config import Config

config = Config(read_timeout=300, connect_timeout=10)
bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=config)
ssm = boto3.client("ssm", region_name="us-east-1")

def get_param(name):
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

SUPERVISOR_ID = get_param("/agenticops/bedrock/supervisor-agent-id")
SUPERVISOR_ALIAS = get_param("/agenticops/bedrock/supervisor-agent-alias-id")

def lambda_handler(event, context):
    """
    Aggregator Lambda — takes parallel agent results
    and asks supervisor to synthesize them
    """
    parallel_results = event["parallelResults"]
    session_id = event.get("sessionId", f"sfn-{uuid.uuid4().hex[:8]}")

    # Extract results from parallel branches
    itops_result = parallel_results[0].get("Payload", {}).get("result", "No IT Ops data")
    pipeline_result = parallel_results[1].get("Payload", {}).get("result", "No Pipeline data")

    # Ask supervisor to synthesize both results
    synthesis_prompt = f"""
    I have collected analysis from two specialist agents. Please synthesize these into a unified incident report.

    IT Ops Agent Analysis:
    {itops_result}

    Data Pipeline Agent Analysis:
    {pipeline_result}

    Please provide a unified summary with:
    1. Combined root cause analysis
    2. Priority-ordered action items
    3. Prevention recommendations
    """

    response = bedrock.invoke_agent(
        agentId=SUPERVISOR_ID,
        agentAliasId=SUPERVISOR_ALIAS,
        sessionId=session_id,
        inputText=synthesis_prompt
    )

    result = ""
    for event in response["completion"]:
        if "chunk" in event:
            result += event["chunk"]["bytes"].decode("utf-8")

    return {
        "taskId": f"sfn-{uuid.uuid4().hex[:12]}",
        "result": result,
        "sessionId": session_id,
        "completedAt": int(time.time())
    }