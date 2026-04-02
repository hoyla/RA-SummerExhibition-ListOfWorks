# Catalogue Staging — Rebuild Checklist

If staging needs to be recreated, here's what existed and how to rebuild it.

## Region / Account
- **Region**: eu-north-1
- **Account**: 028597908565

## Resources that were torn down (April 2026)

### ECS
- **Cluster**: `catalogue` (shared with prod — NOT deleted)
- **Service**: `catalogue-staging` (deleted)
- **Task definition family**: `catalogue-staging`

### RDS
- **Instance**: `catalogue-staging` (db.t4g.micro, Postgres 16, 20 GB gp3)
- **DB name**: `catalogue`, **user**: `catalogue`
- **Subnet group**: `catalogue-db-subnets` (shared — NOT deleted)
- **Security group**: `catalogue-rds-sg` (shared — NOT deleted)

### Secrets Manager
- `catalogue-staging/DATABASE_URL`
- `catalogue-staging/API_KEY`
- `catalogue-staging/S3_BUCKET`

### S3 Bucket
- `ra-catalogue-staging-028597908565` (versioned, private)

### ALB
- **ALB name**: `catalogue-alb` (shared — NOT deleted)
- **Listener rule**: host-based rule routing to staging target group (deleted)
- **Target group**: `catalogue-staging-tg` (deleted)

### Task Definition Config (deleted from repo)
- Was at `.aws/task-definition-staging.json`
- Container: `app`, port 8000, Fargate 256 CPU / 512 MB
- Env vars: LOG_LEVEL=INFO, STORAGE_BACKEND=s3, ENVIRONMENT=staging
- Cognito: pool `eu-north-1_ThfApt8C5`, client `2n4pj4j9l45oj25i0t7sn3dko8`
- Logs: `/ecs/catalogue-app` prefix `staging`

### CI/CD
- GitHub Actions workflow had `deploy-staging` job (non-main branches)
- Used GitHub environment: `staging`
- ECR pushes happened on all branch pushes (not just main)

## To Rebuild
1. Re-create RDS instance (see `.aws/setup-infrastructure.sh` step 6)
2. Re-create Secrets Manager entries (DATABASE_URL, API_KEY, S3_BUCKET)
3. Re-create S3 bucket with versioning + block public access
4. Re-create ECS service + target group + ALB listener rule
5. Re-create `.aws/task-definition-staging.json` (use prod as template, change family/env/secrets)
6. Re-add `deploy-staging` job to `.github/workflows/ci.yml`
7. Re-add `staging` environment in GitHub repo settings
8. Restore ECR push for all branches (not just main)
