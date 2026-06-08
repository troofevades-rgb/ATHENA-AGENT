---
description: Pre-deploy review checklist for infrastructure / IaC changes
name: infra-change-review
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Infrastructure Change Review

Pre-deploy checklist for changes that touch production infrastructure:
Terraform, Kubernetes manifests, Dockerfiles, CI pipelines, network
configs, IAM. The premise: infra changes have a higher blast radius
than code changes, so they earn a more paranoid review.

## When to use this skill

Use BEFORE running ``terraform apply``, ``kubectl apply``, merging a
CI change, modifying network rules, or changing IAM. Skip for
read-only operations (``terraform plan``, ``kubectl describe``).

## The blast-radius questions

Before any apply / merge, answer all five:

### 1. What's the worst case if this is wrong?

Be concrete. "Could break the site" is not specific enough.

- "Could route 100% of prod traffic to a dev backend."
- "Could grant a service account ``*`` on every S3 bucket."
- "Could schedule a job that locks the primary DB for 4 hours."

If the worst case is bad, the change needs a staged rollout — not a
full apply.

### 2. Is this change reversible?

Some infra changes are one-way:

- DROPPING a database column, table, queue, or topic
- DELETING a Terraform-managed resource that holds state (RDS, EBS,
  S3 bucket with data, KMS key)
- ROTATING a credential that's referenced by external systems
- DELETING an IAM role currently in use

For one-way changes: ``terraform plan`` is NOT sufficient. Snapshot
or back up the underlying state BEFORE applying.

### 3. What's the rollback?

Write down the rollback command BEFORE you apply. If the rollback is
"hope nobody notices and revert the PR" — that's not a rollback,
that's a prayer.

```
deploy:    terraform apply -var-file=prod.tfvars
rollback:  terraform apply -var-file=prod.tfvars -target=<previous-state>
```

### 4. What's the staging story?

Has this change been applied to staging? Did anything visible break?
If staging skipped or doesn't exist — the change needs an even more
conservative rollout (canary, percentage-based traffic shift, etc.).

### 5. Who else needs to know?

If this touches:

- A service another team owns → notify them BEFORE applying
- Production DB → notify on-call BEFORE applying
- Security boundaries (IAM, networking) → security team review
- A live incident → incident commander gets veto

## Reading a Terraform plan

For every resource in a ``terraform plan``:

- **Create**: usually safe; check for naming collisions.
- **Update in-place**: safe if the diff is what you expect. Triple-
  check fields like ``enable_deletion_protection`` flipping to false.
- **Destroy and recreate**: STOP. This is a downtime event. Confirm
  the resource can be destroyed AND that recreation will preserve any
  state (DB data, attached volumes, IPs that other systems point at).
- **Destroy**: STOP. Confirm the resource is truly orphaned and that
  nothing external references it.

## Reading a Kubernetes diff

For every changed manifest:

- **Resource requests/limits**: shrinking limits can OOMKill pods on
  the next scheduling decision. Verify with current memory usage.
- **PodDisruptionBudget**: changing this can either cause cluster-
  rebalance outages or block legitimate evictions.
- **Service selectors**: a typo silently routes traffic to nothing.
  ``kubectl get endpoints <svc>`` after deploy to verify.
- **Init containers / volumes**: changing storage class or PVC size
  can force pod recreation with data loss.

## After applying

- Watch the metrics dashboard for 10 minutes. Don't trust "applied
  successfully" — trust "error rate stayed flat after applying."
- Document what was changed and when in your team's change log.
- If anything looks wrong: rollback first, debug second.
