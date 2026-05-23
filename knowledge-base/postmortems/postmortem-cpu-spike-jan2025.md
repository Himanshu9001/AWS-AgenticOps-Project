# Post-Mortem: EC2 CPU Spike — Runaway Embedding Job

**Document Type:** Post-Mortem  
**Domain:** IT Operations / AI Platform  
**Incident ID:** INC-2025-0119  
**Date:** January 19, 2025  
**Duration:** 18 minutes (11:05 – 11:23 UTC)  
**Severity:** P2  
**Status:** Resolved  

---

## Summary

A bulk document ingestion job triggered an unthrottled embedding generation loop on a `t3.large` EC2 instance hosting the document preprocessing service. The instance CPU reached 99.8% causing the instance to become unresponsive. The Knowledge Base sync job failed, leaving the Bedrock KB in a partially updated state.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| 11:02 | Bulk upload of 847 documents to `agenticops-knowledge-base-docs` S3 bucket |
| 11:03 | S3 event triggers document preprocessing Lambda → spawns EC2 batch job |
| 11:05 | CloudWatch alarm fires: `AgenticOps-HighCPU-i-0abc123def456` (CPU 97%) |
| 11:06 | PagerDuty alert sent to on-call (Sneha P.) |
| 11:07 | EC2 instance stops responding to SSH |
| 11:09 | On-call engineer identifies runaway Python process consuming 400% CPU (multiprocessing) |
| 11:11 | Decision: stop EC2 instance, restart with throttled job |
| 11:14 | EC2 instance stopped via AWS Console |
| 11:17 | Instance restarted with environment variable `MAX_WORKERS=2` set |
| 11:23 | CPU stabilizes at 45%, incident resolved |
| 11:45 | KB sync job re-triggered manually, completed successfully |

---

## Root Cause

The document preprocessing script used Python `multiprocessing.Pool` with `processes=cpu_count()`. On a `t3.large` (2 vCPUs), `cpu_count()` returned 2 — but the multiprocessing pool spawned child processes which themselves spawned threads, resulting in effective 8x CPU oversubscription. Combined with 847 documents to process, the instance became CPU-saturated within 2 minutes.

**Faulty code:**
```python
from multiprocessing import Pool, cpu_count

def process_documents(doc_list):
    # BUG: cpu_count() on t3.large = 2, but children also multi-thread
    with Pool(processes=cpu_count()) as pool:
        results = pool.map(embed_and_chunk, doc_list)
    return results
```

**Fix applied:**
```python
import os

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))

def process_documents(doc_list):
    # Fixed: explicit worker count + batching with sleep between batches
    with Pool(processes=MAX_WORKERS) as pool:
        for i in range(0, len(doc_list), BATCH_SIZE):
            batch = doc_list[i:i+BATCH_SIZE]
            pool.map(embed_and_chunk, batch)
            time.sleep(2)  # throttle between batches
```

---

## Contributing Factors

1. **No CPU alarm action beyond notification** — alarm fired but no auto-scaling or auto-remediation
2. **Bulk upload not rate-limited** — no S3 event notification throttling
3. **Knowledge Base sync not idempotent** — partial failure left KB in inconsistent state
4. **Instance type too small** for batch workloads — `t3.large` burstable instances deplete CPU credits under sustained load

---

## Impact

- **Duration:** 18 minutes
- **Users affected:** 0 direct user impact (background job)
- **KB state:** Partially updated — 312 of 847 documents indexed before failure
- **SLA breach:** No
- **Data loss:** No — all 847 documents safely in S3, re-indexed successfully

---

## Action Items

| Action | Owner | Due Date | Status |
|---|---|---|---|
| Add `MAX_WORKERS` environment variable with default=2 | Platform Team | 2025-01-22 | ✅ Completed |
| Move batch jobs to dedicated `c6i.large` (non-burstable) instance | Infra Team | 2025-02-01 | ✅ Completed |
| Implement KB sync idempotency using S3 object ETags | Platform Team | 2025-02-15 | ✅ Completed |
| Add S3 event notification rate limiting via SQS | Platform Team | 2025-02-15 | ✅ Completed |
| Add CloudWatch alarm auto-action: scale out ASG on CPU > 90% | Infra Team | 2025-01-25 | ✅ Completed |

---

## Lessons Learned

1. **Never use `cpu_count()` without an explicit cap** — always set `MAX_WORKERS` via environment variable so it can be tuned per environment
2. **Burstable instances (t3.*) are not suitable for sustained CPU workloads** — use compute-optimized (c6i, c7g) for batch processing
3. **Bulk ingestion must go through SQS** — rate-limit document processing to protect downstream resources
4. **KB sync jobs must be idempotent** — use ETags or checksums to skip already-processed documents on retry

---

## Related Documents

- `runbook-high-cpu-alarm.md`
- `pipeline-sop-kb-ingestion.md`
- `runbook-lambda-errors.md`
