# TV Remote — free web remote for Roku

Everyone uses the **same web app**.  
It only sees TVs on **the Wi‑Fi your phone is on** — so each person controls **their own** TV, never yours.

```
Phone on home Wi‑Fi ──► finds Roku on that Wi‑Fi only
```

---

## How other people use it (their TV)

### Option A — Guaranteed auto-find (recommended)

Someone at their house runs a tiny server **once** on any PC/Pi/Mac that stays on the home Wi‑Fi:

```bash
git clone https://github.com/kurbaitaev/hisense-remote.git
cd hisense-remote
docker compose up -d --build
# or without Docker:
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt && ./start.sh
```

Then **on their phone** (same Wi‑Fi):

```
http://<that-computer-ip>:8080/remote
```

or one-tap:

```
http://<that-computer-ip>:8080/go
```

The **computer** searches the network (like official apps).  
The **phone** only opens the page — and connects to **their** Roku automatically.

That’s the same path that works for you.

### Option B — Public website only (no server)

**https://kurbaitaev.github.io/hisense-remote/**

1. Same Wi‑Fi as **their** TV  
2. Tap **Find my TV**  
3. Phone tries to scan **their** network  

Works better on some Androids.  
**iPhone Safari often blocks Wi‑Fi scanning** from public websites — then use the number pad (last part of the IP) or Option A.

---

## Important: not your TV

| Person | Opens app on | Finds |
|--------|----------------|--------|
| You at home | Your Wi‑Fi | Your Roku |
| Friend at their home | Their Wi‑Fi | Their Roku |

Private IPs like `192.168.0.154` can look the same in every house — that’s normal.  
They’re only reachable **inside that house**.

---

## First time for you (right now)

Phone on your Wi‑Fi, Mac server running:

**http://192.168.0.10:8080/remote**  
or **http://192.168.0.10:8080/go**

---

## Install on Home Screen

- **iPhone:** Share → Add to Home Screen  
- **Android:** ⋮ → Add to Home screen  

No App Store. No mic required.

---

## License

MIT — see [LICENSE](LICENSE).
