#!/usr/bin/env bash
# ==========================================================================
# Catalogue Tool — AWS Infrastructure Setup
#
# Run this script step-by-step from the project root.
# Prerequisites: aws cli configured, account 028597908565, region eu-north-1
#
# What it creates:
#   1. ECR repository
#   2. S3 buckets (staging + prod)
#   3. CloudWatch log group
#   4. VPC + subnets (or use default VPC)
#   5. RDS PostgreSQL (staging + prod)
#   6. ECS cluster + services (staging + prod)
#   7. IAM roles (task execution, task, GitHub Actions deploy)
#   8. GitHub OIDC provider
#   9. Secrets Manager entries (per-environment)
#  10. Application Load Balancer (host-based routing)
# ==========================================================================

set -euo pipefail

REGION="eu-north-1"
ACCOUNT_ID="028597908565"
PROJECT="catalogue"
GITHUB_REPO="hoyla/RA-SummerExhibition-ListOfWorks"

echo "============================================"
echo "  Catalogue Tool — AWS Setup"
echo "  Account: $ACCOUNT_ID  Region: $REGION"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. ECR Repository
# ------------------------------------------------------------------
echo ">>> 1/10  Creating ECR repository..."
aws ecr create-repository \
    --repository-name catalogue-app \
    --region "$REGION" \
    --image-scanning-configuration scanOnPush=true \
    --no-cli-pager 2>/dev/null || echo "    (already exists)"

ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/catalogue-app"
echo "    ECR URI: $ECR_URI"
echo ""

# ------------------------------------------------------------------
# 2. S3 Buckets
# ------------------------------------------------------------------
echo ">>> 2/10  Creating S3 buckets..."
for ENV in staging prod; do
    BUCKET="ra-catalogue-${ENV}-${ACCOUNT_ID}"
    aws s3api create-bucket \
        --bucket "$BUCKET" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION" \
        --no-cli-pager 2>/dev/null || echo "    $BUCKET (already exists)"

    # Block public access
    aws s3api put-public-access-block \
        --bucket "$BUCKET" \
        --public-access-block-configuration \
            BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
        --region "$REGION" \
        --no-cli-pager

    # Enable versioning for safety
    aws s3api put-bucket-versioning \
        --bucket "$BUCKET" \
        --versioning-configuration Status=Enabled \
        --region "$REGION" \
        --no-cli-pager

    echo "    ✓ $BUCKET"
done
echo ""

# ------------------------------------------------------------------
# 3. CloudWatch Log Group
# ------------------------------------------------------------------
echo ">>> 3/10  Creating CloudWatch log group..."
aws logs create-log-group \
    --log-group-name /ecs/catalogue-app \
    --region "$REGION" \
    --no-cli-pager 2>/dev/null || echo "    (already exists)"

aws logs put-retention-policy \
    --log-group-name /ecs/catalogue-app \
    --retention-in-days 30 \
    --region "$REGION" \
    --no-cli-pager
echo "    ✓ /ecs/catalogue-app (30 day retention)"
echo ""

# ------------------------------------------------------------------
# 4. VPC — use default VPC
# ------------------------------------------------------------------
echo ">>> 4/10  Looking up default VPC..."
VPC_ID=$(aws ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text \
    --region "$REGION" --no-cli-pager)

if [ "$VPC_ID" = "None" ] || [ -z "$VPC_ID" ]; then
    echo "    ERROR: No default VPC found. Create one with: aws ec2 create-default-vpc"
    exit 1
fi

SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
    --query 'Subnets[*].SubnetId' --output text \
    --region "$REGION" --no-cli-pager)

# Pick first two subnets for ALB (needs 2 AZs)
SUBNET_1=$(echo "$SUBNET_IDS" | awk '{print $1}')
SUBNET_2=$(echo "$SUBNET_IDS" | awk '{print $2}')

echo "    VPC: $VPC_ID"
echo "    Subnets: $SUBNET_1, $SUBNET_2"
echo ""

# ------------------------------------------------------------------
# 5. Security Groups
# ------------------------------------------------------------------
echo ">>> 5/10  Creating security groups..."

