# TV Remote — free Roku remote on your phone

Control your **Roku / Hisense Roku** TV without paying for an App Store remote.  
**No mic required.** Voice is optional (advanced).

Official apps find TVs with **Local Network + SSDP**. Safari websites cannot do that.  
This project includes a free **iPhone app** (install from your Mac with Xcode) that does.

---

## First time (phone only, no physical remote)

### Install the iPhone app (once)

On your **Mac**:

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

In **Xcode**:

1. Plug in your iPhone  
2. Select your iPhone as the run target  
3. **Signing** → choose your Apple ID (free account is fine)  
4. Press **Run ▶**  
5. On the phone: trust the developer if asked  

### Use it

1. Open **TV Remote** on the iPhone  
2. When iOS asks **Local Network** → tap **Allow**  
3. Power the TV **on** (button on the set)  
4. Tap **Find my TV**  

The app finds Rokus the same way official remotes do (**SSDP** + Wi‑Fi scan).  
No TV Settings menu. No typing an IP. No second computer after install.

More detail: [mobile/README.md](./mobile/README.md)

---

## Website version (optional)

**https://kurbaitaev.github.io/hisense-remote/**

Good for buttons after you already know the TV IP.  
**Auto-find is limited** in Safari — use the **iPhone app** above for discovery.

---

## What you get

| | Website (Safari) | iPhone app |
|--|------------------|------------|
| D-pad, volume, apps, play title | ✅ | ✅ |
| Find TV without typing IP | ❌ often blocked | ✅ SSDP |
| No physical remote needed | ❌ hard | ✅ |
| App Store price | Free | Free (personal install) |

---

## Optional: voice on a home server

Only if you want mic commands on *your* network:

```bash
./start.sh
# phone: https://<mac-ip>:8443
```

Most people never need this.

---

## TV setting (once, when you have a remote)

**Settings → System → Advanced → Control by mobile apps → Enabled**

Some TVs ship with this on. If keys fail after find, enable it when you can.

---

## License

MIT — see [LICENSE](LICENSE).
