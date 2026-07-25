# TV Remote — free Roku remote on your phone

**Open it:** [https://kurbaitaev.github.io/hisense-remote/](https://kurbaitaev.github.io/hisense-remote/)

A free remote for **Roku / Hisense Roku** TVs.  
Use it in the browser, then **Add to Home Screen** so it feels like an app — without paying for one in the App Store.

No account. No subscription. Your phone talks to **your** TV on **your** Wi‑Fi.

---

## Install on your phone (main path — no mic)

### 1. TV setup (once)

On the TV:

**Settings → System → Advanced system settings → Control by mobile apps → Enabled**

### 2. Open the remote

On your **phone** (same Wi‑Fi as the TV):

**https://kurbaitaev.github.io/hisense-remote/**

- Allow **Local Network** if the browser asks  
- Wait for auto-connect, or enter the TV IP from  
  **Settings → Network → About**

### 3. Add to Home Screen (install)

This makes it open full-screen like a normal app.

**iPhone (Safari)**  
1. Tap the **Share** button  
2. Tap **Add to Home Screen**  
3. Tap **Add**  
4. Open **TV Remote** from your home screen  

**Android (Chrome)**  
1. Tap the menu **⋮**  
2. Tap **Add to Home screen** / **Install app**  
3. Confirm  
4. Open **TV Remote** from your home screen  

You do **not** need the App Store. You do **not** need a microphone.

### What you can do

| | |
|--|--|
| D-pad, OK, Home, Back | ✅ |
| Volume / mute / power | ✅ |
| Play / pause / skip | ✅ |
| Open Netflix, YouTube, Prime, etc. | ✅ |
| Type a title → search on the TV | ✅ |
| Microphone / voice | Optional (advanced) |

---

## Share with anyone

Send this link. Each person installs it for **their** TV:

```
https://kurbaitaev.github.io/hisense-remote/
```

---

## Optional: voice features (advanced)

Buttons and “Play …” by typing work with the web remote alone.

**Voice / microphone** is extra and only if you run the home server on a Mac/Pi on your network:

```bash
git clone https://github.com/kurbaitaev/hisense-remote.git
cd hisense-remote
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json   # set "host" to your TV IP
cp .env.example .env                 # optional GROQ_API_KEY for mic
./start.sh
```

Then open `https://<your-computer-ip>:8443` on your phone (HTTPS required for mic).

Most people never need this.

---

## For developers

| Path | Purpose |
|------|---------|
| **`web/`** | Public remote (what people install on their phone) |
| **`server/`** | Optional voice bridge on your LAN |
| **[SHARE.md](./SHARE.md)** | Host your own copy of the static remote |

Update the public site after editing `web/`:

```bash
git subtree split --prefix web -b gh-pages
git push origin gh-pages --force
```

---

## Privacy

- TV IP is saved in **your browser** only  
- Commands go **phone → TV** (no central control server)  
- GitHub Pages only hosts the HTML/JS  

---

## License

MIT — see [LICENSE](LICENSE).
