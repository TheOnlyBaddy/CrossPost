# Deploying Cross Post

Four services, each doing one thing:

| Service | Holds | Cost |
| --- | --- | --- |
| **Render** | the backend process. Stores nothing | free tier works |
| **Vercel** | the built frontend, and the proxy in front of the API | free |
| **MongoDB Atlas** | users, sessions, connected accounts, posts | free M0, 512 MB |
| **Cloudflare R2** | the video files | free to 10 GB, no egress charge |

Render holding no state is the point: nothing is lost when it redeploys, and
the free instance becomes usable.

> **Status:** the MongoDB half is built and tested. **R2 is not implemented
> yet** — the backend still writes videos to local disk. Read Step 0 before
> deploying, because that decides whether the free tier works for you today.

---

## What changes, compared to running locally

| Locally | Deployed |
| --- | --- |
| Cloudflare tunnel gives a public HTTPS URL | **The tunnel is gone.** Vercel's own domain is the public URL |
| Hostname changes every restart, so four redirect URIs churn | Stable hostname. Register the redirect URIs **once** |
| `backend/.env` | Environment variables, or one secret file, in the Render dashboard |
| Vite dev server proxies `/api` to port 8000 | Vercel rewrites `/api` to Render |
| MongoDB on localhost | Atlas |

The tunnel existed only so Meta could reach a public HTTPS address.
Deployment provides one, so drop it from your mental model of production.
`scripts/dev.py` stays for local work.

---

## Step 0 — Where the videos live

The database question is settled: Atlas. The remaining one is the videos,
because Instagram **fetches** the file over public HTTPS when a post fires,
possibly hours after the upload. It has to still exist, at a public address.

Render's own docs are explicit (checked 2026-11-15): free web services **lose
local filesystem changes on redeploy** and **cannot attach a persistent disk**
— that is a paid-plan feature. An uptime monitor prevents the 15-minute
inactivity spin-down; it does not prevent a redeploy.

| Option | Cost | Status |
| --- | --- | --- |
| **A. R2** | free to 10 GB | **Not built yet.** Needs the upload path, `public_media_url` and the YouTube publisher changed |
| **B. Paid Render instance + disk** | ~$7/mo, check current pricing | Works with today's code. One env var: `DATA_DIR=/var/data` |
| **C. Free instance, no disk** | $0 | Videos vanish on every redeploy. Fine for a first smoke test, useless for scheduled posts |

If you are deploying today, **B** is the only option that fully works. Once R2
lands you can drop to the free instance and delete the disk.

A disk also pins the service to a single instance — Render will not scale a
service that has one. That suits this app: the scheduler runs inside the web
process, so a second instance would publish every scheduled post twice.

---

## Step 1 — MongoDB Atlas

1. **cloud.mongodb.com** → sign up → create an organisation and project.
2. **Create a cluster** → **M0 / Free**. Pick the region nearest your Render
   region; a cluster in Mumbai with a backend in Oregon pays for the distance
   on every query.
3. **Database user** (Security → Database Access): a generated password, role
   *Read and write to any database*. Avoid `@ : / ?` in it — they are
   connection-string delimiters and would need percent-encoding.
4. **Network access** (Security → Network Access): **Allow access from
   anywhere**, `0.0.0.0/0`. Render has no static outbound IP on normal plans,
   so an allowlist cannot work. The password is then the only thing guarding
   the cluster, so make it long.
5. **Connect → Drivers → Python** gives you:

   ```
   mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
   ```

The app creates its own collections and indexes on first start. There is no
migration to run.

---

## Step 2 — Prepare the repo

### 2.1 Pin the Python version

Create `backend/runtime.txt`, so Render matches local:

```
python-3.11.9
```

### 2.2 Push

Render and Vercel both deploy from GitHub, so nothing ships until it is
pushed.

```bash
git add -A && git commit -m "Prepare for deployment" && git push
```

---

## Step 3 — Deploy the backend on Render

1. **render.com → New → Web Service → Build and deploy from a Git repository**
2. Connect GitHub and pick **TheOnlyBaddy/CrossPost**
3. Fill in:

   | Field | Value |
   | --- | --- |
   | Name | `crosspost-api` |
   | Region | match your Atlas region |
   | Branch | `main` |
   | Root directory | `backend` |
   | Runtime | Python 3 |
   | Build command | `pip install -r requirements.txt` |
   | Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
   | Instance type | Free works once R2 lands; **Starter** if you need the disk today |
   | Health Check Path | `/api/health`, or leave it blank. Render's `/healthz` placeholder is not a route this app serves, so typing it in makes every check 404 |

   `--host 0.0.0.0` matters: the default `127.0.0.1` is unreachable from
   outside the container. `$PORT` is set by Render; do not hardcode 8000.

4. **Only for option B**, add a disk (Advanced → Add Disk): name `data`, mount
   path `/var/data`, 5 GB. **If you cannot see that option**, the instance
   type is still Free — the Advanced section hides it. Pick a paid plan, or
   add the disk afterwards from the service's **Disks** tab.

5. Deploy, and copy the service URL. Below it is `<API>`.

---

## Step 4 — Deploy the frontend on Vercel

The frontend calls `/api/...` as a relative path. Keep it that way: point
Vercel at Render with a rewrite, so the browser only ever talks to **one
origin**. That avoids cross-site cookies entirely, which is the single biggest
source of "it works locally but not deployed".