# ALB security group — allows HTTP from anywhere
ALB_SG=$(aws ec2 create-security-group \
    --group-name catalogue-alb-sg \
    --description "Catalogue ALB - HTTP inbound" \
    --vpc-id "$VPC_ID" \
    --region "$REGION" \
    --query 'GroupId' --output text \
    --no-cli-pager 2>/dev/null || \
    aws ec2 describe-security-groups \
        --filters Name=group-name,Values=catalogue-alb-sg Name=vpc-id,Values="$VPC_ID" \
        --query 'SecurityGroups[0].GroupId' --output text \
        --region "$REGION" --no-cli-pager)

aws ec2 authorize-security-group-ingress \
    --group-id "$ALB_SG" \
    --protocol tcp --port 80 --cidr 0.0.0.0/0 \
    --region "$REGION" --no-cli-pager 2>/dev/null || true

echo "    ALB SG: $ALB_SG"

# ECS tasks security group — allows traffic from ALB only
ECS_SG=$(aws ec2 create-security-group \
    --group-name catalogue-ecs-sg \
    --description "Catalogue ECS tasks - ALB inbound only" \
    --vpc-id "$VPC_ID" \
    --region "$REGION" \
    --query 'GroupId' --output text \
    --no-cli-pager 2>/dev/null || \
    aws ec2 describe-security-groups \
        --filters Name=group-name,Values=catalogue-ecs-sg Name=vpc-id,Values="$VPC_ID" \
        --query 'SecurityGroups[0].GroupId' --output text \
        --region "$REGION" --no-cli-pager)

aws ec2 authorize-security-group-ingress \
    --group-id "$ECS_SG" \
    --protocol tcp --port 8000 --source-group "$ALB_SG" \
    --region "$REGION" --no-cli-pager 2>/dev/null || true

echo "    ECS SG: $ECS_SG"

# RDS security group — allows Postgres from ECS tasks
RDS_SG=$(aws ec2 create-security-group \
    --group-name catalogue-rds-sg \
    --description "Catalogue RDS - ECS inbound only" \
    --vpc-id "$VPC_ID" \
    --region "$REGION" \
    --query 'GroupId' --output text \
    --no-cli-pager 2>/dev/null || \
    aws ec2 describe-security-groups \
        --filters Name=group-name,Values=catalogue-rds-sg Name=vpc-id,Values="$VPC_ID" \
        --query 'SecurityGroups[0].GroupId' --output text \
        --region "$REGION" --no-cli-pager)

aws ec2 authorize-security-group-ingress \
    --group-id "$RDS_SG" \
    --protocol tcp --port 5432 --source-group "$ECS_SG" \
    --region "$REGION" --no-cli-pager 2>/dev/null || true

echo "    RDS SG: $RDS_SG"
echo ""

# ------------------------------------------------------------------
# 6. RDS PostgreSQL (staging + prod — separate instances)
# ------------------------------------------------------------------
echo ">>> 6/10  Creating RDS PostgreSQL instances..."

DB_PASSWORD_STAGING=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
DB_PASSWORD_PROD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

# Create DB subnet group
aws rds create-db-subnet-group \
    --db-subnet-group-name catalogue-db-subnets \
    --db-subnet-group-description "Catalogue DB subnets" \
    --subnet-ids "$SUBNET_1" "$SUBNET_2" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (subnet group exists)"

for ENV in staging prod; do
    DB_CLASS="db.t4g.micro"
    if [ "$ENV" = "prod" ]; then
        DB_PASSWORD="$DB_PASSWORD_PROD"
    else
        DB_PASSWORD="$DB_PASSWORD_STAGING"
    fi

    aws rds create-db-instance \
        --db-instance-identifier "catalogue-${ENV}" \
        --engine postgres \
        --engine-version 16 \
        --db-instance-class "$DB_CLASS" \
        --allocated-storage 20 \
        --storage-type gp3 \
        --master-username catalogue \
        --master-user-password "$DB_PASSWORD" \
        --db-name catalogue \
        --vpc-security-group-ids "$RDS_SG" \
        --db-subnet-group-name catalogue-db-subnets \
        --backup-retention-period 7 \
        --no-publicly-accessible \
        --no-multi-az \
        --storage-encrypted \
        --region "$REGION" --no-cli-pager 2>/dev/null || echo "    catalogue-${ENV} (instance exists)"

    echo "    ✓ catalogue-${ENV} (${DB_CLASS}, Postgres 16)"
