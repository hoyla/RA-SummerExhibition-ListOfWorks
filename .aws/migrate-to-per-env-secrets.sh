#!/usr/bin/env bash
# ==========================================================================
# Migrate shared secrets to per-environment secrets
#
# ONE-TIME SCRIPT — run this to fix the staging/prod environment isolation.
#
# Before: Both environments used shared secrets at catalogue/*
# After:  Staging uses catalogue-staging/*, Prod uses catalogue-prod/*
#
# Prerequisites:
#   - aws cli configured for account 028597908565, region eu-north-1
#   - Existing shared secrets: catalogue/DATABASE_URL, catalogue/API_KEY,
#     catalogue/S3_BUCKET
#
# What this script does:
#   1. Creates a new production RDS instance (catalogue-prod)
#   2. Creates per-environment secrets (catalogue-staging/* and catalogue-prod/*)
#   3. Re-registers task definitions for both environments
#   4. Updates both ECS services to use their new task definitions
#
# After running:
#   - Push to any non-main branch → deploys to staging (own DB, own S3)
#   - Push to main → deploys to production (own DB, own S3)
#   - Old shared secrets (catalogue/*) can be deleted once verified
# ==========================================================================

set -euo pipefail

REGION="eu-north-1"
ACCOUNT_ID="028597908565"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  Migrate to per-environment secrets"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. Copy existing shared secrets → staging secrets
# ------------------------------------------------------------------
echo ">>> Step 1: Creating staging secrets from existing shared secrets..."

for SECRET_NAME in DATABASE_URL API_KEY S3_BUCKET; do
    # Read the existing shared value
    EXISTING=$(aws secretsmanager get-secret-value \
        --secret-id "catalogue/$SECRET_NAME" \
        --query 'SecretString' --output text \
        --region "$REGION" --no-cli-pager)

    # For S3_BUCKET, ensure it points to the staging bucket
    if [ "$SECRET_NAME" = "S3_BUCKET" ]; then
        EXISTING="ra-catalogue-staging-$ACCOUNT_ID"
    fi

    # Create the staging secret
    aws secretsmanager create-secret \
        --name "catalogue-staging/$SECRET_NAME" \
        --secret-string "$EXISTING" \
        --region "$REGION" --no-cli-pager 2>/dev/null || \
    aws secretsmanager put-secret-value \
        --secret-id "catalogue-staging/$SECRET_NAME" \
        --secret-string "$EXISTING" \
        --region "$REGION" --no-cli-pager
    echo "    ✓ catalogue-staging/$SECRET_NAME"
done
echo ""

# ------------------------------------------------------------------
# 2. Create production RDS instance
# ------------------------------------------------------------------
echo ">>> Step 2: Creating production RDS instance..."

# Look up the existing RDS security group
RDS_SG=$(aws ec2 describe-security-groups \
    --filters Name=group-name,Values=catalogue-rds-sg \
    --query 'SecurityGroups[0].GroupId' --output text \
    --region "$REGION" --no-cli-pager)

DB_PASSWORD_PROD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

aws rds create-db-instance \
    --db-instance-identifier catalogue-prod \
    --engine postgres \
    --engine-version 16 \
    --db-instance-class db.t4g.micro \
    --allocated-storage 20 \
    --storage-type gp3 \
    --master-username catalogue \
    --master-user-password "$DB_PASSWORD_PROD" \
    --db-name catalogue \
    --vpc-security-group-ids "$RDS_SG" \
    --db-subnet-group-name catalogue-db-subnets \
    --backup-retention-period 7 \
    --no-publicly-accessible \
    --no-multi-az \
    --storage-encrypted \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (instance already exists)"

echo "    Waiting for catalogue-prod to become available..."
echo "    (This may take 5-10 minutes)"
aws rds wait db-instance-available \
    --db-instance-identifier catalogue-prod \
    --region "$REGION" --no-cli-pager

RDS_ENDPOINT_PROD=$(aws rds describe-db-instances \
    --db-instance-identifier catalogue-prod \
    --query 'DBInstances[0].Endpoint.Address' --output text \
    --region "$REGION" --no-cli-pager)

