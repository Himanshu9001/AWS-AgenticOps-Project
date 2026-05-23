import boto3
import json
from botocore.config import Config

config = Config(read_timeout=300, connect_timeout=10)
bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=config)

def lambda_handler(event, context):
    """
    Step Functions Lambda — invokes a specific Bedrock agent
    Called by both parallel branches of the state machine
    """
    agent_id = event["agentId"]
    agent_alias_id = event["agentAliasId"]
    session_id = event["sessionId"]
    input_text = event["inputText"]

    response = bedrock.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=input_text
    )

    # Stream full response
    result = ""
    for event in response["completion"]:
        if "chunk" in event:
            result += event["chunk"]["bytes"].decode("utf-8")

    return {
        "agentId": agent_id,
        "sessionId": session_id,
        "result": result
    }