#!/usr/bin/env bash
# ==========================================================================
# Catalogue Tool — Mothball / Restore PRE-FLIGHT (READ-ONLY)
#
# Validates every resource name, config value, and assumption that
# mothball-prod.sh and restore-prod.sh depend on, BEFORE you run either for
# real. Contains only describe/get calls — no create/update/delete/put — so it
# is safe to run any time.
#
# Run it before a mothball (confirm the stack is as the scripts expect) and
# before a restore (confirm the snapshot, networking, secret, and ECR image are
# all in place). Eyeball the ✓/✗/⚠ lines; investigate any ✗ before proceeding.
#
# Prerequisites: aws cli configured, account 028597908565, region eu-north-1.
# ==========================================================================
REGION="eu-north-1"
export AWS_PAGER=""

hr(){ echo; echo "=== $1 ==="; }

hr "Caller identity (expect account 028597908565)"
aws sts get-caller-identity --query '{account:Account,arn:Arn}' --output text 2>/dev/null | sed 's/^/  /' \
  || echo "  ✗ not authenticated"

hr "RDS instance catalogue-prod (mothball target / restore parity)"
read -r RSTATUS RCLS RSTORE RMAZ RPUB RDELPROT RSUBG <<<"$(aws rds describe-db-instances \
  --db-instance-identifier catalogue-prod --region "$REGION" \
  --query 'DBInstances[0].[DBInstanceStatus,DBInstanceClass,AllocatedStorage,MultiAZ,PubliclyAccessible,DeletionProtection,DBSubnetGroup.DBSubnetGroupName]' \
  --output text 2>/dev/null)"
if [ -n "$RSTATUS" ]; then
  echo "  status=$RSTATUS  class=$RCLS  storageGB=$RSTORE  multiAZ=$RMAZ  public=$RPUB"
  echo "  deletionProtection=$RDELPROT  subnetGroup=$RSUBG"
  [ "$RCLS"  = "db.t4g.micro" ]         && echo "  ✓ class matches restore (db.t4g.micro)"              || echo "  ⚠ class $RCLS != restore's db.t4g.micro"
  [ "$RMAZ"  = "False" ]                && echo "  ✓ single-AZ matches restore (--no-multi-az)"          || echo "  ⚠ multiAZ=$RMAZ; restore forces single-AZ"
  [ "$RPUB"  = "False" ]                && echo "  ✓ private matches restore (--no-publicly-accessible)" || echo "  ⚠ public=$RPUB; restore forces private"
  [ "$RSUBG" = "catalogue-db-subnets" ] && echo "  ✓ subnet group matches restore"                      || echo "  ⚠ subnet group $RSUBG != restore's catalogue-db-subnets"
  [ "$RDELPROT" = "True" ] && echo "  ⚠ DELETION PROTECTION ON — mothball will (correctly) abort; disable it before the real run."
else
  echo "  (catalogue-prod not found — expected if already mothballed; needed before a mothball)"
fi

hr "ECS cluster 'catalogue' + service catalogue-prod"
aws ecs describe-services --cluster catalogue --services catalogue-prod --region "$REGION" \
  --query 'services[0].[status,launchType,runningCount,desiredCount]' --output text 2>/dev/null \
  | sed 's/^/  status launchType running desired: /' || echo "  (service not found — expected if mothballed)"

hr "ALB catalogue-alb"
aws elbv2 describe-load-balancers --names catalogue-alb --region "$REGION" \
  --query 'LoadBalancers[0].[State.Code,Scheme,Type,DNSName]' --output text 2>/dev/null \
  | sed 's/^/  /' || echo "  (ALB not found — expected if mothballed)"

hr "Target group catalogue-prod-tg (restore recreates as HTTP/8000/ip//health)"
read -r TPROTO TPORT TTYPE THC <<<"$(aws elbv2 describe-target-groups --names catalogue-prod-tg --region "$REGION" \
  --query 'TargetGroups[0].[Protocol,Port,TargetType,HealthCheckPath]' --output text 2>/dev/null)"
if [ -n "$TPROTO" ]; then
  echo "  protocol=$TPROTO port=$TPORT targetType=$TTYPE healthCheckPath=$THC"
  [ "$TPROTO/$TPORT/$TTYPE/$THC" = "HTTP/8000/ip//health" ] && echo "  ✓ matches restore" || echo "  ⚠ differs from restore's hardcoded HTTP/8000/ip//health"
else
  echo "  (target group not found — expected if mothballed; restore recreates it)"
fi

hr "Default VPC + default-for-az subnets (restore needs >=2)"
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text --region "$REGION" 2>/dev/null)
echo "  default VPC: ${VPC_ID:-<none>}"
SUBS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
  --query 'Subnets[*].SubnetId' --output text --region "$REGION" 2>/dev/null)
