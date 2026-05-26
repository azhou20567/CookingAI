# Deployment — Render + Neon (Free Tier)

Target audience: a portfolio piece. Public URL, anyone can browse and submit a YouTube URL, but rate-limited so a single bad actor can't drain your wallet. Total cost ceiling: **$5/month** (capped at Anthropic; Render and Neon stay at $0 indefinitely).

Expect a 30-second cold start after 15 minutes of idle — fine for portfolio traffic, awkward for live demos. (For a live demo, hit the URL ~60s before you start.)

---

## Manual steps

Do these in order. Steps 1–7 are required; step 8 is optional.

### 1. Cap your Anthropic spend at $5/month

Before anything else — this is the floor that protects you if everything else fails.

1. Open <https://console.anthropic.com/settings/limits>.
2. Set **Monthly spend limit** to `$5.00`.
3. Set the **Alert threshold** to `$4.00` (so you get an email before you hit the cap).
4. Save.

Once you hit $5 in a month, the Anthropic API returns a quota error. Your view already maps that to the 502 error page (no stack trace, no surprise bill).

### 2. Push the repo to GitHub

If it's not already there:

```powershell
gh repo create CookingAI --public --source=. --push
```

Or use the GitHub website UI to create the repo and push manually. **Verify `cookingai/.env` and `cookingai/db.sqlite3` are NOT in the commit** — both are gitignored, but double-check `git status` on the first push.

### 3. Generate a production SECRET_KEY

Run this locally and copy the output — you'll paste it into Render in step 6:

```powershell
python -c "from secrets import token_urlsafe; print(token_urlsafe(50))"
```

**Do not reuse** the `django-insecure-…` value from your local `.env`. That string is in your shell history and any backups; treat it as compromised for production purposes.

### 4. Create the Neon Postgres database

1. Sign up at <https://neon.tech> (no credit card required for free tier).
2. Click **New project**. Name it `cookingai`. Pick a region geographically close to Render's region (e.g. both `us-east`).
3. Once created, copy the **connection string** under "Connection details". It looks like:
   ```
   postgresql://username:password@host.neon.tech/dbname?sslmode=require
   ```
4. Save this string somewhere safe — you'll paste it into Render in step 6.

Free tier limits: 0.5 GB storage, 191 compute hours/month. The recipe app uses kilobytes per recipe, so storage is a non-issue.

### 5. Create the Render web service

1. Sign up at <https://render.com> (GitHub auth recommended).
2. **New → Web Service**.
3. Connect your GitHub account and select the `CookingAI` repo.
4. Configure:
   - **Name**: `cookingai` (this becomes `cookingai.onrender.com` — pick something unique)
   - **Region**: same as Neon (e.g. `Ohio` if Neon is in `us-east-2`)
   - **Branch**: `main`
   - **Root Directory**: *leave blank* (repo root)
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```
     pip install -r requirements.txt && cd cookingai && python manage.py collectstatic --no-input && python manage.py migrate && python manage.py seed_examples
     ```
   - **Start Command**:
     ```
     gunicorn --chdir cookingai cookingai.wsgi
     ```
   - **Instance Type**: `Free`
5. **Do not click Deploy yet** — finish step 6 first, otherwise the first deploy fails.

### 6. Set environment variables in Render

In the same Render service page, scroll to **Environment Variables** and add:

| Key | Value |
|---|---|
| `SECRET_KEY` | (the string from step 3) |
| `ANTHROPIC_API_KEY` | (your real Anthropic key, starts with `sk-ant-`) |
| `DATABASE_URL` | (the Neon connection string from step 4) |
| `ALLOWED_HOSTS` | `cookingai.onrender.com` (or whatever your actual Render URL is) |
| `DEBUG` | `false` |
| `USE_FAKE_GENERATOR` | `false` |

Click **Create Web Service**. The first deploy will start.

### 7. Verify

1. Watch the build log in Render. Expected sequence: `pip install` → `collectstatic` → `migrate` → `seed_examples` (this last step makes 3 Anthropic API calls, ~$0.50 total — one-time). First deploy takes 5–8 minutes.
2. Once build shows `Live`, visit `https://cookingai.onrender.com`. The home page should load and the three Featured Examples should be visible.
3. Click an example → cached recipe loads instantly.
4. Paste a *new* YouTube cooking-video URL → wait ~15s → recipe page renders.
5. Submit 4 different URLs from the same browser within a minute — the 4th should hit the rate limit (3 per IP per day) and show a friendly "slow down" page.

If any of these fail, see **Troubleshooting** below.

### 8. (Optional) Custom domain

Skip if `cookingai.onrender.com` is fine.

1. Buy a domain (~$10/year on Namecheap or Cloudflare).
2. In Render: **Settings → Custom Domains → Add**. Enter your domain.
3. Render shows you a CNAME target. Add it at your registrar.
4. Wait ~10 minutes for DNS to propagate. Render auto-provisions HTTPS via Let's Encrypt.
5. Update the `ALLOWED_HOSTS` env var to include the new domain.

---

## What happens automatically (no action needed)

- **Migrations run on every deploy** (in the build command). Idempotent — Django only applies pending ones.
- **Example recipes are seeded once** by `seed_examples`. The command is idempotent — subsequent deploys see them already cached and skip the API calls.
- **Static files are served by WhiteNoise** baked into Django. No separate CDN needed.
- **Rate limiting**: 3 recipe generations per IP per day. Anyone exceeding it sees a 429 page until midnight UTC. Cached recipes (the 3 examples and anything previously generated) load freely.
- **HTTPS** is provisioned by Render automatically — no certs to manage.
- **Logs** are visible in Render's dashboard → your service → Logs tab.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails on `pip install` | Python version mismatch | Add `runtime.txt` with `python-3.13.0` (or whatever you tested locally) |
| Build fails on `migrate` | `DATABASE_URL` wrong format | Re-copy from Neon, make sure `?sslmode=require` is on the end |
| Build fails on `seed_examples` | `ANTHROPIC_API_KEY` not set or invalid | Check the env var; regenerate the key if needed |
| Home page returns "DisallowedHost" | `ALLOWED_HOSTS` doesn't include your URL | Add the Render domain to the env var (comma-separated if multiple) |
| Site loads but no examples shown | First deploy hadn't run `seed_examples` yet | Trigger a manual redeploy from Render's dashboard |
| 502 on every recipe submit | `ANTHROPIC_API_KEY` wrong, or you hit the $5 cap | Check the key, check Anthropic Console usage |
| 429 on first submission | Rate limit triggered before you tested | Wait until midnight UTC, or raise the limit (in code — ask Claude) |
| Cold start every visit | Free tier sleeps after 15 min idle | Expected. Upgrade to Render Starter ($7/mo) to eliminate. |

---

## Costs and limits — summary

| Service | Free tier limit | Cost above |
|---|---|---|
| **Render web** | 750 hrs/mo, sleeps after 15 min idle, 30s cold start | Starter $7/mo (no sleep) |
| **Neon Postgres** | 0.5 GB storage, 191 compute hrs/mo | Launch $19/mo |
| **Anthropic API** | Capped at $5/mo per your spending limit (step 1) | You set the cap |
| **Total maximum** | **$5/month** | |

If you start seeing serious traffic, the upgrade order is:
1. Raise Anthropic cap (~$10–20/mo for ~100 generations/day)
2. Render Starter (eliminate cold starts) — $7/mo
3. Neon Launch (more compute hours) — $19/mo

You will not accidentally cross any of these thresholds — both Render and Neon require an explicit plan upgrade in their UIs.
