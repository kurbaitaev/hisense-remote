# Share with friends (their TVs, not yours)

This project is meant for **anyone with a Roku / Hisense Roku TV**.  
Each person uses the remote on **their phone → their TV** on **their Wi‑Fi**.  
Nothing goes through your Mac or your living room.

```
Friend's phone ──same Wi‑Fi──► Friend's Roku :8060
       ▲
       └── web page (HTML only, free host)
```

---

## What to send friends

One link (this project’s public remote):

```
https://kurbaitaev.github.io/hisense-remote/
```

**Friend does:**

1. Open the link on their phone  
2. Join the Wi‑Fi the TV uses  
3. Allow “Local Network” if the browser asks  
4. TV IP is found automatically, or they paste it from  
   **Settings → Network → About**  
5. Optional: Share → **Add to Home Screen**

**TV once (their house):**  
**Settings → System → Advanced system settings → Control by mobile apps → Enabled**

---

## Deploy the public page (you, once)

Friends only need the **`web/`** folder — no Python, no API keys.

### Option A — Cloudflare Pages (recommended, free)

```bash
cd ~/hisense-remote
# need: npm i -g wrangler  &&  wrangler login
npx wrangler pages deploy web --project-name=roku-remote
```

Or: Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect Git  
- **Build output directory:** `web`  
- **Build command:** (empty)

You get something like `https://roku-remote.pages.dev` — text that to friends.

### Option B — GitHub Pages (this repo)

Already live after push:

```
https://kurbaitaev.github.io/hisense-remote/
```

To refresh after editing `web/`:

```bash
git subtree split --prefix web -b gh-pages
git push origin gh-pages --force
```

### Option C — no deploy, AirDrop the file

Send `web/index.html` to their phone.  
Open it from Files (works best if they can load it; some browsers restrict `file://` → LAN).  
**Public host is more reliable.**

---

## What friends get

| Feature | Works? |
|---------|--------|
| D-pad, volume, home, back | ✅ |
| Netflix / YouTube / Paramount buttons | ✅ |
| Type a title → Play | ✅ (Roku search API) |
| Mic / voice AI | ❌ (needs a home server + keys) |
| Control *your* TV from their house | ❌ (by design) |

---

## Repo layout (what you ship)

```
web/
  index.html           ← entire remote app
  manifest.webmanifest
```

The Python server in this repo is **optional** — only if *you* want voice AI on *your* network. Friends never need it.

---

## Quick copy-paste for friends

> Open this on your phone (same Wi‑Fi as your TV):  
> **https://YOUR-SITE.pages.dev**  
>  
> If it asks, allow local network.  
> On the TV: Settings → System → Advanced → Control by mobile apps → **Enabled**.  
> Then use the remote. Add to Home Screen if you want.
