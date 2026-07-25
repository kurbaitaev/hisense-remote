# TV Remote — free Roku remote (no App Store)

**Use it now:** [https://kurbaitaev.github.io/hisense-remote/](https://kurbaitaev.github.io/hisense-remote/)

A free remote control for **Roku / Hisense Roku** TVs.  
Runs in your phone browser. Talks **straight to your TV** on your home Wi‑Fi — same idea as paid App Store remotes, without paying.

```
Your phone ── same Wi‑Fi ──► Your Roku TV
```

No account. No subscription. No your neighbor’s TV — only the TV on *your* network.

---

## Use it (anyone)

1. Open **[the remote](https://kurbaitaev.github.io/hisense-remote/)** on your phone  
2. Join the **same Wi‑Fi** as your TV  
3. On the TV (once):  
   **Settings → System → Advanced system settings → Control by mobile apps → Enabled**  
4. Allow **Local Network** if the browser asks  
5. Connect (auto-find or paste IP from **Settings → Network → About**)  
6. Optional: **Share → Add to Home Screen** for a full-screen app feel  

### What you get

| | |
|--|--|
| D-pad, OK, Home, Back | ✅ |
| Volume / mute / power | ✅ |
| Play / pause / skip | ✅ |
| Netflix, YouTube, Prime, Paramount+, Disney+, Hulu | ✅ |
| Type a title → search & open | ✅ |
| App Store price | **$0** |

Works only on your home network (by design — your TV isn’t on the public internet).

---

## Share with anyone

Send this link:

```
https://kurbaitaev.github.io/hisense-remote/
```

Each person uses it with **their** phone and **their** TV.

---

## For developers

| Path | What it is |
|------|------------|
| **`web/`** | The public remote (static HTML — what GitHub Pages serves) |
| **`static/` + `server/`** | Optional home bridge: voice, mic, smarter play on *your* LAN |
| **[SHARE.md](./SHARE.md)** | Deploy / host your own copy of the static remote |

### Run the optional voice bridge (your house only)

```bash
git clone https://github.com/kurbaitaev/hisense-remote.git
cd hisense-remote
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json   # set "host" to your TV IP
./start.sh
```

Phone: `https://<your-computer-ip>:8443`

### Update the public site after editing `web/`

```bash
git subtree split --prefix web -b gh-pages
git push origin gh-pages --force
```

---

## TV requirement

**Control by mobile apps → Enabled**  
(Settings → System → Advanced system settings)

Without that, the TV rejects remote commands (same as official apps).

---

## Privacy

- The web remote stores your TV IP in **your browser** only.  
- Commands go **phone → TV**. Nothing is sent to a central control server.  
- GitHub Pages only hosts the HTML/JS files.

---

## License

MIT — see [LICENSE](LICENSE).
