# TV Remote — free web remote for Roku

**https://kurbaitaev.github.io/hisense-remote/**

A free **web app** remote for Roku / Hisense Roku TVs.  
No App Store. No account. No microphone required.

Your phone talks to **your** TV on **your** Wi‑Fi.

---

## First time (web only)

### On your phone

1. Same **Wi‑Fi** as the TV  
2. Open **https://kurbaitaev.github.io/hisense-remote/**  
3. Power the TV **on**  
4. Tap **Find my TV**  
   - If it finds one → tap **Open**  
   - If not → use the **number pad** (last number of the TV IP)  

### Install like an app

- **iPhone:** Share → **Add to Home Screen**  
- **Android:** ⋮ → **Add to Home screen**  

---

## Make “Find my TV” work reliably

Browsers (especially Safari) limit scanning Wi‑Fi from public websites.  
For **best auto-find**, open the remote from a small server on your home network:

```bash
cd ~/hisense-remote
./start.sh
```

Then on the phone open:

```
http://<your-computer-ip>:8080/remote
```

That page can use real network discovery (`/api/scan`) and usually finds the TV in one tap.

---

## What you get

| | |
|--|--|
| D-pad, OK, Home, Back | ✅ |
| Volume / mute / power | ✅ |
| Play / pause | ✅ |
| Netflix, YouTube, Prime, Paramount+, Disney+, Hulu | ✅ |
| Type a title → search | ✅ |
| App Store price | **$0** |

---

## Optional later

- **Voice / mic** — only with the home server + API keys (not required)  
- **Native iPhone app** — experimental under `mobile/` (not required for the web remote)

---

## License

MIT — see [LICENSE](LICENSE).
