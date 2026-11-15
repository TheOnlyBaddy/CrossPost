# Getting verified: Google and Meta

Three approvals, gating different things. Do not start all three.

| | Unlocks | Needed if Cross Post is only for you |
| --- | --- | --- |
| **Google OAuth verification** | Removes the "unverified app" screen and the 100-test-user cap | No |
| **YouTube compliance audit** | Public uploads, and quota above the default | **Yes**, if you want public videos |
| **Meta Business Verification + App Review** | Other people connecting their own Page and Instagram | No |

If it stays your tool, do the **YouTube audit only** and skip the rest. The
other two exist so strangers can sign in.

Your values, used throughout:

- Vercel app: `https://cross-post-beige.vercel.app`
- Render API: `https://crosspost-funt.onrender.com`
- Meta App ID: `991385000183956`
- Google client: `478603149884-...apps.googleusercontent.com`

---

# Part 0 — What the app is missing before either review

Both reviewers check these, and neither submission can be completed without
them. None exist yet.

1. **Privacy policy page**, publicly reachable, no login
2. **Terms of service page** (Meta asks, Google likes it)
3. **Data deletion instructions page** — Meta requires a URL or callback
4. **App icon**, 1024×1024 PNG, no transparency, no rounded corners
5. **A homepage** that explains what the app does, before sign-in

Items 1–3 are static routes in the frontend and item 5 is a public landing
section. Ask and they can be built in one pass.

## Can the Vercel domain be used instead of buying one?

For everything except Google's OAuth brand verification, yes.

| Use | `cross-post-beige.vercel.app` |
| --- | --- |
| Running the app, OAuth in Testing mode | **Works today** — already proven |
| Meta: App Domains, privacy policy, redirect URIs | **Fine** |
| YouTube compliance audit | **Fine** — it wants a project number and a demo |
| Google OAuth brand verification | **Reported not to work** |

The theory says it should: `vercel.app` is on the Public Suffix List, so the
"top private domain" Google asks for is `cross-post-beige.vercel.app` itself,
and Search Console can verify it as a URL-prefix property with an HTML file
you serve. In practice Google's developer forum has people stuck on "home
page URL not registered" after exactly that, and being told to get a real
domain.

So buy a domain (about $10/year, pointed at Vercel) **only if** you are
pursuing Google verification so that strangers can sign in. For a personal
tool, and for the YouTube audit, the Vercel domain is enough.

---

# Part A — Google

## A1. Decide whether you need it at all

Cloud Console → **Google Auth Platform → Data Access**. Each scope is labelled
**sensitive** or **restricted**. Confirm yours:

- `https://www.googleapis.com/auth/youtube.upload`
- `https://www.googleapis.com/auth/youtube.readonly`

**Sensitive** means a document review. **Restricted** additionally means an
annual third-party security assessment (CASA), which costs real money and
months. YouTube scopes are normally sensitive — read the label rather than
assuming.

If you stay in Testing with yourself as a test user, stop here. The costs of
staying unverified are: at most 100 test users, a warning screen they must
click past, and **refresh tokens that expire after 7 days**, so you reconnect
weekly.

## A2. Own a domain and prove it

1. Buy a domain and point it at Vercel (Project → Settings → Domains → Add,
   then the DNS records Vercel shows you).
2. **search.google.com/search-console** → Add property → Domain → add the TXT
   record it gives you at your registrar.
3. Verify with the **same Google account** that owns the Cloud project, or the
   submission bounces.

## A3. Fill in the consent screen properly

Cloud Console → **Google Auth Platform → Branding**:

- App name: `Cross Post`
- User support email
- App logo: the 1024×1024 icon
- **Application home page**: `https://yourdomain.com`
- **Privacy policy**: `https://yourdomain.com/privacy`
- **Terms of service**: `https://yourdomain.com/terms`
- **Authorised domains**: `yourdomain.com`

Every URL must be on the verified domain, live, and reachable without signing
in.

## A4. Write the scope justification

Under **Data Access**, each sensitive scope needs a reason. Be specific and
truthful. What is actually true here:

> `youtube.upload` — the user uploads one vertical video in our app and
> chooses YouTube as a destination. We call `videos.insert` once per post to
> publish that video to the channel they connected. We do not read, modify or
> delete any other video.
>
> `youtube.readonly` — immediately after connecting, we call
> `channels.list?mine=true` once to read the channel title and id, so the UI
> can show which channel is connected. Nothing else is read.

Reviewers reject vague answers like "to integrate with YouTube".

## A5. Record the demo video

