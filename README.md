# SiteRevive IQ — Basic

Modular Django monolith, Celery/Redis workers, Postgres, HTMX + Tailwind
frontend, Docker Compose, Caddy for TLS. No WordPress involved anywhere in
this stack — that's a separate client tool.

This is the Basic tier — the most trimmed-down of the three builds:
single-user workspaces, one website per workspace, no roadmap builder, no
baselines/comparisons, no AI Visibility, reports restricted to Prospect
Audit only (no proposal generator, white-label, or CSV export), monitoring
frequency capped at None/Monthly, and issue categories narrowed to
Technical/SEO/Content/Security-Trust. See the Enterprise and Pro builds for
the fuller feature sets.

## What's built

- Auth (email/password; no public signup yet — accounts are created via a
  management command, then linked to Stripe by an operator), single-user
  workspace (no invites, roles, or activity log)
- Website CRUD (hard-capped at 1 website per workspace), manual scan
  triggering, HTMX-polled scan progress
- The crawler: SSRF-safe destination validation, URL normalization,
  bounded fetcher, HTML parser, breadth-first orchestration
- Deterministic analysis: Technical/SEO/Content/Security-Trust findings,
  scored issues, category + trend charts
- Reports: Prospect Audit only, with PDF export and a client-facing share
  page
- Monitoring (None/Monthly frequency) + notifications, with archive/bulk
  actions
- Stripe billing: Subscription model, billing portal, webhook handling.
  Currently admin-linked (sales-assisted) only — see "Not built yet" below

