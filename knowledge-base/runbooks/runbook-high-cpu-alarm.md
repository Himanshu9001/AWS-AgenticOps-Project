# Runbook: High CPU Utilization Alarm Response

**Document Type:** Runbook  
**Domain:** IT Operations  
**Severity:** High  
**Last Updated:** 2025-01-15  
**Owner:** Platform Engineering Team

---

## Overview

This runbook describes the standard response procedure when a CloudWatch alarm fires for high CPU utilization on EC2 instances or ECS/EKS workloads. High CPU can indicate runaway processes, traffic spikes, under-provisioned instances, or application bugs.

---

## Alarm Definition

- **Alarm Name:** `AgenticOps-HighCPU-{instance-id}`
- **Threshold:** CPU Utilization > 85% for 5 consecutive minutes
- **Metric:** `AWS/EC2 CPUUtilization`
- **Action:** SNS notification → PagerDuty → On-call engineer

---

## Severity Classification

| CPU % | Duration | Severity | Response Time |
|---|---|---|---|
| 85–90% | 5 min | Medium | 30 minutes |
| 90–95% | 5 min | High | 15 minutes |
| >95% | 2 min | Critical | Immediate |

---

## Diagnosis Steps

### Step 1: Identify the Affected Resource

```bash
# Get instance details from alarm
aws cloudwatch describe-alarms \
  --alarm-names "AgenticOps-HighCPU-*" \
  --state-value ALARM

# Describe the EC2 instance
aws ec2 describe-instances \
  --instance-ids <instance-id> \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,Tags]'
```

### Step 2: Check CloudWatch Metrics

```bash
# Get CPU metrics for last 30 minutes
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=<instance-id> \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average,Maximum
```

### Step 3: SSH and Investigate Process

```bash
# SSH into instance
ssh -i ~/.ssh/agenticops-key.pem ec2-user@<instance-ip>

# Check top processes by CPU
top -bn1 | head -20

# Check specific process
ps aux --sort=-%cpu | head -10

# Check system load average
uptime

# Check if it's a memory-CPU swap issue
free -m
vmstat 1 5
```

### Step 4: Check Application Logs

```bash
# Check application logs for errors
sudo journalctl -u agenticops-app --since "30 minutes ago" | grep -i error

# Check for OOM killer activity
sudo dmesg | grep -i "out of memory"
sudo dmesg | grep -i "oom_kill"
```

---

## Remediation Actions

### Action 1: Kill Runaway Process (if identified)

```bash
# Identify PID
ps aux | grep <process-name>

# Graceful kill first
kill -15 <PID>

# Force kill if graceful fails after 30 seconds
kill -9 <PID>
```

**Risk:** Data loss possible if process is writing. Confirm with application owner first.

### Action 2: Scale Up Instance (vertical scaling)

```bash
# Stop instance first
aws ec2 stop-instances --instance-ids <instance-id>

# Change instance type
aws ec2 modify-instance-attribute \
  --instance-id <instance-id> \
  --instance-type '{"Value": "t3.xlarge"}'

# Start instance
aws ec2 start-instances --instance-ids <instance-id>
```

**Risk:** ~2–5 minutes downtime. Notify stakeholders before executing.

### Action 3: Scale Out via Auto Scaling (horizontal scaling)

```bash
# Manually trigger scale-out
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name agenticops-asg \
  --desired-capacity <current+2>
```

### Action 4: Restart Application Service

```bash
# Restart systemd service
sudo systemctl restart agenticops-app

# Verify service status
sudo systemctl status agenticops-app
```

---

## Escalation Path

1. **L1 (On-call):** Diagnosis + Action 1 or Action 4
2. **L2 (Senior Engineer):** Action 2 or Action 3
3. **L3 (Architect):** If issue recurs within 24 hours → capacity planning review

---

## Post-Incident

- Update CloudWatch dashboard with incident annotation
- File post-mortem if severity was Critical
- Review Auto Scaling policy thresholds if horizontal scaling was needed
- Update this runbook if new diagnosis steps were discovered

---

## Related Documents

- `postmortem-cpu-spike-jan2025.md`
- `runbook-memory-alarm.md`
- `pipeline-sop-scaling.md`
