#!/usr/bin/env bash
# ==========================================================================
# Catalogue Tool — Mothball PRODUCTION
#
# Takes a final RDS snapshot, then deletes the three resources that cost money
# year-round: the RDS instance, the ALB (+ target group), and the ECS service.
#
# DELIBERATELY LEFT IN PLACE (cheap or free, and they hold all the state):
#   - S3 bucket  ra-catalogue-prod-028597908565   (uploaded files + versioning)
#   - The final RDS snapshot                       (= the database, frozen)
#   - Cognito user pool                            (free <50k MAU; users kept)
#   - Secrets Manager  catalogue-prod/*            (~$1.20/mo total)
#   - ECR image, IAM roles, security groups, subnet group, CloudWatch logs
#
# Bring it all back with restore-prod.sh.
#
# Prerequisites: aws cli configured, account 028597908565, region eu-north-1.
# Run from the project root.
# ==========================================================================

set -euo pipefail

REGION="eu-north-1"
# Timestamp to the second so every run gets a unique snapshot id. A date-only id
# could collide with a pre-existing (possibly stale) same-day snapshot, which the
# old reuse-if-exists branch would then have accepted as the "final" backup
# before deleting the DB with --skip-final-snapshot — silent data loss.
SNAPSHOT_ID="catalogue-prod-mothball-$(date +%Y%m%d-%H%M%S)"
export AWS_PAGER=""

echo "============================================"
echo "  Catalogue — Mothball PRODUCTION"
echo "============================================"
echo ""
echo "This DELETES the production RDS instance, ALB, and ECS service."
echo "A snapshot ($SNAPSHOT_ID) is taken and verified FIRST."
echo "S3 files, Cognito users, secrets, and the container image are untouched."
echo ""
read -r -p "Type 'mothball' to continue: " confirm
[ "$confirm" = "mothball" ] || { echo "Aborted."; exit 1; }
echo ""

# --------------------------------------------------------------------------
# 1. Final snapshot (and verify it before deleting anything)
# --------------------------------------------------------------------------
echo ">>> 1/4  Snapshotting RDS catalogue-prod -> $SNAPSHOT_ID ..."
if aws rds describe-db-instances --db-instance-identifier catalogue-prod \
        --region "$REGION" >/dev/null 2>&1; then

    # The id is unique per run (see above), so always take a fresh snapshot of
    # the live data. If the id somehow already existed, create fails and set -e
    # aborts here — before any deletion.
    aws rds create-db-snapshot \
        --db-instance-identifier catalogue-prod \
        --db-snapshot-identifier "$SNAPSHOT_ID" \
        --region "$REGION" --no-cli-pager >/dev/null

    echo "    Waiting for snapshot to complete (5-10 min)..."
    aws rds wait db-snapshot-available \
        --db-snapshot-identifier "$SNAPSHOT_ID" --region "$REGION"

    STATUS=$(aws rds describe-db-snapshots --db-snapshot-identifier "$SNAPSHOT_ID" \
        --query 'DBSnapshots[0].Status' --output text --region "$REGION")
    [ "$STATUS" = "available" ] || {
        echo "    ERROR: snapshot status is '$STATUS', not 'available'."
        echo "    Aborting BEFORE any deletion — your data is untouched."
        exit 1
    }
    echo "    ✓ Snapshot $SNAPSHOT_ID is available."
else
    echo "    (RDS instance catalogue-prod not found — already mothballed?)"
fi
echo ""

# --------------------------------------------------------------------------
# 2. Delete the ECS service (keeps cluster + task definitions)
# --------------------------------------------------------------------------
echo ">>> 2/4  Deleting ECS service catalogue-prod ..."
aws ecs update-service --cluster catalogue --service catalogue-prod \
    --desired-count 0 --region "$REGION" --no-cli-pager >/dev/null 2>&1 || true
aws ecs delete-service --cluster catalogue --service catalogue-prod --force \
    --region "$REGION" --no-cli-pager >/dev/null 2>&1 \
    && echo "    ✓ Service deleted." \
    || echo "    (service already gone)"
