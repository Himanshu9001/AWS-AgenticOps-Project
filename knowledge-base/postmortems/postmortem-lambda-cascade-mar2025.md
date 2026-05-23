# Post-Mortem: Lambda Cascade Failure — Bedrock Agent Timeout

**Document Type:** Post-Mortem  
**Domain:** IT Operations / AI Platform  
**Incident ID:** INC-2025-0308  
**Date:** March 8, 2025  
**Duration:** 23 minutes (09:41 – 10:04 UTC)  
**Severity:** P2  
**Status:** Resolved  

---

## Summary

A Bedrock model latency spike caused the `agenticops-api-handler` Lambda to time out. Because the Lambda was configured with only a 30-second timeout and Bedrock's Claude Sonnet was experiencing elevated response times of 45–60 seconds, all agent invocations failed. The async SQS consumer also failed as it reused the same Lambda execution role without a separate timeout configuration.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 09:38 | AWS Health Dashboard posts degraded performance notice for Bedrock in us-east-1 |
| 09:41 | `AgenticOps-Lambda-ErrorRate-agenticops-api-handler` alarm fires (error rate 78%) |
| 09:42 | `AgenticOps-Lambda-ErrorRate-agenticops-async-consumer` alarm fires (error rate 61%) |
| 09:43 | PagerDuty alerts sent to on-call (Rahul M.) |
| 09:49 | Root cause identified as Bedrock latency — Lambda timeout too short |
| 09:52 | Lambda timeout increased from 30s to 120s for `agenticops-api-handler` |
| 09:54 | Lambda timeout increased from 60s to 180s for `agenticops-async-consumer` |
| 09:57 | Error rate begins dropping |
| 10:04 | Error rate returns to < 1%, incident resolved |
| 10:15 | AWS Health Dashboard shows Bedrock latency returning to normal |

---

## Root Cause

The `agenticops-api-handler` Lambda had a hardcoded 30-second timeout set during initial development when Bedrock response times were typically 8–15 seconds. During the Bedrock service degradation event, response times increased to 45–60 seconds, causing all Lambda invocations to hit the timeout before Bedrock could respond.

The SQS consumer (`agenticops-async-consumer`) had a 60-second timeout but Bedrock agent invocations with multiple tool calls were taking 90–120 seconds during the degradation, causing it to also fail.

---

## Cascade Effect

```
Bedrock latency spike (45-60s)
    ↓
api-handler Lambda times out (30s limit)
    ↓
All sync API requests return 500
    ↓
Clients retry → SQS queue depth increases
    ↓
async-consumer Lambda times out (60s limit)
    ↓
SQS messages requeued → consumer retries → DLQ fills up
    ↓
DynamoDB results table has no entries
    ↓
Supervisor agent polling for results gets empty responses
```

---

## Root Cause Analysis — Why Timeouts Were Too Low

1. **Timeouts set during development** using average-case latency, not worst-case
2. **No circuit breaker** — system kept retrying Bedrock instead of failing fast
3. **No Bedrock health check** in the agent invocation path
4. **SQS visibility timeout** (30s) was shorter than Lambda timeout (60s) — caused duplicate processing

---

## Impact

- **Duration:** 23 minutes
- **Users affected:** ~340 active users
- **API error rate:** Peak 78% on sync path, 61% on async path
- **SLA breach:** No — within monthly 99.9% budget
- **DLQ messages:** 847 messages sent to dead letter queue, all reprocessed successfully

---

## Action Items

| Action | Owner | Due Date | Status |
|---|---|---|---|
| Set Lambda timeouts to 3x expected Bedrock p99 latency | Platform Team | 2025-03-15 | ✅ Completed |
| Implement exponential backoff on Bedrock retries | Platform Team | 2025-03-20 | ✅ Completed |
| Set SQS visibility timeout = Lambda timeout + 30s buffer | Platform Team | 2025-03-12 | ✅ Completed |
| Add AWS Health Dashboard monitoring to PagerDuty | On-call Team | 2025-03-10 | ✅ Completed |
| Implement fallback model (Haiku) when Sonnet latency > 20s | AI Team | 2025-04-01 | 🔄 In Progress |
| Add Bedrock latency metric to CloudWatch dashboard | Platform Team | 2025-03-15 | ✅ Completed |

---

## Recommended Lambda Timeout Configuration

Based on this incident and load testing, use these timeout values:

| Function | Recommended Timeout | Rationale |
|---|---|---|
| `agenticops-api-handler` | 120 seconds | Bedrock Sonnet p99 = 35s, 3x buffer |
| `agenticops-async-consumer` | 300 seconds | Multi-tool agent calls can reach 90s |
| `agenticops-itops-remediate` | 60 seconds | Simple API calls, 2x buffer |
| `agenticops-pipeline-status` | 30 seconds | Fast Glue API calls |

---

## Lessons Learned

1. **Lambda timeout must account for worst-case downstream latency** — use p99 + 3x multiplier, not average
2. **SQS visibility timeout must exceed Lambda timeout** — otherwise messages become visible again mid-processing causing duplicate execution
3. **Bedrock is a dependency — treat it like any external service** — add health checks, circuit breakers, and fallback models
4. **Monitor Bedrock latency as a first-class metric** — add `Bedrock/InvokeModel/Latency` to your main dashboard

---

## Related Documents

- `runbook-lambda-errors.md`
- `runbook-high-cpu-alarm.md`
- `pipeline-sop-async-pipeline.md`
