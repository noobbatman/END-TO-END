# AWS ECS Fargate Deployment Guide

This repo is ready to run on ECS Fargate with:

- `api` service behind an ALB
- `worker`, `worker-high`, and `worker-webhooks` Celery services
- S3 for uploads/exports
- RDS PostgreSQL
- ElastiCache Redis

The repo now includes two PowerShell scripts for the repeatable part of deployment:

- `aws/render-task-definitions.ps1`
- `aws/deploy-fargate.ps1`

This guide keeps the one-time AWS infrastructure steps separate from the app deployment/update steps.

## 1. One-Time AWS Prerequisites

Create these resources once:

- ECR repository: `docintel`
- ECS cluster: `docintel`
- RDS PostgreSQL instance
- ElastiCache Redis
- S3 buckets for uploads and exports
- ALB target group for the API on port `8000`
- Security groups for API and workers
- Private subnets for ECS tasks
- IAM roles:
  - `ecsTaskExecutionRole`
  - `ecsTaskRole`
- Secrets Manager secrets:
  - `docintel/database-url`
  - `docintel/redis-broker`
  - `docintel/redis-backend`
  - `docintel/api-keys`
  - `docintel/webhook-secret`
  - optional: `docintel/anthropic-api-key`
  - optional: `docintel/email-address`
  - optional: `docintel/email-password`

Recommended secret values:

- `docintel/database-url`
  - plain string like `postgresql+psycopg://postgres:password@your-rds-endpoint:5432/docintel`
- `docintel/redis-broker`
  - plain string like `redis://your-redis-endpoint:6379/0`
- `docintel/redis-backend`
  - plain string like `redis://your-redis-endpoint:6379/1`
- `docintel/api-keys`
  - plain string like `prod-key-1,prod-key-2`

Important:

- These secrets should be stored as plain strings.
- The ECS task definitions now inject the whole secret ARN directly.
- You do not need JSON-key selectors in Secrets Manager for this repo.

## 2. Render Task Definitions

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\aws\render-task-definitions.ps1 `
  -Region us-east-1 `
  -AccountId 123456789012
```

Rendered files are written to `aws/rendered/`.

Defaults:

- ECR image: `123456789012.dkr.ecr.us-east-1.amazonaws.com/docintel:latest`
- uploads bucket: `docintel-uploads-123456789012`
- exports bucket: `docintel-exports-123456789012`
- IAM roles:
  - `ecsTaskExecutionRole`
  - `ecsTaskRole`

To include the optional review UI:

```powershell
powershell -ExecutionPolicy Bypass -File .\aws\render-task-definitions.ps1 `
  -Region us-east-1 `
  -AccountId 123456789012 `
  -IncludeReviewUi `
  -ReviewApiBase https://your-alb-dns/api/v1
```

## 3. Build, Push, Register, and Update ECS

If the cluster, target group, subnets, and security groups already exist, use the end-to-end deployment script:

```powershell
powershell -ExecutionPolicy Bypass -File .\aws\deploy-fargate.ps1 `
  -Region us-east-1 `
  -AccountId 123456789012 `
  -EnsureCluster `
  -CreateServices `
  -WaitForStability `
  -RunMigrations `
  -PrivateSubnets subnet-aaa,subnet-bbb `
  -ApiSecurityGroup sg-api `
  -WorkerSecurityGroup sg-worker `
  -ApiTargetGroupArn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/docintel-api/abc123
```

What the script does:

1. Logs in to ECR
2. Builds the Docker image
3. Pushes both `:<timestamp>` and `:latest`
4. Renders task definitions with resolved role ARNs and secret ARNs
5. Registers the ECS task definitions
6. Creates or updates the ECS services
7. Waits for service stability if requested
8. Runs `alembic upgrade head` as a one-off Fargate task if requested

If services already exist and you only want to roll out a new image:

```powershell
powershell -ExecutionPolicy Bypass -File .\aws\deploy-fargate.ps1 `
  -Region us-east-1 `
  -AccountId 123456789012 `
  -UpdateServices `
  -WaitForStability `
  -PrivateSubnets subnet-aaa,subnet-bbb `
  -ApiSecurityGroup sg-api `
  -WorkerSecurityGroup sg-worker `
  -ApiTargetGroupArn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/docintel-api/abc123
```

## 4. Optional Review UI Deployment

The review UI is optional and needs its own target group on port `8501`.

Example:

```powershell
powershell -ExecutionPolicy Bypass -File .\aws\deploy-fargate.ps1 `
  -Region us-east-1 `
  -AccountId 123456789012 `
  -CreateServices `
  -IncludeReviewUi `
  -ReviewApiBase https://your-alb-dns/api/v1 `
  -PrivateSubnets subnet-aaa,subnet-bbb `
  -ApiSecurityGroup sg-api `
  -WorkerSecurityGroup sg-worker `
  -ReviewUiSecurityGroup sg-api `
  -ApiTargetGroupArn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/docintel-api/abc123 `
  -ReviewUiTargetGroupArn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/docintel-review/def456
```

## 5. Verify the Deployment

Check ECS services:

```powershell
aws ecs describe-services `
  --cluster docintel `
  --services docintel-api docintel-worker docintel-worker-high docintel-worker-webhooks `
  --region us-east-1 `
  --query "services[*].[serviceName,desiredCount,runningCount,status]" `
  --output table
```

Check the API health endpoint:

```powershell
curl.exe -H "X-API-Key: prod-key-1" http://your-alb-dns/api/v1/health/ready
```

Check logs:

```powershell
aws logs tail /ecs/docintel-api --follow --region us-east-1
aws logs tail /ecs/docintel-worker --follow --region us-east-1
```

## 6. Notes About This Repo

- The readiness probe now returns HTTP `503` when the database is unavailable.
- Worker task definitions now use `app.workers.celery_app.celery_app`, which matches the actual Celery app object.
- Review UI tasks require `REVIEW_API_BASE`; the old local default `http://api:8000/api/v1` is not valid across ECS services.
- Optional secrets are removed from rendered task definitions if the secret does not exist.

## 7. Cheapest Practical Starting Point

For a small first deployment:

- API: `1 vCPU / 2 GB`
- Worker: `1 vCPU / 2 GB`
- Worker-high: `1 vCPU / 2 GB`
- Worker-webhooks: `0.5 vCPU / 1 GB`
- RDS: `db.t3.micro`
- Redis: `cache.t3.micro`

Start there, then scale based on CloudWatch CPU, memory, queue depth, and request volume.