done
echo "    DB passwords saved to Secrets Manager in step 9"
echo ""

# ------------------------------------------------------------------
# 7. IAM Roles
# ------------------------------------------------------------------
echo ">>> 7/10  Creating IAM roles..."

# 7a. ECS task execution role (pulls images, reads secrets)
cat > /tmp/ecs-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

EXEC_ROLE_ARN=$(aws iam create-role \
    --role-name catalogue-ecs-execution \
    --assume-role-policy-document file:///tmp/ecs-trust.json \
    --query 'Role.Arn' --output text \
    --no-cli-pager 2>/dev/null || \
    aws iam get-role --role-name catalogue-ecs-execution \
        --query 'Role.Arn' --output text --no-cli-pager)

aws iam attach-role-policy \
    --role-name catalogue-ecs-execution \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy \
    --no-cli-pager 2>/dev/null || true

# Allow reading secrets (both environments)
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

echo "    ✓ catalogue-ecs-execution: $EXEC_ROLE_ARN"

# 7b. ECS task role (the app's own permissions — S3 access)
TASK_ROLE_ARN=$(aws iam create-role \
    --role-name catalogue-ecs-task \
    --assume-role-policy-document file:///tmp/ecs-trust.json \
    --query 'Role.Arn' --output text \
    --no-cli-pager 2>/dev/null || \
    aws iam get-role --role-name catalogue-ecs-task \
        --query 'Role.Arn' --output text --no-cli-pager)

cat > /tmp/s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:ListBucket", "s3:HeadObject"
    ],
    "Resource": [
      "arn:aws:s3:::ra-catalogue-staging-$ACCOUNT_ID",
      "arn:aws:s3:::ra-catalogue-staging-$ACCOUNT_ID/*",
      "arn:aws:s3:::ra-catalogue-prod-$ACCOUNT_ID",
      "arn:aws:s3:::ra-catalogue-prod-$ACCOUNT_ID/*"
    ]
  }]
}
EOF

aws iam put-role-policy \
    --role-name catalogue-ecs-task \
    --policy-name catalogue-s3-access \
    --policy-document file:///tmp/s3-policy.json \
    --no-cli-pager

echo "    ✓ catalogue-ecs-task: $TASK_ROLE_ARN"

# 7c. GitHub Actions OIDC provider
echo ""
echo ">>> 8/10  Setting up GitHub OIDC provider..."

aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
    --no-cli-pager 2>/dev/null || echo "    (OIDC provider exists)"

# 7d. GitHub Actions deploy role
cat > /tmp/github-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:*"
      }
    }
  }]
}
EOF

DEPLOY_ROLE_ARN=$(aws iam create-role \
    --role-name catalogue-github-deploy \
    --assume-role-policy-document file:///tmp/github-trust.json \
    --query 'Role.Arn' --output text \
    --no-cli-pager 2>/dev/null || \
    aws iam get-role --role-name catalogue-github-deploy \
        --query 'Role.Arn' --output text --no-cli-pager)

cat > /tmp/deploy-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "arn:aws:ecr:$REGION:$ACCOUNT_ID:repository/catalogue-app"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:ListTasks",
        "ecs:DescribeTasks"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "$EXEC_ROLE_ARN",
        "$TASK_ROLE_ARN"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
    --role-name catalogue-github-deploy \
    --policy-name catalogue-deploy-permissions \
    --policy-document file:///tmp/deploy-policy.json \
    --no-cli-pager

echo "    ✓ catalogue-github-deploy: $DEPLOY_ROLE_ARN"
echo ""

# ------------------------------------------------------------------
# 9. Secrets Manager (per-environment)
# ------------------------------------------------------------------
echo ">>> 9/10  Storing secrets..."

API_KEY_STAGING=$(openssl rand -hex 32)
API_KEY_PROD=$(openssl rand -hex 32)