echo ""

# --------------------------------------------------------------------------
# 3. Delete the ALB, then its target group
# --------------------------------------------------------------------------
echo ">>> 3/4  Deleting ALB catalogue-alb + target group ..."
ALB_ARN=$(aws elbv2 describe-load-balancers --names catalogue-alb \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text \
    --region "$REGION" 2>/dev/null || echo "None")
if [ "$ALB_ARN" != "None" ] && [ -n "$ALB_ARN" ]; then
    aws elbv2 delete-load-balancer --load-balancer-arn "$ALB_ARN" \
        --region "$REGION" --no-cli-pager
    aws elbv2 wait load-balancers-deleted --load-balancer-arns "$ALB_ARN" \
        --region "$REGION"
    echo "    ✓ ALB deleted."
else
    echo "    (ALB already gone)"
fi

# Target group can only be deleted once no listener references it. The ALB's
# listener can lag a few seconds behind 'load-balancers-deleted' returning, so
# the delete races and fails with ResourceInUse. Retry to ride out that window
# rather than masking the failure (which left an orphaned TG + a misleading
# success banner).
TG_ARN=$(aws elbv2 describe-target-groups --names catalogue-prod-tg \
    --query 'TargetGroups[0].TargetGroupArn' --output text \
    --region "$REGION" 2>/dev/null || echo "None")
if [ "$TG_ARN" != "None" ] && [ -n "$TG_ARN" ]; then
    tg_deleted=false
    for attempt in 1 2 3 4 5; do
        if aws elbv2 delete-target-group --target-group-arn "$TG_ARN" \
                --region "$REGION" --no-cli-pager 2>/dev/null; then
            tg_deleted=true
            break
        fi
        echo "    target group still referenced (attempt $attempt/5) — retrying in 10s..."
        sleep 10
    done
    if [ "$tg_deleted" = true ]; then
        echo "    ✓ Target group deleted."
    else
        echo "    ⚠ Target group NOT deleted after retries (still referenced)."
        echo "      It's free and restore reuses it, but remove it manually if you want a clean slate:"
        echo "      aws elbv2 delete-target-group --target-group-arn $TG_ARN --region $REGION"
    fi
else
    echo "    (target group already gone)"
fi
echo ""

# --------------------------------------------------------------------------
# 4. Delete the RDS instance (the snapshot from step 1 is what we keep)
# --------------------------------------------------------------------------
echo ">>> 4/4  Deleting RDS instance catalogue-prod ..."
if aws rds describe-db-instances --db-instance-identifier catalogue-prod \
        --region "$REGION" >/dev/null 2>&1; then
    # Only report "already gone" when it genuinely isn't there. A real failure
    # (deletion protection, incompatible state) must NOT be masked as success —
    # otherwise the instance keeps billing while the banner claims it's mothballed.
    aws rds delete-db-instance \
        --db-instance-identifier catalogue-prod \
        --skip-final-snapshot \
        --region "$REGION" --no-cli-pager >/dev/null \
        && echo "    ✓ Deletion initiated (runs in the background, a few minutes)." \
        || { echo "    ERROR: delete-db-instance failed (deletion protection? instance state?)."; \
             echo "    Snapshot $SNAPSHOT_ID is safe; investigate, then re-run."; exit 1; }
else
    echo "    (instance already gone)"
fi
echo ""

echo "============================================"
echo "  ✅  Production mothballed."
echo "============================================"
echo ""
echo "  KEEP THIS — needed to restore:"
echo "    Snapshot: $SNAPSHOT_ID"
echo ""
echo "  Revive with:   ./.aws/restore-prod.sh $SNAPSHOT_ID"
echo "  (restore-prod.sh also auto-detects the newest mothball snapshot.)"
echo ""
echo "  Tip: check for any now-unattached Elastic IPs"
echo "    aws ec2 describe-addresses --region $REGION \\"
echo "      --query 'Addresses[?AssociationId==\`null\`].PublicIp'"
echo "  Unattached EIPs bill ~\$3.60/mo each; release with aws ec2 release-address."
