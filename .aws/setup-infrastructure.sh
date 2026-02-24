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
#   5. RDS PostgreSQL (staging)
#   6. ECS cluster + services
#   7. IAM roles (task execution, task, GitHub Actions deploy)
#   8. GitHub OIDC provider
#   9. Secrets Manager entries
#  10. Application Load Balancer
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
# 6. RDS PostgreSQL (staging — single, small instance)
# ------------------------------------------------------------------
echo ">>> 6/10  Creating RDS PostgreSQL instance (staging)..."

DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

# Create DB subnet group
aws rds create-db-subnet-group \
    --db-subnet-group-name catalogue-db-subnets \
    --db-subnet-group-description "Catalogue DB subnets" \
    --subnet-ids "$SUBNET_1" "$SUBNET_2" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (subnet group exists)"

aws rds create-db-instance \
    --db-instance-identifier catalogue-staging \
    --engine postgres \
    --engine-version 16 \
    --db-instance-class db.t4g.micro \
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
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (instance exists)"

echo "    ✓ catalogue-staging (db.t4g.micro, Postgres 16)"
echo "    DB password saved to Secrets Manager in step 9"
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

# Allow reading secrets
cat > /tmp/secrets-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "secretsmanager:GetSecretValue"
    ],
    "Resource": "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:catalogue/*"
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
# 9. Secrets Manager
# ------------------------------------------------------------------
echo ">>> 9/10  Storing secrets..."

# Wait for RDS endpoint (it takes a few minutes)
echo "    Waiting for RDS instance to become available..."
echo "    (This may take 5-10 minutes — grab a coffee ☕)"
aws rds wait db-instance-available \
    --db-instance-identifier catalogue-staging \
    --region "$REGION" --no-cli-pager

RDS_ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier catalogue-staging \
    --query 'DBInstances[0].Endpoint.Address' --output text \
    --region "$REGION" --no-cli-pager)

DATABASE_URL="postgresql://catalogue:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/catalogue"
API_KEY=$(openssl rand -hex 32)
S3_BUCKET="ra-catalogue-staging-$ACCOUNT_ID"

for SECRET_NAME in DATABASE_URL API_KEY S3_BUCKET; do
    SECRET_VALUE="${!SECRET_NAME}"
    aws secretsmanager create-secret \
        --name "catalogue/$SECRET_NAME" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" --no-cli-pager 2>/dev/null || \
    aws secretsmanager put-secret-value \
        --secret-id "catalogue/$SECRET_NAME" \
        --secret-string "$SECRET_VALUE" \
        --region "$REGION" --no-cli-pager
    echo "    ✓ catalogue/$SECRET_NAME"
done
echo ""

# ------------------------------------------------------------------
# 10. ALB + ECS Cluster + Service
# ------------------------------------------------------------------
echo ">>> 10/10  Creating ALB, ECS cluster, and service..."

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

# Target group
TG_ARN=$(aws elbv2 create-target-group \
    --name catalogue-staging-tg \
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
        --names catalogue-staging-tg \
        --query 'TargetGroups[0].TargetGroupArn' --output text \
        --region "$REGION" --no-cli-pager)

# HTTP listener → target group
aws elbv2 create-listener \
    --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 \
    --default-actions Type=forward,TargetGroupArn="$TG_ARN" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (listener exists)"

# ECS cluster
aws ecs create-cluster \
    --cluster-name catalogue \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (cluster exists)"

echo "    ✓ ECS cluster: catalogue"

# Register task definition with real role ARNs
TASK_DEF_CONTENT=$(cat .aws/task-definition.json \
    | sed "s|\${EXECUTION_ROLE_ARN}|$EXEC_ROLE_ARN|g" \
    | sed "s|\${TASK_ROLE_ARN}|$TASK_ROLE_ARN|g" \
    | sed "s|PLACEHOLDER|$ECR_URI:latest|g")

echo "$TASK_DEF_CONTENT" > /tmp/task-def-resolved.json

TASK_DEF_ARN=$(aws ecs register-task-definition \
    --cli-input-json file:///tmp/task-def-resolved.json \
    --region "$REGION" \
    --query 'taskDefinition.taskDefinitionArn' --output text \
    --no-cli-pager)

echo "    ✓ Task definition: $TASK_DEF_ARN"

# Create ECS service (staging)
aws ecs create-service \
    --cluster catalogue \
    --service-name catalogue-staging \
    --task-definition catalogue-app \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$ECS_SG],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=$TG_ARN,containerName=app,containerPort=8000" \
    --region "$REGION" --no-cli-pager 2>/dev/null || echo "    (service exists)"

echo "    ✓ ECS service: catalogue-staging"
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
echo "  RDS Host:   $RDS_ENDPOINT"
echo "  S3 Bucket:  $S3_BUCKET"
echo ""
echo "  Deploy Role ARN (add to GitHub secrets):"
echo "    $DEPLOY_ROLE_ARN"
echo ""
echo "  API Key (share with team):"
echo "    $API_KEY"
echo ""
echo "  Next steps:"
echo "    1. Add AWS_DEPLOY_ROLE_ARN secret to GitHub repo:"
echo "       $DEPLOY_ROLE_ARN"
echo "    2. Create 'staging' environment in GitHub (no protection)"
echo "    3. Create 'production' environment in GitHub (add reviewers)"
echo "    4. Push to main — CI will build, test, and deploy!"
echo ""

# Clean up temp files
rm -f /tmp/ecs-trust.json /tmp/secrets-policy.json /tmp/s3-policy.json \
      /tmp/github-trust.json /tmp/deploy-policy.json /tmp/task-def-resolved.json