for ENV in staging prod; do
    echo "    --- ${ENV} ---"

    # Wait for RDS endpoint
    echo "    Waiting for RDS instance catalogue-${ENV} to become available..."
    echo "    (This may take 5-10 minutes — grab a coffee ☕)"
    aws rds wait db-instance-available \
        --db-instance-identifier "catalogue-${ENV}" \
        --region "$REGION" --no-cli-pager

    RDS_ENDPOINT=$(aws rds describe-db-instances \
        --db-instance-identifier "catalogue-${ENV}" \
        --query 'DBInstances[0].Endpoint.Address' --output text \
        --region "$REGION" --no-cli-pager)

    if [ "$ENV" = "prod" ]; then
        DB_PASSWORD="$DB_PASSWORD_PROD"
        API_KEY="$API_KEY_PROD"
    else
        DB_PASSWORD="$DB_PASSWORD_STAGING"
        API_KEY="$API_KEY_STAGING"
    fi

    DATABASE_URL="postgresql://catalogue:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/catalogue"
    S3_BUCKET="ra-catalogue-${ENV}-$ACCOUNT_ID"

    for SECRET_NAME in DATABASE_URL API_KEY S3_BUCKET; do
        SECRET_VALUE="${!SECRET_NAME}"
        aws secretsmanager create-secret \
            --name "catalogue-${ENV}/$SECRET_NAME" \
            --secret-string "$SECRET_VALUE" \
            --region "$REGION" --no-cli-pager 2>/dev/null || \
        aws secretsmanager put-secret-value \
            --secret-id "catalogue-${ENV}/$SECRET_NAME" \
            --secret-string "$SECRET_VALUE" \
            --region "$REGION" --no-cli-pager
        echo "    ✓ catalogue-${ENV}/$SECRET_NAME"
    done
done
echo ""

# ------------------------------------------------------------------
# 10. ALB + ECS Cluster + Services (staging + prod)
# ------------------------------------------------------------------
echo ">>> 10/10  Creating ALB, ECS cluster, and services..."

# Create ALB
ALB_ARN=$(aws elbv2 create-load-balancer \
    --name catalogue-alb \
    --subnets "$SUBNET_1" "$SUBNET_2" \
    --security-groups "$ALB_SG" \
    --scheme internet-facing \
    --type application \
    --region "$REGION" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text \
    --no-cli-pager 2>/dev/null || \
    aws elbv2 describe-load-balancers \
        --names catalogue-alb \
        --query 'LoadBalancers[0].LoadBalancerArn' --output text \
        --region "$REGION" --no-cli-pager)

ALB_DNS=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns "$ALB_ARN" \
    --query 'LoadBalancers[0].DNSName' --output text \
    --region "$REGION" --no-cli-pager)

echo "    ALB: $ALB_DNS"

# Target groups — one per environment
for ENV in staging prod; do
    TG_NAME="catalogue-${ENV}-tg"
    TG_ARN=$(aws elbv2 create-target-group \
        --name "$TG_NAME" \
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
            --names "$TG_NAME" \
            --query 'TargetGroups[0].TargetGroupArn' --output text \
            --region "$REGION" --no-cli-pager)

    if [ "$ENV" = "staging" ]; then
        TG_ARN_STAGING="$TG_ARN"
    else
        TG_ARN_PROD="$TG_ARN"
    fi
    echo "    ✓ Target group: $TG_NAME"
done

# HTTPS listener with host-based routing
# Default action → prod target group
# Rule: staging-catalogue.hoy.la → staging target group
#
# NOTE: To use HTTPS, an ACM certificate must already exist for
# *.hoy.la or catalogue.hoy.la + staging-catalogue.hoy.la.
# Replace CERT_ARN below with the real ARN, or use HTTP for initial setup.

