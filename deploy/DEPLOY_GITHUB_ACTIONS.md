# Deploying with GitHub Actions ($0, no credit card, no server)

There is no server to keep awake. A scheduled workflow
([.github/workflows/review-responder.yml](../.github/workflows/review-responder.yml)) runs every
15 minutes. Each run processes new reviews, saves its state, and exits.

- **Cost:** $0. GitHub Actions minutes are free and unlimited for **public** repos (a private
  repo would run out of its 2,000 free minutes). The LLM is Groq's free tier.
- **State:** the processed-review store (which guarantees one email per review) is encrypted
  with your `STATE_KEY` and kept on the `responder-state` branch. It's safe in a public repo
  because nothing is readable without the key.
- **Logs are public**, so the workflow prints only review IDs and statuses, never names,
  emails, or review text.

## 1. Add the secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `LLM_API_KEY` | Your Groq key (console.groq.com/keys) |
| `STATE_KEY` | A long random string. Generate one: `python -c "import secrets; print(secrets.token_hex(32))"`. **Save a copy somewhere safe**; without it the saved state can't be read. |

Email secrets (`SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`) are only needed once you turn
dry-run off.

## 2. Turn it on
Repo → **Actions** tab → enable workflows if asked → **Review Responder → Run workflow**.
After that it runs by itself every 15 minutes.

## 3. Read the drafts (on your PC)
Drafts aren't in the public logs. To read them, download and decrypt the state:
```bash
export STATE_KEY=<your key>
bash deploy/state.sh restore
review-responder drafts                 # or: drafts --status dry_run / pending_approval / held
```

## Changing settings
Non-secret settings (brand, source, `DRY_RUN`, model, ...) live in the `env:` block of the
workflow file. Edit, commit, push.

## Going live later
1. Add `SMTP_USER`, `SMTP_PASSWORD` (Gmail: an app password) and `EMAIL_FROM` secrets.
2. Set `DRY_RUN: "false"` in the workflow. Drafts then wait in the approval queue.
3. To send one: **Actions → Review Responder → Run workflow**, enter the review ID in
   `approve_review_id`. (Or set `AUTO_SEND: "true"` to send guard-approved drafts
   automatically.)
4. Point it at a real app: `ADAPTER: sql` with a `SOURCE_DB_URL` secret, or keep a CSV/JSON
   export updated in the repo.

## Limits to know
- Scheduled runs can start late (often by 5-15 min, more at busy times). That's fine for email
  replies, but there's no live URL or webhook endpoint.
- GitHub pauses schedules in public repos after 60 days with no repo activity. The workflow
  re-enables itself on each run, and you'll get an email from GitHub if it ever gets paused.
- If a run fails after sending but before saving state, the next run could send that email
  again. The save step runs even when earlier steps fail, and retries the push, to keep this
  window tiny.
