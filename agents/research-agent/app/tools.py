import boto3
import json
from langchain_core.tools import tool
from tavily import TavilyClient
from botocore.config import Config

ssm = boto3.client("ssm", region_name="us-east-1")

def get_param(name: str, decrypt: bool = False) -> str:
    return ssm.get_parameter(Name=name, WithDecryption=decrypt)["Parameter"]["Value"]

TAVILY_API_KEY = get_param("/agenticops/tavily/api-key", decrypt=True)
KB_ID = get_param("/agenticops/bedrock/kb-id")

bedrock_config = Config(read_timeout=30, connect_timeout=10, retries={"max_attempts": 3, "mode": "adaptive"})
bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=bedrock_config)
tavily = TavilyClient(api_key=TAVILY_API_KEY)


@tool
def web_search(query: str) -> str:
    """Search the web for current information not available in the knowledge base.
    Use this for recent AWS announcements, latest Bedrock features, external
    incident reports, or any time-sensitive information."""
    try:
        results = tavily.search(query=query, search_depth="advanced", max_results=5, include_answer=True)
        formatted = []
        if results.get("answer"):
            formatted.append(f"Direct Answer: {results['answer']}\n")
        for i, result in enumerate(results.get("results", []), 1):
            formatted.append(f"[{i}] {result['title']}\nURL: {result['url']}\nContent: {result['content'][:500]}\n")
        return "\n".join(formatted) if formatted else "No results found."
    except Exception as e:
        return f"Web search failed: {str(e)}"


@tool
def kb_retrieve(query: str) -> str:
    """Search the AgenticOps knowledge base for internal runbooks, post-mortems,
    and pipeline SOPs. Use this before web_search for operational questions
    about this platform's infrastructure, past incidents, or procedures."""
    try:
        response = bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}}
        )
        results = []
        for item in response.get("retrievalResults", []):
            score = round(item.get("score", 0), 4)
            text = item.get("content", {}).get("text", "")
            source = item.get("location", {}).get("s3Location", {}).get("uri", "")
            results.append(f"[Score: {score}] Source: {source}\n{text[:600]}\n")
        return "\n---\n".join(results) if results else "No relevant documents found in KB."
    except Exception as e:
        return f"KB retrieval failed: {str(e)}"


@tool
def summarize_document(url: str, focus: str = "") -> str:
    """Fetch and summarize a specific web page or document URL.
    Use this when web_search returns a relevant URL and you need
    the full content rather than just the snippet."""
    try:
        result = tavily.extract(urls=[url])
        content = ""
        for item in result.get("results", []):
            content += item.get("raw_content", "")[:3000]
        if not content:
            return f"Could not extract content from {url}"
        bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
        prompt = f"Summarize this content{' focusing on: ' + focus if focus else ''}:\n\n{content}"
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-sonnet-4-6",
            body=json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "anthropic_version": "bedrock-2023-05-31"
            })
        )
        summary = json.loads(response["body"].read())["content"][0]["text"]
        return f"Summary of {url}:\n{summary}"
    except Exception as e:
        return f"Document summarization failed: {str(e)}"


TOOLS = [web_search, kb_retrieve, summarize_document]