Unlisted on YouTube, 2–4 minutes, no music, no editing tricks. Show, in order:

1. The homepage on your verified domain
2. Clicking **Connect YouTube**
3. The **full OAuth consent screen**, with the scopes legible and the URL bar
   visible
4. Coming back to the app, the channel name appearing
5. Uploading a video and it reaching YouTube
6. **Disconnecting**, and where the privacy policy explains data deletion

The URL bar must be visible throughout — they check that the client id in the
consent URL is the one under review.

## A6. Submit, then wait

**Google Auth Platform → Verification Center → Prepare for verification.**
Expect weeks and at least one round of questions. Answer the same day; a
stalled thread gets closed.

## A7. The YouTube compliance audit — separate, and the one that matters

This is **not** OAuth verification. It is what unlocks public uploads, and
without it every video the API uploads is locked private regardless of what
your code asks for.

Form: **https://support.google.com/youtube/contact/yt_api_form**

It asks for your Cloud **project number** (not the client id), what the app
does, how many uploads per day you expect, and usually a demo video — the one
from A5 works. The same form covers a quota extension.

Be honest that it publishes the user's own video to their own channel.
**Expect rejection if it reads as a personal tool**; approvals favour apps
with real users. No published turnaround time.

---

# Part B — Meta

Two sequential things. App Review cannot finish without Business
Verification for these permissions.

## B1. Business Verification

**business.facebook.com → Business settings → Security Center → Start
Verification.**

You need a **real registered business**: legal name, address, phone, and a
document showing them — certificate of incorporation, business licence, utility
bill or bank statement in the business name. A personal account with no entity
cannot pass this, and it is where most individual developers stop.

Days to weeks. Mismatched details between the form and the document are the
usual rejection.

## B2. Fill in the app's basics

**App Dashboard → Settings → Basic:**

- App icon, 1024×1024
- Category (Business or Productivity)
- **Privacy Policy URL** — required
- **Terms of Service URL**
- **User Data Deletion**: instructions URL, or a callback endpoint
- **App Domains**: `cross-post-beige.vercel.app`

**Settings → Advanced:** add a Business Account, so the app is owned by the
verified business rather than by you personally.

## B3. Request each permission

**App Review → Permissions and Features.** Request Advanced Access for
exactly these five, with no extras — asking for permissions you do not use is
a rejection on its own:

| Permission | What to say it is for |
| --- | --- |
| `pages_show_list` | Listing the user's Pages so they can choose which one to post to |
| `pages_read_engagement` | Reading the chosen Page's name and linked Instagram account |
| `pages_manage_posts` | Publishing the user's video to the Page they chose |
| `instagram_basic` | Reading the Instagram professional account linked to that Page |
| `instagram_content_publish` | Publishing the user's video as a Reel to that account |

## B4. Record a screencast per permission

This is where submissions fail. Meta wants to watch a **real person using your
live app**, not a slideshow. One continuous recording covering all five is
accepted if every permission is visibly exercised:

1. Open `https://cross-post-beige.vercel.app`, sign up or sign in
2. Click **Connect Facebook & Instagram**
3. The **whole** Facebook consent dialog, with permissions legible
4. The Page picker, showing the list that `pages_show_list` returned
5. Choosing a Page, and the linked Instagram account appearing
6. Uploading a video, posting it
7. The post live on both the Page and Instagram

Also provide **test credentials** — an account in your app they can sign in
with — and make sure it works. Reviewers close submissions they cannot log
into.

## B5. Submit

**App Review → Requests → Submit.** Then switch the app from Development to
**Live** once approved. Typically days to a couple of weeks per round.

---

# Part C — While you wait, nothing is blocked for you

- **Google**: keep the app in Testing, with your account under *Test users*.
  Full functionality, warning screen, weekly reconnect.
- **Meta**: keep the app in Development mode. Everyone with a **role** on the
  app (App Dashboard → App Roles) gets full permissions with no review at
  all. Add any collaborator as a Developer or Tester.

This is why a personal tool never needs either review.

---

# Part D — Why submissions get rejected

Shared by both reviewers:

- A privacy policy that is a template, does not name the app, or does not say
  what data is collected and how to delete it
- A demo video without a visible URL bar, or showing a mock instead of the
  live app
- Requesting permissions the demo never exercises
- Test credentials that do not work
- Vague use-case text
- Google only: homepage or privacy policy not on the verified domain
- Meta only: business documents that do not match the submitted details

Fix the named issue and resubmit. Both allow it, and a second submission is
not penalised.
