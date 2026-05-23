# SOP: Knowledge Base Document Ingestion Pipeline

**Document Type:** Pipeline SOP  
**Domain:** Data Pipeline Operations  
**Pipeline Name:** `agenticops-kb-ingestion`  
**Last Updated:** 2025-03-10  
**Owner:** Data Engineering Team

---

## Overview

This SOP covers the operation, monitoring, and troubleshooting of the Knowledge Base document ingestion pipeline. This pipeline processes raw documents from S3, chunks them, generates embeddings via Titan Embed v2, and indexes them into OpenSearch Serverless for use by Bedrock Knowledge Base.

---

## Pipeline Architecture

```
Document Upload (S3)
    ↓ S3 Event Notification
SQS Queue: agenticops-kb-ingestion-queue
    ↓ Lambda trigger (batch size: 10)
Lambda: agenticops-kb-preprocessor
    ↓ chunk + clean text
Bedrock KB Sync Job (StartIngestionJob API)
    ↓ embed via Titan Embed v2
OpenSearch Serverless (vector index)
    ↓
Bedrock Knowledge Base (queryable)
```

---

## Supported Document Types

| Format | Max Size | Notes |
|---|---|---|
| PDF | 50 MB | Text extraction only, no image OCR |
| Markdown (.md) | 10 MB | Preferred format |
| Plain text (.txt) | 10 MB | UTF-8 encoding required |
| HTML | 10 MB | Tags stripped during processing |
| Word (.docx) | 25 MB | Converted to text |

---

## Starting an Ingestion Job

### Manual Trigger (Console)

1. Go to **Amazon Bedrock → Knowledge Bases → agenticops-kb**
2. Click **Sync** button
3. Select data source: `agenticops-knowledge-base-docs`
4. Click **Sync now**
5. Monitor progress in the **Ingestion jobs** tab

### Manual Trigger (CLI)

```bash
# Start ingestion job
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <KB_ID> \
  --data-source-id <DS_ID> \
  --region us-east-1

# Check job status
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id <KB_ID> \
  --data-source-id <DS_ID> \
  --ingestion-job-id <JOB_ID> \
  --region us-east-1
```

### Automated Trigger

The pipeline auto-triggers when:
1. New document uploaded to `s3://agenticops-knowledge-base-docs/`
2. EventBridge scheduled rule fires at 02:00 UTC daily (full sync)

---

## Monitoring the Pipeline

### Key Metrics to Watch

| Metric | Source | Threshold | Action |
|---|---|---|---|
| Ingestion job status | Bedrock console | FAILED | Check CloudWatch logs |
| SQS queue depth | CloudWatch | > 100 messages | Check Lambda consumer |
| Lambda errors | CloudWatch | > 5% error rate | See runbook-lambda-errors.md |
| Documents indexed | Bedrock KB console | < expected count | Re-trigger sync |

### CloudWatch Logs Insights Query

```
# Check ingestion job failures
fields @timestamp, @message
| filter @message like /FAILED/ or @message like /ERROR/
| sort @timestamp desc
| limit 50
```

---

## Chunking Configuration

Current configuration uses **hierarchical chunking**:

| Parameter | Value | Reason |
|---|---|---|
| Parent chunk size | 1500 tokens | Provides full context for LLM |
| Child chunk size | 300 tokens | Precise retrieval granularity |
| Overlap | 20% | Prevents context loss at chunk boundaries |
| Embedding model | Titan Embed v2 | AWS-native, 1024 dimensions |

**Do not change chunking config without re-syncing entire KB** — changing chunk sizes mid-operation creates inconsistent vector representations.

---

## Metadata Schema

Every document should include these metadata attributes in its S3 object tags or in a companion `.metadata.json` file:

```json
{
  "doc_type": "runbook | postmortem | pipeline-sop | architecture",
  "domain": "itops | datapipeline | ai-platform | security",
  "severity": "critical | high | medium | low | info",
  "team": "platform | database | data-engineering | security",
  "date": "YYYY-MM-DD"
}
```

**Example metadata file:** `runbook-high-cpu-alarm.md.metadata.json`
```json
{
  "metadataAttributes": {
    "doc_type": {"value": {"stringValue": "runbook"}, "type": "STRING"},
    "domain": {"value": {"stringValue": "itops"}, "type": "STRING"},
    "severity": {"value": {"stringValue": "high"}, "type": "STRING"}
  }
}
```

---

## Troubleshooting

### Issue: Ingestion job stuck in STARTING state

**Cause:** OpenSearch Serverless collection not ready or IAM permissions missing.

**Fix:**
```bash
# Check AOSS collection status
aws opensearchserverless list-collections \
  --collection-filters '{"status":"CREATING"}' \
  --region us-east-1

# Verify KB IAM role has AOSS access
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT:role/agenticops-kb-role \
  --action-names "aoss:APIAccessAll" \
  --resource-arns "*"
```

### Issue: Documents uploaded but not searchable

**Cause:** Sync job not triggered or completed with partial failure.

**Fix:**
1. Check last ingestion job status in Bedrock console
2. If FAILED — check CloudWatch logs for the specific document that failed
3. Remove the failing document, re-trigger sync, then fix and re-upload the document

### Issue: Retrieval returns wrong chunks

**Cause:** Stale vectors from old chunking config, or metadata filter too restrictive.

**Fix:**
```bash
# Delete all documents and re-sync (nuclear option — use carefully)
# First remove all objects from S3 prefix
aws s3 rm s3://agenticops-knowledge-base-docs/ --recursive

# Re-upload all documents
aws s3 cp ./knowledge-base/ s3://agenticops-knowledge-base-docs/ --recursive

# Trigger full sync
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <KB_ID> \
  --data-source-id <DS_ID>
```

---

## SLA / Performance Targets

| Metric | Target |
|---|---|
| Single document ingestion time | < 2 minutes |
| Bulk ingestion (100 docs) | < 15 minutes |
| Retrieval latency (p99) | < 500ms |
| KB sync daily job completion | Before 04:00 UTC |

---

## Related Documents

- `runbook-lambda-errors.md`
- `postmortem-cpu-spike-jan2025.md`
- `pipeline-sop-async-pipeline.md`
