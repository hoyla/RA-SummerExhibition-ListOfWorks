#!/usr/bin/env bash
# ==========================================================================
# Catalogue Tool — Restore PRODUCTION from a mothball snapshot
#
# Reverses mothball-prod.sh: restores the RDS instance from a snapshot, repoints
# the DATABASE_URL secret at the new endpoint, then recreates the ALB, target
# group, listener, and ECS service. S3 files, Cognito users, secrets, and the
# ECR image were never deleted, so they come back as they were.
#
# Usage:
#   ./.aws/restore-prod.sh [snapshot-id]
# If no snapshot id is given, the newest 'catalogue-prod-mothball-*' is used.
#
# Prerequisites: aws cli configured, account 028597908565, region eu-north-1.
# Run from the project root (needs .aws/task-definition-prod.json).
# ==========================================================================

set -euo pipefail

REGION="eu-north-1"
ACCOUNT_ID="028597908565"
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/catalogue-app"
export AWS_PAGER=""

[ -f .aws/task-definition-prod.json ] || {
    echo "ERROR: run from the project root (.aws/task-definition-prod.json not found)."
    exit 1
}

# --------------------------------------------------------------------------
# Resolve the snapshot
# --------------------------------------------------------------------------
SNAPSHOT_ID="${1:-}"
if [ -z "$SNAPSHOT_ID" ]; then
    SNAPSHOT_ID=$(aws rds describe-db-snapshots --snapshot-type manual \
        --query "reverse(sort_by(DBSnapshots[?starts_with(DBSnapshotIdentifier,'catalogue-prod-mothball')],&SnapshotCreateTime))[0].DBSnapshotIdentifier" \
        --output text --region "$REGION")
fi
[ -n "$SNAPSHOT_ID" ] && [ "$SNAPSHOT_ID" != "None" ] || {
    echo "ERROR: no mothball snapshot found. Pass one explicitly:"
    echo "  ./.aws/restore-prod.sh <snapshot-id>"
    exit 1
}

echo "============================================"
echo "  Catalogue — Restore PRODUCTION"
echo "  Snapshot: $SNAPSHOT_ID"
echo "============================================"
echo ""

# Warn early if there's no image to run (it normally persists in ECR).
aws ecr describe-images --repository-name catalogue-app \
    --image-ids imageTag=latest --region "$REGION" >/dev/null 2>&1 \
    || echo "  ⚠  No ':latest' image in ECR — deploy one (CI / docker push) before tasks will start."

# --------------------------------------------------------------------------
# Look up shared networking (created once by setup-infrastructure.sh)
# --------------------------------------------------------------------------
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text --region "$REGION")
SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
    --query 'Subnets[*].SubnetId' --output text --region "$REGION")
SUBNET_1=$(echo "$SUBNET_IDS" | awk '{print $1}')
SUBNET_2=$(echo "$SUBNET_IDS" | awk '{print $2}')

sg() { aws ec2 describe-security-groups \
    --filters Name=group-name,Values="$1" Name=vpc-id,Values="$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text --region "$REGION"; }
ALB_SG=$(sg catalogue-alb-sg)
ECS_SG=$(sg catalogue-ecs-sg)
RDS_SG=$(sg catalogue-rds-sg)

# --------------------------------------------------------------------------
# 1. Restore RDS from the snapshot
# --------------------------------------------------------------------------
echo ">>> 1/5  Restoring RDS catalogue-prod from $SNAPSHOT_ID ..."
if aws rds describe-db-instances --db-instance-identifier catalogue-prod \
        --region "$REGION" >/dev/null 2>&1; then
    # Reusing an existing instance — flag it loudly with its create time so a
    # leftover from an interrupted/earlier restore isn't silently adopted as
    # though it were the snapshot we were asked to restore.
    EXISTING_CREATED=$(aws rds describe-db-instances --db-instance-identifier catalogue-prod \
        --query 'DBInstances[0].InstanceCreateTime' --output text --region "$REGION" 2>/dev/null || echo "unknown")
    echo "    ⚠  catalogue-prod already exists (created $EXISTING_CREATED) — skipping restore."
    echo "       If that's a leftover rather than the DB you want, delete it and re-run"
    echo "       to restore from $SNAPSHOT_ID."
else
    aws rds restore-db-instance-from-db-snapshot \
        --db-instance-identifier catalogue-prod \
        --db-snapshot-identifier "$SNAPSHOT_ID" \
        --db-instance-class db.t4g.micro \
        --db-subnet-group-name catalogue-db-subnets \
        --vpc-security-group-ids "$RDS_SG" \
        --no-publicly-accessible \
        --no-multi-az \
        --region "$REGION" --no-cli-pager >/dev/null
fi
echo "    Waiting for RDS to become available (5-10 min)..."
aws rds wait db-instance-available --db-instance-identifier catalogue-prod \
    --region "$REGION"
RDS_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier catalogue-prod \
    --query 'DBInstances[0].Endpoint.Address' --output text --region "$REGION")
echo "    ✓ RDS available: $RDS_ENDPOINT"
echo ""

