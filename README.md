# TV Remote — free Roku remote

Control Roku / Hisense Roku TVs without a paid App Store remote.

## How apps find TVs (research)

Open-source and official remotes all use the same **Roku ECP discovery**:

```
UDP multicast SSDP
  → 239.255.255.250:1900
  → M-SEARCH … ST: roku:ecp
  → response LOCATION: http://192.168.x.x:8060/
```

Then keys go to `http://TV-IP:8060/keypress/...`.

Examples: [Roam](https://github.com/msdrigg/Roam), [RoMote](https://github.com/wseemann/RoMote), [matthewdowney/roku](https://github.com/matthewdowney/roku), [grahamplata/roku-remote](https://github.com/grahamplata/roku-remote).

**Websites cannot do SSDP.** A native shell can. That’s what `mobile/` is.

---

## Use the phone app (finds TV like official apps)

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

1. Xcode → select your **iPhone** → **Run ▶**  
2. Allow **Local Network**  
3. Power TV on → **Find my TV**  

Details: **[mobile/README.md](./mobile/README.md)**

---

## Website only (buttons; find limited on iPhone Safari)

**https://kurbaitaev.github.io/hisense-remote/**

Fine for control after you have an IP. Auto-find is unreliable in Safari (browser rules).

---

## License

MIT — see [LICENSE](LICENSE).