# Try to find an existing HTTPS listener, otherwise create HTTP
LISTENER_ARN=$(aws elbv2 describe-listeners \
    --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[0].ListenerArn' --output text \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "None")

if [ "$LISTENER_ARN" = "None" ] || [ -z "$LISTENER_ARN" ]; then
    LISTENER_ARN=$(aws elbv2 create-listener \
        --load-balancer-arn "$ALB_ARN" \
        --protocol HTTP --port 80 \
        --default-actions Type=forward,TargetGroupArn="$TG_ARN_PROD" \
        --region "$REGION" \
        --query 'Listeners[0].ListenerArn' --output text \
        --no-cli-pager)
    echo "    ✓ HTTP listener (default → prod)"
fi

# Host-based rule: staging-catalogue.hoy.la → staging TG
aws elbv2 create-rule \
    --listener-arn "$LISTENER_ARN" \
    --priority 10 \
    --conditions Field=host-header,Values=staging-catalogue.hoy.la \
    --actions Type=forward,TargetGroupArn="$TG_ARN_STAGING" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (staging host rule exists)"

echo "    ✓ Host rule: staging-catalogue.hoy.la → staging TG"

# ECS cluster
aws ecs create-cluster \
    --cluster-name catalogue \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (cluster exists)"

echo "    ✓ ECS cluster: catalogue"

# Register task definitions — one per environment
for ENV in staging prod; do
    TASK_DEF_CONTENT=$(cat ".aws/task-definition-${ENV}.json" \
        | sed "s|PLACEHOLDER|$ECR_URI:latest|g")

    echo "$TASK_DEF_CONTENT" > "/tmp/task-def-${ENV}-resolved.json"

    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --cli-input-json "file:///tmp/task-def-${ENV}-resolved.json" \
        --region "$REGION" \
        --query 'taskDefinition.taskDefinitionArn' --output text \
        --no-cli-pager)

    echo "    ✓ Task definition (${ENV}): $TASK_DEF_ARN"
done

# Create ECS services — one per environment
for ENV in staging prod; do
    if [ "$ENV" = "staging" ]; then
        TG_ARN="$TG_ARN_STAGING"
        TASK_FAMILY="catalogue-staging"
    else
        TG_ARN="$TG_ARN_PROD"
        TASK_FAMILY="catalogue-prod"
    fi

    aws ecs create-service \
        --cluster catalogue \
        --service-name "catalogue-${ENV}" \
        --task-definition "$TASK_FAMILY" \
        --desired-count 1 \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}" \
        --load-balancers "targetGroupArn=$TG_ARN,containerName=app,containerPort=8000" \
        --region "$REGION" --no-cli-pager 2>/dev/null || echo "    catalogue-${ENV} (service exists)"

    echo "    ✓ ECS service: catalogue-${ENV}"
done
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "============================================"
echo "  ✅  AWS Infrastructure Ready!"
echo "============================================"
echo ""
echo "  ALB URL:    http://$ALB_DNS"
echo "  ECR URI:    $ECR_URI"
echo ""
echo "  Staging:"
echo "    RDS:      catalogue-staging"
echo "    S3:       ra-catalogue-staging-$ACCOUNT_ID"
echo "    Secrets:  catalogue-staging/{DATABASE_URL,API_KEY,S3_BUCKET}"
echo "    DNS:      staging-catalogue.hoy.la"
echo ""
echo "  Production:"
echo "    RDS:      catalogue-prod"
echo "    S3:       ra-catalogue-prod-$ACCOUNT_ID"
echo "    Secrets:  catalogue-prod/{DATABASE_URL,API_KEY,S3_BUCKET}"
echo "    DNS:      catalogue.hoy.la"
echo ""
echo "  Deploy Role ARN (add to GitHub secrets):"
echo "    $DEPLOY_ROLE_ARN"
echo ""
echo "  API Keys (share with team):"
echo "    Staging: $API_KEY_STAGING"
echo "    Prod:    $API_KEY_PROD"
echo ""
echo "  Next steps:"
echo "    1. Add AWS_DEPLOY_ROLE_ARN secret to GitHub repo:"
echo "       $DEPLOY_ROLE_ARN"
echo "    2. Create 'staging' environment in GitHub (no protection)"
echo "    3. Create 'production' environment in GitHub (add reviewers)"
echo "    4. Point DNS: staging-catalogue.hoy.la → ALB"
echo "       Point DNS: catalogue.hoy.la → ALB"
echo "    5. Push to a branch → deploys to staging"
echo "       Merge to main → deploys to production"
echo ""

# Clean up temp files
rm -f /tmp/ecs-trust.json /tmp/secrets-policy.json /tmp/s3-policy.json \
      /tmp/github-trust.json /tmp/deploy-policy.json \
      /tmp/task-def-staging-resolved.json /tmp/task-def-prod-resolved.json