echo "    ✓ catalogue-prod RDS: $RDS_ENDPOINT_PROD"
echo ""

# ------------------------------------------------------------------
# 3. Create production secrets
# ------------------------------------------------------------------
echo ">>> Step 3: Creating production secrets..."

DATABASE_URL_PROD="postgresql://catalogue:${DB_PASSWORD_PROD}@${RDS_ENDPOINT_PROD}:5432/catalogue"
API_KEY_PROD=$(openssl rand -hex 32)
S3_BUCKET_PROD="ra-catalogue-prod-$ACCOUNT_ID"

for SECRET_NAME in DATABASE_URL API_KEY S3_BUCKET; do
    case "$SECRET_NAME" in
        DATABASE_URL) SECRET_VALUE="$DATABASE_URL_PROD" ;;
        API_KEY)      SECRET_VALUE="$API_KEY_PROD" ;;
        S3_BUCKET)    SECRET_VALUE="$S3_BUCKET_PROD" ;;
    esac

    aws secretsmanager create-secret \
        --name "catalogue-prod/$SECRET_NAME" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" --no-cli-pager 2>/dev/null || \
    aws secretsmanager put-secret-value \
        --secret-id "catalogue-prod/$SECRET_NAME" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" --no-cli-pager
    echo "    ✓ catalogue-prod/$SECRET_NAME"
done
echo ""

# ------------------------------------------------------------------
# 4. Update execution role to allow reading new secret paths
# ------------------------------------------------------------------
echo ">>> Step 4: Updating IAM secrets policy..."

cat > /tmp/secrets-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "secretsmanager:GetSecretValue"
    ],
    "Resource": [
      "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:catalogue-staging/*",
      "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:catalogue-prod/*"
    ]
  }]
}
EOF

aws iam put-role-policy \
    --role-name catalogue-ecs-execution \
    --policy-name catalogue-read-secrets \
    --policy-document file:///tmp/secrets-policy.json \
    --no-cli-pager

echo "    ✓ Updated catalogue-ecs-execution secrets policy"
echo ""

# ------------------------------------------------------------------
# 5. Create prod target group + ALB host rule
# ------------------------------------------------------------------
echo ">>> Step 5: Creating prod target group and ALB routing..."

VPC_ID=$(aws ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text \
    --region "$REGION" --no-cli-pager)

TG_ARN_PROD=$(aws elbv2 create-target-group \
    --name catalogue-prod-tg \
    --protocol HTTP --port 8000 \
    --vpc-id "$VPC_ID" \
    --target-type ip \
    --health-check-path /health \
    --health-check-interval-seconds 30 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --region "$REGION" \
    --query 'TargetGroups[0].TargetGroupArn' --output text \
    --no-cli-pager 2>/dev/null || \
    aws elbv2 describe-target-groups \
        --names catalogue-prod-tg \
        --query 'TargetGroups[0].TargetGroupArn' --output text \
        --region "$REGION" --no-cli-pager)

echo "    ✓ Target group: catalogue-prod-tg"

# Update ALB default action to point to prod TG
ALB_ARN=$(aws elbv2 describe-load-balancers \
    --names catalogue-alb \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text \
    --region "$REGION" --no-cli-pager)