Create `frontend/vercel.json`:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://<API>/api/:path*" },
    { "source": "/media/:path*", "destination": "https://<API>/media/:path*" }
  ]
}
```

Drop the `/media` rewrite once videos come from R2 — they will be served from
R2's own domain by then.

Then:

1. **vercel.com → Add New → Project**, import the same repo
2. Framework **Vite**, root directory `frontend`, build `npm run build`,
   output `dist`
3. Deploy, and copy the URL. Below it is `<APP>`.

---

## Step 5 — Environment variables on Render

Render dashboard → your service → **Environment**.

**Shortcut:** with the root directory set to `backend`, Advanced → **Secret
Files** → a file named `.env` lands exactly where `config.py` already reads
it, so you can paste your whole local `.env` in one go — after changing the
URLs below.

| Key | Value | Notes |
| --- | --- | --- |
| `MONGO_URL` | the `mongodb+srv://...` string | Password included, percent-encoded if it has odd characters |
| `MONGO_DB` | `crosspost` | |
| `PUBLIC_BASE_URL` | `<APP>` | **The Vercel URL, not the Render one** — see below |
| `FRONTEND_ORIGIN` | `<APP>` | Where OAuth callbacks send the browser back to |
| `TOKEN_ENCRYPTION_KEY` | the key from your local `.env` | Reuse it, or every stored token reads as disconnected |
| `GOOGLE_CLIENT_ID` | from Google Cloud | |
| `GOOGLE_CLIENT_SECRET` | from Google Cloud | |
| `META_APP_ID` | from Meta | |
| `META_APP_SECRET` | from Meta | |
| `GRAPH_API_VERSION` | `v27.0` | |
| `YOUTUBE_PRIVACY_STATUS` | `private` until you decide otherwise | |
| `DATA_DIR` | `/var/data` | **Only for option B.** Drop it once media is on R2 |

### Why `PUBLIC_BASE_URL` is the Vercel URL

Everything the outside world touches goes through that one hostname:

- OAuth providers redirect to `<APP>/api/auth/...`, Vercel forwards it to
  Render, and the session cookie is set for `<APP>` — the same origin the app
  runs on. If the callback landed on `onrender.com`, the cookie would belong
  to the wrong site and you would be signed out the instant you signed in.
- Instagram fetches `<APP>/media/<file>`, forwarded to Render.

Once media is on R2 the second line stops being true and videos are fetched
straight from R2, which also removes the risk of a large file timing out
inside Vercel's proxy.

---

## Step 6 — Update the provider consoles

The hostname is stable now, so this is the last time.

**Google Cloud → Credentials → your OAuth client → Authorized redirect URIs:**

```
<APP>/api/auth/youtube/callback
<APP>/api/login/google/callback
```

**Meta → Facebook Login → Settings → Valid OAuth Redirect URIs:**

```
<APP>/api/auth/meta/callback
<APP>/api/login/meta/callback
```

Keep the localhost entries so local development still works. In Meta, **App
Domains** (Settings → Basic) should list your Vercel domain, and a **Privacy
Policy URL** is required before the app can leave Development mode.

---

## Step 7 — Keep it awake

Only needed on a free instance. Point UptimeRobot at:

```
<API>/api/health
```

Every 5 minutes, HTTP(S) type. Use the **Render** URL, not the Vercel one, so
you are pinging the thing that sleeps.

A monitor prevents the inactivity spin-down. It does not prevent a redeploy,
so it is not a substitute for Step 0.

---

## Step 8 — Verify, in this order

Each step depends on the one above, so a failure tells you where to look.

1. **Backend alive and talking to Atlas**

   ```bash
   curl -s <API>/api/health
   ```

   Expect `"ok": true`. If the service failed to boot, the logs say
   `Cannot reach MongoDB at ...` — that is `MONGO_URL` or the Network Access
   list. The password is masked in that message.

2. **Through Vercel** — `<APP>/api/health` returns the same JSON. A 404 means
   the rewrite in `vercel.json` is wrong or was not deployed.

3. **Sign up** at `<APP>`. Landing back on the login page means the session
   cookie is not sticking — check `PUBLIC_BASE_URL` is the Vercel URL.

4. **Check Atlas.** Browse Collections should show `users` and `sessions`
   with rows in them. That proves the whole write path end to end.

5. **Connect YouTube.** `redirect_uri_mismatch` means Step 6 is incomplete.

6. **Post one short video** to YouTube only, scheduled two minutes out. This
   proves the scheduler fires on the deployed instance.

7. **Then** try Instagram, the only leg that needs your media to be publicly
   fetchable.

8. **Redeploy, then reload.** Your account and connections survive, because
   they live in Atlas. Your *videos* survive only on option B.

---

## Known gaps in the deployed setup

- **R2 is not built.** Until it is, videos live on the Render filesystem and
  need a paid disk to survive a deploy.
- **The session cookie is `secure=False`** so that localhost works. In
  production it should be `True` — one line in
  `backend/app/routers/session.py`, ideally driven by an env var.
- **The scheduler runs inside the web process.** Never scale past one
  instance, or every scheduled post publishes twice.
- **Atlas M0 is 512 MB and shared-tier**, with connection limits and no
  dedicated resources. Plenty for this data, not for the videos.
- **Meta App Review and Google verification** still gate other people's
  accounts. Deploying changes nothing there.