# --------------------------------------------------------------------------
# 2. Repoint DATABASE_URL at the new endpoint (password is unchanged, so it is
#    still correct in the retained secret — only the host moved)
# --------------------------------------------------------------------------
echo ">>> 2/5  Updating catalogue-prod/DATABASE_URL endpoint ..."
OLD_URL=$(aws secretsmanager get-secret-value --secret-id catalogue-prod/DATABASE_URL \
    --query SecretString --output text --region "$REGION")
NEW_URL=$(echo "$OLD_URL" | sed -E "s#@[^/]+/#@${RDS_ENDPOINT}:5432/#")
# Guard: only write a value that actually points at the new host. If the secret's
# URL shape didn't match the sed (so the dead endpoint would survive), stop rather
# than silently persist a broken DATABASE_URL. (Passes idempotent re-runs, where
# the secret already contains the current endpoint.)
case "$NEW_URL" in
    *"@${RDS_ENDPOINT}:5432/"*) : ;;
    *) echo "    ERROR: DATABASE_URL rewrite did not produce the new endpoint ($RDS_ENDPOINT)."
       echo "    Refusing to write a possibly-broken secret — fix it manually and re-run."
       exit 1 ;;
esac
aws secretsmanager put-secret-value --secret-id catalogue-prod/DATABASE_URL \
    --secret-string "$NEW_URL" --region "$REGION" --no-cli-pager >/dev/null
echo "    ✓ Secret repointed."
echo ""

# --------------------------------------------------------------------------
# 3. Ensure cluster + register the task definition
# --------------------------------------------------------------------------
echo ">>> 3/5  Registering task definition ..."
aws ecs create-cluster --cluster-name catalogue --region "$REGION" \
    --no-cli-pager >/dev/null 2>&1 || true
sed "s|PLACEHOLDER|$ECR_URI:latest|g" .aws/task-definition-prod.json \
    > /tmp/task-def-prod-resolved.json
aws ecs register-task-definition --cli-input-json file:///tmp/task-def-prod-resolved.json \
    --region "$REGION" --no-cli-pager >/dev/null
echo "    ✓ Task definition registered."
echo ""

# --------------------------------------------------------------------------
# 4. Recreate ALB + target group + listener
# --------------------------------------------------------------------------
echo ">>> 4/5  Recreating ALB + target group + listener ..."
ALB_ARN=$(aws elbv2 create-load-balancer --name catalogue-alb \
    --subnets "$SUBNET_1" "$SUBNET_2" --security-groups "$ALB_SG" \
    --scheme internet-facing --type application \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text \
    --region "$REGION" --no-cli-pager 2>/dev/null \
    || aws elbv2 describe-load-balancers --names catalogue-alb \
        --query 'LoadBalancers[0].LoadBalancerArn' --output text --region "$REGION")

TG_ARN=$(aws elbv2 create-target-group --name catalogue-prod-tg \
    --protocol HTTP --port 8000 --vpc-id "$VPC_ID" --target-type ip \
    --health-check-path /health --health-check-interval-seconds 30 \
    --healthy-threshold-count 2 --unhealthy-threshold-count 3 \
    --query 'TargetGroups[0].TargetGroupArn' --output text \
    --region "$REGION" --no-cli-pager 2>/dev/null \
    || aws elbv2 describe-target-groups --names catalogue-prod-tg \
        --query 'TargetGroups[0].TargetGroupArn' --output text --region "$REGION")

LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[0].ListenerArn' --output text --region "$REGION" 2>/dev/null || echo "None")
if [ "$LISTENER_ARN" = "None" ] || [ -z "$LISTENER_ARN" ]; then
    aws elbv2 create-listener --load-balancer-arn "$ALB_ARN" \
        --protocol HTTP --port 80 \
        --default-actions Type=forward,TargetGroupArn="$TG_ARN" \
        --region "$REGION" --no-cli-pager >/dev/null
fi
ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
    --query 'LoadBalancers[0].DNSName' --output text --region "$REGION")
echo "    ✓ ALB ready."
echo ""

# --------------------------------------------------------------------------
# 5. Create the ECS service
# --------------------------------------------------------------------------
echo ">>> 5/5  Creating ECS service catalogue-prod ..."
aws ecs create-service \
    --cluster catalogue \
    --service-name catalogue-prod \
    --task-definition catalogue-prod \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=$TG_ARN,containerName=app,containerPort=8000" \
    --region "$REGION" --no-cli-pager >/dev/null 2>&1 \
    || aws ecs update-service --cluster catalogue --service catalogue-prod \
        --task-definition catalogue-prod --desired-count 1 \
        --region "$REGION" --no-cli-pager >/dev/null
echo "    ✓ Service starting."
echo ""

echo "============================================"
echo "  ✅  Production restored."
echo "============================================"
echo ""
echo "  App URL:  http://$ALB_DNS"
echo ""
echo "  Give it a few minutes for the task to start and pass health checks."
echo "  The app runs Alembic migrations on boot — a no-op against restored data."
echo "  Watch rollout:"
echo "    aws ecs describe-services --cluster catalogue --services catalogue-prod \\"
echo "      --query 'services[0].deployments' --region $REGION"
