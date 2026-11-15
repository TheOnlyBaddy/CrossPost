# Cross Post

Upload a video once, publish it to YouTube, Instagram and Facebook.

React + TypeScript frontend, FastAPI backend. The backend exists because both
Google and Meta require an HTTPS redirect to a server that holds the client
secret and stores the refresh token — the browser never sees either.

## Status

Scaffold, running end to end. What is real:

- v1 format gate (9:16, 3–60s, H.264 + AAC), in the browser *and* server-side via ffprobe
- Per-platform publish state with independent retry
- Scheduling: post now or at a chosen time, with cancel and reschedule
- OAuth flows for Google and Meta, including the Meta Page picker
- Encrypted-at-rest token storage
- 85 passing tests

What is not done: nothing has been run against a real YouTube or Meta account
yet, because that needs credentials. Every API call shape marked
`TODO verify` in the source should be checked against the official docs before
you rely on it.

## Prerequisites

- Python 3.11+ (invoked as `py` on Windows)
- Node 20+
- ffmpeg/ffprobe on PATH (optional, but it is what checks codecs server-side)

## Setup

```bash
cd backend && py -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`backend/.env` already exists with a generated `TOKEN_ENCRYPTION_KEY`. Fill in
the rest from `backend/.env.example`.

```bash
cd frontend && npm install
```

## Running

Backend (port 8000):

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Frontend (port 5173, proxies `/api` and `/media` to the backend):

```bash
cd frontend && npm run dev
```

Then open http://localhost:5173. The app's Setup panel tells you what is still
missing. API docs are at http://localhost:8000/docs.

Tests:

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```

## The two things that will bite you

**1. Instagram fetches the video; it does not accept bytes.**
The Content Publishing flow is: create a container pointing at a `video_url`,
poll until it finishes, then publish. Meta pulls the file from that URL. So
`PUBLIC_BASE_URL` must be a real public HTTPS host — `localhost` will not work.
Use a Cloudflare Tunnel or ngrok in development.

This is also why an Android client would not have simplified anything: the
bytes have to transit your server either way.

*TODO verify:* whether the resumable `rupload.facebook.com` path accepts raw
bytes for Reels. If it does, this constraint disappears.

**2. YouTube uploads default to private here, on purpose.**
Projects that have not passed the YouTube API Services compliance audit
reportedly have their uploads locked to private — the call succeeds but the
video cannot be made public. `YOUTUBE_PRIVACY_STATUS` defaults to `private`
so this is not a surprise. *TODO verify* where you stand before changing it.

## Scheduling

A post is a row with a `scheduled_at`; a loop in the backend claims whatever
is due and publishes it. **"Post now" is not a special case** — it is a post
scheduled for now, so there is exactly one path from an upload to a platform.
Creating a due post nudges the loop, so there is no poll-interval delay.

Because the queue is a database table rather than in-process state, this also
fixes the old problem where a publish died with the server. On startup:

- targets claimed but not started go back in the queue
- targets that were mid-upload are **failed, not retried** — the bytes may
  already have reached the platform, and a silent duplicate upload is worse
  than a message asking you to check

**The server has to be running at the scheduled moment.** There is no cloud
component. If it misses a slot by more than `SCHEDULER_MAX_CATCHUP_MINUTES`
(default 60), the post fails with an explanation instead of going out late —
posting a day-old video without warning is the worse failure. Set it to `0`
to always publish late.

Timezones: the browser converts your local picker value to a UTC instant, so
the server never guesses what "09:00" meant. Everything is stored and compared
in one canonical UTC format.

| Endpoint | |
|---|---|
| `POST /api/posts` | `scheduledAt` empty = now, otherwise a UTC ISO instant |
| `POST /api/posts/{id}/cancel` | cancels only legs that have not gone out |
| `POST /api/posts/{id}/reschedule` | moves a post that has not fired yet |
| `POST /api/posts/{id}/retry/{platform}` | one platform, immediately |

## Rate limits, verified 2026-11-14

Both of the commonly cited numbers are wrong. Check them yourself before
relying on either.

| | Limit | Source |
|---|---|---|
| YouTube | **~100 uploads/day per Cloud project.** `videos.insert` has its own bucket: 100 calls/day at 1 unit each. | [Quota calculator](https://developers.google.com/youtube/data/determine_quota_cost) |
| Instagram | **100 API-published posts per rolling 24h per account.** | [Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing) |

The widely repeated "10,000 units ÷ 1,600 per upload = ~6 uploads/day" for
YouTube no longer matches the official quota calculator. The "25 posts/day"
figure for Instagram appears equally stale.

Note the YouTube limit is **per project, not per user**. Fine for personal use;
it becomes the hard ceiling if other people ever connect their own accounts.

## Still to decide

**Is this just for you, or for other people too?** It is the biggest fork left.
Posting only to your own channel/account/Page may let you skip Google OAuth
verification, Meta App Review and Meta Business Verification entirely — Meta's
Development mode covers assets you administer yourself. Opening it to other
people means all three, and that is weeks of queueing. *Verify both shortcuts
against the official docs before counting on them.*

## Layout

```
backend/
  app/
    config.py       settings + .env loading (anchored to backend/, not cwd)
    models.py       Platform, TargetState, PublishResult
    validation.py   the v1 format gate (pure functions + ffprobe wrapper)
    schedule_input.py  parsing and bounds-checking a requested publish time
    store.py        SQLite; OAuth tokens encrypted with Fernet
    scheduler.py    the publish worker: claims due work, survives restarts
    publishing.py   fan-out; one platform failing never affects another
    platforms/      one adapter per platform
    routers/        auth (OAuth) and posts (upload, status, schedule, retry)
  tests/            85 tests, no network
frontend/
  src/
    api.ts          typed client; XHR upload for progress
    datetime.ts     local <-> UTC conversion; relative time
    probeVideo.ts   browser-side dimension/duration check
    components/     SetupBanner, Connections, Composer, PostCard
```

## Design note: partial success is the normal case

YouTube succeeding while Instagram fails is routine, not an error. So there is
no global "posted!" state anywhere — each platform has its own row, its own
error, and its own retry button, and retrying one never re-uploads to the
others. The full platform error body is stored on every failure, because these
APIs fail with opaque codes.

## Not in v1

Recurring slots and a fill-the-queue model (the Buffer approach) · per-platform
captions · per-platform scheduled times · thumbnails · multiple accounts per
platform · transcoding or aspect conversion · analytics · drafts · multi-user ·
Twitch/Snapchat/Kick.

The scheduler is one loop inside the API process, which is right for a
single-user app. Running more than one replica would want a real queue
instead — the claim is per target so it would not double-post, but that is
not a design to lean on.