Not built yet: self-serve signup/checkout (Basic is meant to be purchasable
directly off a website eventually — that flow doesn't exist yet) and the
public marketing site itself. Seat limit is a non-issue here — the
workspace is already hard-capped at 1 user.

**Why this order works for a front-to-back build:** everything in section 1
and 2 below gets you a real, live, logged-in UI — dashboard, website list,
add/edit forms, scan progress — deployed on your own domain. That's the
visual reference to build against and show around, even though the crawler
underneath it is the only "smart" part so far. Build 2+ adds intelligence
behind screens that already exist, instead of you staring at an empty page
waiting for backend logic first.

---

## 1. Local development (do this first)

Requirements: Docker Desktop (or Docker Engine + Compose) installed.

```bash
cd sitereviveiq
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD to anything for local dev.

docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py bootstrap_admin \
  --email you@yourcompany.com --workspace-name "Your Agency"
```

Visit http://localhost:8000 and log in. Add a website, hit "Run scan," and
watch the HTMX progress view — it polls every 3 seconds until the scan
finishes.

Run the tests:
```bash
docker compose exec web pip install -e ".[dev]"
docker compose exec web pytest
```

---

## 2. AWS setup — what you need to create

This is everything on the AWS side that can't be hard-coded into the repo,
in the order to do it.

### 2.1 IAM role for the instance (console only, no SSH)

Before launching the instance, create an IAM role so CodeDeploy can manage
it:

1. IAM console → Roles → Create role → AWS service → EC2
2. Attach policy `AmazonEC2RoleforAWSCodeDeploy`
3. Name it e.g. `SiteReviveIQ-EC2-Role`, create it

You'll attach this role to the instance in the next step.

### 2.2 EC2 instance

- **Instance type:** `t3.small` (2 vCPU, 2 GB RAM) — matches the spec's
  alpha sizing. You can resize later without much pain.
- **AMI:** Ubuntu 24.04 LTS
- **Storage:** 30 GB gp3 is plenty to start
- **IAM instance profile:** the `SiteReviveIQ-EC2-Role` from step 2.1
- **Key pair:** create one and download it even though you won't be
  SSHing in regularly — AWS requires a key pair to launch, and it's the
  fallback for the "absolutely necessary" case (see 2.9)
- **User data:** paste the full contents of `ops/ec2-user-data.sh` into
  the "User data" box under Advanced details. This installs Docker and
  the CodeDeploy agent automatically on first boot — nothing to type in
  over SSH.

### 2.3 Security group

Only open what's needed:
| Port | Source | Why |
|---|---|---|
| 80 | 0.0.0.0/0 | HTTP (Caddy redirects to HTTPS) |
| 443 | 0.0.0.0/0 | HTTPS |

Notice port 22 isn't listed — you don't need it open at all day-to-day.
SSM Session Manager (2.9) works over HTTPS through the IAM role, not
through an open port.

Do **not** open 5432 (Postgres) or 6379 (Redis) to the internet — in the
production Compose file those containers don't publish ports at all, so
they're only reachable from other containers on the same Docker network.

### 2.4 Elastic IP

Allocate one and associate it with the instance, so the IP doesn't change
if you ever stop/start it. You'll point DNS at this IP.

### 2.5 DNS (in whatever registrar/DNS host you use for sitereviveiq.com)

| Type | Name | Value |
|---|---|---|
| A | `sitereviveiq.com` | your Elastic IP |
| A | `www.sitereviveiq.com` | your Elastic IP |

Caddy (already configured in `compose.production.yaml` /
`ops/Caddyfile`) will automatically get and renew a Let's Encrypt cert
once DNS resolves and ports 80/443 are reachable — no manual cert work.

### 2.6 CodeDeploy setup (console only)

1. CodeDeploy console → Applications → Create application. Platform:
   EC2/On-premises. Name it `sitereviveiq`.
2. Create a deployment group. Deployment type: In-place. Environment:
   Amazon EC2 instances, tag-matched to your instance. Attach the
   `AWSCodeDeployRole` service role (create it if prompted — console
   button does this for you).
3. Create an S3 bucket (e.g. `sitereviveiq-deploys`) to drop zips into.

### 2.7 The one unavoidable manual step: secrets

`.env.production` holds real passwords and your Django secret key, so it
is never in the repo or the deploy zip — CodeDeploy can't create it for
you, and it shouldn't. This is the one time you'll touch the instance
directly, and you can do it without SSH using **SSM Session Manager**
(EC2 console → select instance → Connect → Session Manager tab — opens a
browser terminal, no key file, no local terminal app):

```bash
sudo mkdir -p /opt/sitereviveiq
sudo nano /opt/sitereviveiq/.env.production
# paste in the real values (see .env.example for the list of keys),
# save, exit
```

That file then persists on the instance across every future deploy —
CodeDeploy only overwrites files that are part of the zip, and this one
never is.

After your very first successful deployment (2.8), create your login —
also via the SSM Session Manager browser terminal, one time only:

```bash
cd /opt/sitereviveiq
sudo docker compose -f compose.production.yaml exec web python manage.py bootstrap_admin \
  --email you@yourcompany.com --workspace-name "Activated Mobile Solutions"
```

### 2.8 Deploying, from here on out (drag-and-drop, zero SSH)

```bash
# On your own machine, zip the repo (excluding anything with secrets/local state):
zip -r sitereviveiq.zip . -x ".git/*" ".env" "*.pyc"
```

Then in the S3 console: upload `sitereviveiq.zip` to your `sitereviveiq-deploys`
bucket (drag-and-drop works). Then in the CodeDeploy console: your
application → Create deployment → point it at that S3 object → Deploy.
CodeDeploy pulls the zip onto the instance, runs the hooks in `appspec.yml`
(stop containers → build → migrate/collectstatic → start → health-check),
and reports success/failure right in the console. No terminal involved.

Give Caddy a minute on the very first deploy to issue the HTTPS
certificate, then visit `https://sitereviveiq.com`.

### 2.9 The "absolutely necessary" fallback

If something's genuinely stuck and you need to look under the hood — a
container in a crash loop, reading a raw log file — use the same SSM
Session Manager browser terminal from 2.7. No SSH key, no terminal app,
no open port 22. This should be rare, not routine.

### 2.10 Monthly cost estimate (this is the budget-efficient path)

| Item | Est. cost/mo |
|---|---|
| EC2 t3.small (on-demand, us-east-1) | ~$15 |
| 30 GB gp3 EBS volume | ~$2.50 |
| Elastic IP (free while attached to a running instance) | $0 |
| S3 (deploy zips, negligible size/frequency) | ~$0.10 |
| Data transfer (low volume, alpha use) | ~$1–3 |
| **Total** | **~$19–21/mo** |

Two ways to cut this further later, if you want: a 1-year EC2 Savings Plan
(~30% off) once you're confident this is staying up long-term, or stopping
the instance overnight/weekends during pure development (you lose the
Elastic IP's "free while attached" status only if you release it, so just
stop the instance, don't terminate it).

**On Cognito:** holding off on it, per your call. It's AWS's hosted
login/user-management service, and it's genuinely useful once you have
public signup and lots of users to manage — but for a single-admin
internal alpha it's an extra paid service and integration surface for
something Django's built-in auth (already built, $0, zero extra moving
parts) already handles. Worth revisiting if/when this becomes a
self-serve SaaS product with real signup volume.

### 2.11 What AWS is NOT doing here (by design, for Build 1)

- No RDS — Postgres runs in a container on the same instance. Fine for
  alpha/single-tenant use; move to RDS when you actually need managed
  backups/failover.
- No S3 — nothing generates files yet (reports/exports come in a later
  build).
- No load balancer/ALB — a single t3.small behind Caddy is the whole
  stack for now, matching "single active scan at a time during alpha."
- No WordPress, no relation to it at all — separate stack, separate
  concern.

### 2.12 Basic operational commands (via SSM Session Manager, not SSH)

```bash
# View logs
docker compose -f compose.production.yaml logs -f web
docker compose -f compose.production.yaml logs -f worker

# Restart after a code change
git pull
docker compose -f compose.production.yaml up -d --build

# Run a new migration
docker compose -f compose.production.yaml exec web python manage.py migrate

# Back up Postgres manually (do this before anything risky)
docker compose -f compose.production.yaml exec postgres \
  pg_dump -U sitereviveiq sitereviveiq > backup-$(date +%F).sql
```

---

## 3. What's next

- Self-serve checkout (Stripe Checkout/Payment Element + webhook-driven
  account provisioning), so this tier is purchasable directly off a
  website instead of only admin-linked
- The public marketing site
- Migrate to the AWS setup in section 2, alongside Enterprise and Pro
