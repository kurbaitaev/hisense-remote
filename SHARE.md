# Free Roku remote — install on your phone

**Link:** https://kurbaitaev.github.io/hisense-remote/

Install like an app (Home Screen). **No App Store. No mic required.**  
Voice is optional and only for people who run an extra home server.

---

## How to install (send this)

> **Free TV remote for Roku** (no App Store):  
> https://kurbaitaev.github.io/hisense-remote/  
>  
> 1. Phone on the **same Wi‑Fi** as your TV  
> 2. On the TV: Settings → System → Advanced → **Control by mobile apps → Enabled**  
> 3. Open the link → connect to your TV  
> 4. **Install on phone:**  
>    - **iPhone:** Share → **Add to Home Screen**  
>    - **Android:** Menu ⋮ → **Add to Home screen**  
> 5. Open **TV Remote** from your home screen — no microphone needed  

---

## Install steps (detail)

### iPhone

1. Open the link in **Safari**  
2. Connect to your TV  
3. Share → **Add to Home Screen** → Add  
4. Launch from the home screen icon  

### Android

1. Open the link in **Chrome**  
2. Connect to your TV  
3. Menu → **Add to Home screen** / **Install app**  
4. Launch from the home screen icon  

---

## Voice (optional only)

The installed remote is **buttons + type a title to play**.

Mic / voice needs a separate computer on your network running this repo’s server. Skip it unless you want that.

---

## Host your own copy of the web remote

```bash
# After editing web/
git subtree split --prefix web -b gh-pages
git push origin gh-pages --force
```

Or Cloudflare Pages with build output = `web`.
