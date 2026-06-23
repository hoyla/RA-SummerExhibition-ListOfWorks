# Mothball & Restore — Production

This tool is used for a couple of weeks a year. The rest of the time the
production stack can be torn down to near-zero cost and rebuilt intact when the
next exhibition comes round. This is the runbook; the two scripts
(`.aws/mothball-prod.sh`, `.aws/restore-prod.sh`) automate it.

- **Region / account:** `eu-north-1` / `028597908565`
- **Related:** [`staging-rebuild-checklist.md`](staging-rebuild-checklist.md) (staging
  was torn down in April 2026 the same way), [`.aws/setup-infrastructure.sh`](../.aws/setup-infrastructure.sh)
  (the original full build).

## What costs money, and what doesn't

No NAT gateways, so the only year-round costs are three resources:

| Resource | ~Monthly | Mothball action |
|---|---|---|
| ALB `catalogue-alb` | ~£15–18 | Delete → recreate on restore |
| Fargate task (256/512, desired=1) | ~£8–10 | Delete service |
| RDS `catalogue-prod` (t4g.micro, 20 GB) | ~£13 | Final snapshot → delete |
| **Running total** | **~£40/mo (~£480/yr)** | |

Everything that holds **state** is cheap or free and is **left in place**, which
is what makes the restore lossless:

- **S3** `ra-catalogue-prod-028597908565` — uploaded files + versioning (pennies)
- **The final RDS snapshot** — this *is* the database, frozen (cents/mo)
- **Cognito user pool** — free under 50k monthly users, so every account survives
- **Secrets Manager** `catalogue-prod/{DATABASE_URL,API_KEY,S3_BUCKET}` (~£1/mo)
- **ECR image, IAM roles, security groups, subnet group, CloudWatch log group** — free

**Mothballed cost: ~£1.50–2/mo (~£20/yr).** Saving ≈ **£460/yr**.

## The two wrinkles (already handled by the scripts)

1. **RDS comes back from a snapshot, not a fresh create.** `setup-infrastructure.sh`
   would create an *empty* DB with a *new* password. `restore-prod.sh` instead
   restores the snapshot (data + original password intact) and then repoints the
   retained `DATABASE_URL` secret at the new endpoint hostname (the
   `…cjc8si80mtkh…` token is per-instance and changes each rebuild).
2. **The ALB URL changes** on each rebuild (new `catalogue-alb-NNN….elb.amazonaws.com`).
   There's no Route53 zone, so just note the new URL printed at the end of
   `restore-prod.sh` and re-share it. (If you ever want a stable URL, add a
   ~£0.40/mo hosted zone with an alias to the ALB and re-point it on restore.)

## Mothball (end of season)

From the project root:

```bash
./.aws/mothball-prod.sh
```

It will:
1. Take a snapshot `catalogue-prod-mothball-YYYYMMDD-HHMMSS` (timestamped per run,
   so a re-run never reuses a stale earlier snapshot) and **wait until it is
   `available`** — if the snapshot fails, it aborts *before* deleting anything.
2. Delete the ECS service (cluster + task definitions kept).
3. Delete the ALB, then its target group.
4. Delete the RDS instance (`--skip-final-snapshot`, because step 1 already made one).

**Record the snapshot id** it prints — that's all `restore-prod.sh` needs (it can
also auto-detect the newest one). Then optionally check for orphaned Elastic IPs
(unattached ones bill ~£3/mo each):

```bash
aws ec2 describe-addresses --region eu-north-1 \
  --query 'Addresses[?AssociationId==`null`].PublicIp'
```

## Restore (a day before the next exhibition)

From the project root:

```bash
./.aws/restore-prod.sh                       # uses newest mothball snapshot
# or pin one explicitly:
./.aws/restore-prod.sh catalogue-prod-mothball-20260801-031500
```

It will:
1. Restore RDS from the snapshot and wait until available.
2. Repoint `catalogue-prod/DATABASE_URL` at the new endpoint.
3. Re-register the prod task definition (image `…/catalogue-app:latest` from ECR).
4. Recreate the ALB, target group, and HTTP:80 listener.
5. Create the ECS service (desired=1) wired to the target group.

It prints the new app URL. Give it a few minutes to pass health checks. The app
runs Alembic migrations on boot, which is a no-op against the restored data.

**Before restoring, confirm an image exists in ECR** (it normally persists):

```bash
aws ecr describe-images --repository-name catalogue-app \
  --image-ids imageTag=latest --region eu-north-1 >/dev/null && echo "image OK"
```

If it's gone, push one first via the normal CI/deploy path.

## Verify after restore

```bash
# Task healthy and stable?
aws ecs describe-services --cluster catalogue --services catalogue-prod \
  --query 'services[0].{running:runningCount,desired:desiredCount}' --region eu-north-1
# Target healthy in the ALB?
aws elbv2 describe-target-health \
  --target-group-arn "$(aws elbv2 describe-target-groups --names catalogue-prod-tg \
     --query 'TargetGroups[0].TargetGroupArn' --output text --region eu-north-1)" \
  --region eu-north-1 --query 'TargetHealthDescriptions[].TargetHealth.State'
```

Then open the printed URL and log in — Cognito accounts and all data should be
exactly as they were.

## Safety notes

- The mothball script is **snapshot-first, verify, then delete** — it will not
  delete the database without a confirmed-available snapshot.
- S3 data and Cognito users are never touched by either script.
- Both scripts are re-runnable: existing resources are detected and skipped.
- Manual snapshots persist until explicitly deleted (unlike the 7-day automated
  ones), so a mothball snapshot is safe to leave for the full off-season. Delete
  old ones once a season is successfully restored:
  `aws rds delete-db-snapshot --db-snapshot-identifier <id>`.
