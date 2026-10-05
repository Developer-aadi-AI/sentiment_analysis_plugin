# Deploying on Oracle Cloud Always Free ($0, always on)

The app runs in Docker on an Always Free VM. It never sleeps, `restart: always` brings it back
after crashes and reboots, and the processed-review store lives on a Docker volume, so no review
is ever emailed twice across redeploys.

## 1. Create the account (you do this; it needs your identity)
1. Sign up at https://signup.cloud.oracle.com. A card is required for verification only; Always
   Free resources are not charged.
2. Pick your **home region** carefully. Always Free compute only runs there, and it can't be changed.
3. (Recommended) **Billing → Upgrade to Pay As You Go.** Oracle stops Always Free VMs that sit
   idle (<20% CPU for 7 days); PAYG accounts are exempt. Usage within Always Free limits stays
   $0. Then add a **Budget** with an alert at $1 (Billing → Budgets) as a safety net.

## 2. Create the VM
Compute → Instances → Create instance:
- **Image:** Canonical Ubuntu 24.04
- **Shape:** `VM.Standard.A1.Flex` (Ampere), **1 OCPU, 6 GB**, labelled "Always Free eligible".
  If A1 capacity is unavailable in your region, use `VM.Standard.E2.1.Micro` (1 GB); it's enough.
- **Networking:** public subnet, *assign a public IPv4 address*.
- **SSH keys:** upload or download a key pair.
- Boot volume: the default (≤200 GB total is free).

## 3. Open the port in Oracle's network firewall
Networking → Virtual cloud networks → your VCN → Security Lists → Default → **Add Ingress Rule**:
source `0.0.0.0/0`, TCP, destination port **8000**.

## 4. Install and start the app
```bash
ssh ubuntu@<public-ip>
curl -fsSLO https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/oracle-setup.sh
bash oracle-setup.sh https://github.com/<owner>/<repo>.git
nano ~/review-responder/.env            # set LLM_API_KEY, ADMIN_TOKEN
bash oracle-setup.sh https://github.com/<owner>/<repo>.git
```
For a private repo, clone with a GitHub fine-grained read-only token or a deploy key.

## 5. Check it
```bash
curl http://<public-ip>:8000/health
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://<public-ip>:8000/pending
sudo docker logs -f review-responder
```

## Updating
```bash
cd ~/review-responder && git pull && sudo docker compose up -d --build
```

## Going live later
- Read drafts with `/pending`; when happy set `DRY_RUN=false` (approval queue) and SMTP settings
  (Gmail: app password, port 587), then `sudo docker compose up -d`.
- Switch `ADAPTER` to `webhook` or `sql` for a real app. For webhooks, put HTTPS in front
  (e.g. a free Cloudflare Tunnel or Caddy with a domain), and set `WEBHOOK_SECRET`.

## Costs to watch
- Hosting: $0 within Always Free limits.
- LLM: the template uses Groq's free tier (`openai/gpt-oss-120b`), $0 but rate-limited. The
  poller only classifies new reviews, and dry-run drafts are not re-generated. Switching to a
  paid model (e.g. `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-opus-5-5`) bills per review.