LISTENER_ARN=$(aws elbv2 describe-listeners \
    --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[0].ListenerArn' --output text \
    --region "$REGION" --no-cli-pager)

# Default action → prod
aws elbv2 modify-listener \
    --listener-arn "$LISTENER_ARN" \
    --default-actions Type=forward,TargetGroupArn="$TG_ARN_PROD" \
    --region "$REGION" --no-cli-pager > /dev/null

echo "    ✓ Default listener action → prod TG"

# Staging host rule
TG_ARN_STAGING=$(aws elbv2 describe-target-groups \
    --names catalogue-staging-tg \
    --query 'TargetGroups[0].TargetGroupArn' --output text \
    --region "$REGION" --no-cli-pager)

aws elbv2 create-rule \
    --listener-arn "$LISTENER_ARN" \
    --priority 10 \
    --conditions Field=host-header,Values=staging-catalogue.hoy.la \
    --actions Type=forward,TargetGroupArn="$TG_ARN_STAGING" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (staging host rule exists)"

echo "    ✓ Host rule: staging-catalogue.hoy.la → staging TG"
echo ""

# ------------------------------------------------------------------
# 6. Register per-env task definitions + create prod ECS service
# ------------------------------------------------------------------
echo ">>> Step 6: Registering task definitions and creating prod service..."

ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/catalogue-app"

for ENV in staging prod; do
    TASK_DEF_CONTENT=$(cat "$SCRIPT_DIR/task-definition-${ENV}.json" \
        | sed "s|PLACEHOLDER|$ECR_URI:latest|g")

    echo "$TASK_DEF_CONTENT" > "/tmp/task-def-${ENV}-resolved.json"

    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --cli-input-json "file:///tmp/task-def-${ENV}-resolved.json" \
        --region "$REGION" \
        --query 'taskDefinition.taskDefinitionArn' --output text \
        --no-cli-pager)

    echo "    ✓ Task definition (${ENV}): $TASK_DEF_ARN"
done

# Update staging service to use new task family
aws ecs update-service \
    --cluster catalogue \
    --service catalogue-staging \
    --task-definition catalogue-staging \
    --region "$REGION" --no-cli-pager > /dev/null

echo "    ✓ Updated staging service → catalogue-staging task def"

# Look up subnets and security group for prod service
SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
    --query 'Subnets[*].SubnetId' --output text \
    --region "$REGION" --no-cli-pager)
SUBNET_1=$(echo "$SUBNET_IDS" | awk '{print $1}')
SUBNET_2=$(echo "$SUBNET_IDS" | awk '{print $2}')

ECS_SG=$(aws ec2 describe-security-groups \
    --filters Name=group-name,Values=catalogue-ecs-sg Name=vpc-id,Values="$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text \
    --region "$REGION" --no-cli-pager)

# Create prod service
aws ecs create-service \
    --cluster catalogue \
    --service-name catalogue-prod \
    --task-definition catalogue-prod \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=$TG_ARN_PROD,containerName=app,containerPort=8000" \
    --region "$REGION" --no-cli-pager 2>/dev/null || \
aws ecs update-service \
    --cluster catalogue \
    --service catalogue-prod \
    --task-definition catalogue-prod \
    --region "$REGION" --no-cli-pager > /dev/null

echo "    ✓ ECS service: catalogue-prod"
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "============================================"
echo "  ✅  Migration Complete!"
echo "============================================"
echo ""
echo "  Staging:"
echo "    RDS:      catalogue-staging (unchanged)"
echo "    S3:       ra-catalogue-staging-$ACCOUNT_ID"
echo "    Secrets:  catalogue-staging/{DATABASE_URL,API_KEY,S3_BUCKET}"
echo "    DNS:      staging-catalogue.hoy.la"
echo ""
echo "  Production:"
echo "    RDS:      catalogue-prod (NEW — empty database)"
echo "    S3:       ra-catalogue-prod-$ACCOUNT_ID"
echo "    Secrets:  catalogue-prod/{DATABASE_URL,API_KEY,S3_BUCKET}"
echo "    DNS:      catalogue.hoy.la"
echo ""
echo "  Production API Key:"
echo "    $API_KEY_PROD"
echo ""
echo "  Next steps:"
echo "    1. Verify staging works: https://staging-catalogue.hoy.la"
echo "    2. Merge to main to deploy prod with new config"
echo "    3. Re-upload production data (prod DB is fresh)"
echo "    4. Once verified, delete old shared secrets:"
echo "       aws secretsmanager delete-secret --secret-id catalogue/DATABASE_URL"
echo "       aws secretsmanager delete-secret --secret-id catalogue/API_KEY"
echo "       aws secretsmanager delete-secret --secret-id catalogue/S3_BUCKET"
echo ""

rm -f /tmp/secrets-policy.json /tmp/task-def-staging-resolved.json \
      /tmp/task-def-prod-resolved.json
