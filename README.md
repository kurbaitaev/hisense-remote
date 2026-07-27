# TV Remote — free Roku / Hisense remote

Control Roku TVs (including Hisense Roku) without a paid App Store remote.

## Research: how other projects do it

Open-source remotes all use **Roku ECP discovery**, not a website scan:

| Project | What it is |
|---------|------------|
| [Roam](https://github.com/msdrigg/Roam) | Production Swift remote — SSDP as soon as you open the app |
| [RoMote](https://github.com/wseemann/RoMote) | Android remote — MulticastLock + ECP |
| [grahamplata/roku-remote](https://github.com/grahamplata/roku-remote) | Go CLI `find` via SSDP |
| [matthewdowney/roku](https://github.com/matthewdowney/roku) | Classic Java M-SEARCH `roku:ecp` |

```
UDP multicast SSDP
  → 239.255.255.250:1900
  → M-SEARCH … ST: roku:ecp
  → LOCATION: http://192.168.x.x:8060/
→ keys: POST /keypress/…
```

**Websites cannot do SSDP.** Native code can. That’s `mobile/`.

---

## Phone app (finds TV like official apps)

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

1. Install **Xcode** from the Mac App Store if needed  
2. Xcode → select your **iPhone** → **Signing** (Apple ID) → **Run ▶**  
3. **Allow Local Network**  
4. Power TV on → app finds it via SSDP  

Details: **[mobile/README.md](./mobile/README.md)**

---

## Website only (buttons; weak auto-find in Safari)

**https://kurbaitaev.github.io/hisense-remote/**

Fine after you already know the TV IP. Safari cannot match native SSDP.

---

## Optional: Mac LAN helper

With the Python server on your Mac (`./start.sh`), phone can open:

- `http://<mac-ip>:8080/go` — redirects to remote with discovered TV  
- `http://<mac-ip>:8080/remote` — injects found TVs  

Day-to-day target is still the **native app** (no Mac required).

---

## License

MIT — see [LICENSE](LICENSE).