NSUB=$(echo "$SUBS" | wc -w | tr -d ' ')
echo "  default-for-az subnets ($NSUB): $SUBS"
{ [ "$NSUB" -ge 2 ] 2>/dev/null && echo "  ✓ >=2 subnets (ALB OK)"; } || echo "  ✗ fewer than 2 default subnets — ALB create would fail"

hr "Security groups (restore looks these up by name)"
for g in catalogue-alb-sg catalogue-ecs-sg catalogue-rds-sg; do
  id=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$g" Name=vpc-id,Values="$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text --region "$REGION" 2>/dev/null)
  { [ -n "$id" ] && [ "$id" != "None" ] && echo "  ✓ $g = $id"; } || echo "  ✗ $g NOT FOUND"
done

hr "DB subnet group catalogue-db-subnets"
aws rds describe-db-subnet-groups --db-subnet-group-name catalogue-db-subnets --region "$REGION" \
  --query 'DBSubnetGroups[0].[DBSubnetGroupName,SubnetGroupStatus]' --output text 2>/dev/null \
  | sed 's/^/  /' || echo "  ✗ not found"

hr "Secrets catalogue-prod/{DATABASE_URL,API_KEY,S3_BUCKET} (existence only)"
for s in DATABASE_URL API_KEY S3_BUCKET; do
  n=$(aws secretsmanager describe-secret --secret-id "catalogue-prod/$s" --region "$REGION" --query 'Name' --output text 2>/dev/null)
  { [ -n "$n" ] && [ "$n" != "None" ] && echo "  ✓ $n"; } || echo "  ✗ catalogue-prod/$s NOT FOUND"
done

hr "ECR image catalogue-app:latest (restore needs it)"
aws ecr describe-images --repository-name catalogue-app --image-ids imageTag=latest --region "$REGION" \
  --query 'imageDetails[0].imagePushedAt' --output text 2>/dev/null \
  | sed 's/^/  latest pushed: /' || echo "  ✗ no :latest image in ECR"

hr "S3 bucket ra-catalogue-prod-028597908565 (must persist through mothball)"
if aws s3api head-bucket --bucket ra-catalogue-prod-028597908565 2>/dev/null; then echo "  ✓ bucket reachable"; else echo "  ✗ bucket missing/inaccessible"; fi

hr "Cognito user pool eu-north-1_ThfApt8C5 (from task-def env)"
aws cognito-idp describe-user-pool --user-pool-id eu-north-1_ThfApt8C5 --region "$REGION" \
  --query 'UserPool.[Name,EstimatedNumberOfUsers]' --output text 2>/dev/null | sed 's/^/  name users: /' \
  || echo "  ✗ pool not found"

hr "DATABASE_URL rewrite simulation (restore step 2) — password masked"
OLD_URL=$(aws secretsmanager get-secret-value --secret-id catalogue-prod/DATABASE_URL \
  --query SecretString --output text --region "$REGION" 2>/dev/null)
if [ -n "$OLD_URL" ]; then
  AT=$(printf '%s' "$OLD_URL" | tr -cd '@' | wc -c | tr -d ' ')
  FAKE="catalogue-prod.newtoken0000.eu-north-1.rds.amazonaws.com"
  NEW_URL=$(printf '%s' "$OLD_URL" | sed -E "s#@[^/]+/#@${FAKE}:5432/#")
  MOLD=$(printf '%s' "$OLD_URL"  | sed -E 's#(://[^:]+:)[^@]*@#\1****@#')
  MNEW=$(printf '%s' "$NEW_URL"  | sed -E 's#(://[^:]+:)[^@]*@#\1****@#')
  echo "  unencoded '@' count: $AT  (expect exactly 1; >1 means the sed would corrupt the URL)"
  echo "  current   (masked): $MOLD"
  echo "  rewritten (masked): $MNEW"
  case "$NEW_URL" in
    *"@${FAKE}:5432/"*) echo "  ✓ rewrite points at the new endpoint (restore guard would pass)" ;;
    *)                  echo "  ✗ rewrite would NOT match — restore's guard would abort. Investigate the URL shape." ;;
  esac
else
  echo "  ✗ could not read DATABASE_URL"
fi

hr "Existing manual mothball snapshots (restore restores the newest)"
aws rds describe-db-snapshots --snapshot-type manual --region "$REGION" \
  --query "DBSnapshots[?starts_with(DBSnapshotIdentifier,'catalogue-prod-mothball')].[DBSnapshotIdentifier,Status,SnapshotCreateTime]" \
  --output text 2>/dev/null | sed 's/^/  /'
echo "  (empty = no mothball snapshot yet — expected before the first mothball)"

hr "Orphaned Elastic IPs (unattached ones bill ~£3/mo each)"
aws ec2 describe-addresses --region "$REGION" --query 'Addresses[?AssociationId==`null`].PublicIp' --output text 2>/dev/null | sed 's/^/  unattached: /'

echo; echo "=== pre-flight complete (read-only; nothing was changed) ==="
