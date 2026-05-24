import boto3
import json
import urllib.request
import urllib.error

# Load config at cold start
ssm = boto3.client("ssm", region_name="us-east-1")

def get_param(name):
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

RESEARCH_AGENT_IP = get_param("/agenticops/ecs/research-agent-ip")
RESEARCH_AGENT_URL = f"http://{RESEARCH_AGENT_IP}:8080/research"

def lambda_handler(event, context):
    """
    Action Group Lambda — bridges Bedrock Supervisor to LangGraph Research Agent
    Extracts query from Bedrock action group event and calls ECS FastAPI endpoint
    """
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    query = parameters.get("query", "")
    session_id = event.get("sessionId", "default")

    if not query:
        return _response(event, 400, {"error": "query parameter is required"})

    try:
        # Call LangGraph Research Agent on ECS
        payload = json.dumps({
            "query": query,
            "sessionId": session_id
        }).encode("utf-8")

        req = urllib.request.Request(
            RESEARCH_AGENT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read())

        return _response(event, 200, {
            "answer": result["answer"],
            "toolsUsed": result["toolsUsed"],
            "durationMs": result["durationMs"]
        })

    except urllib.error.URLError as e:
        return _response(event, 503, {
            "error": f"Research agent unavailable: {str(e)}",
            "agentUrl": RESEARCH_AGENT_URL
        })
    except Exception as e:
        return _response(event, 500, {"error": str(e)})


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
