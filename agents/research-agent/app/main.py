import time
import logging
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.agent import run_research

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log(event: str, **kwargs):
    logger.info(json.dumps({"event": event, "timestamp": int(time.time()), **kwargs}))

app = FastAPI(
    title="AgenticOps Research Agent",
    description="LangGraph-powered research agent with web search and KB retrieval",
    version="1.0.0"
)

class ResearchRequest(BaseModel):
    query: str
    sessionId: str = "default"

class ResearchResponse(BaseModel):
    answer: str
    toolsUsed: list[str]
    messageCount: int
    sessionId: str
    durationMs: int

@app.get("/health")
def health():
    return {"status": "healthy", "service": "agenticops-research-agent"}

@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest):
    start = time.time()
    log("research_request", query=request.query, sessionId=request.sessionId)
    try:
        result = run_research(request.query)
        duration_ms = int((time.time() - start) * 1000)
        log("research_complete", sessionId=request.sessionId, toolsUsed=result["toolsUsed"], durationMs=duration_ms)
        return ResearchResponse(
            answer=result["answer"],
            toolsUsed=result["toolsUsed"],
            messageCount=result["messageCount"],
            sessionId=request.sessionId,
            durationMs=duration_ms
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        log("research_failed", error=str(e), durationMs=duration_ms)
        raise HTTPException(status_code=500, detail=str(e))
