# TV Remote — native iPhone / Android app

## Why not just a website?

Official apps (and open-source remotes like [Roam](https://github.com/msdrigg/Roam), [RoMote](https://github.com/wseemann/RoMote), [matthewdowney/roku](https://github.com/matthewdowney/roku)) find TVs with:

```
SSDP M-SEARCH → 239.255.255.250:1900
ST: roku:ecp
→ LOCATION: http://192.168.x.x:8060/
```

Then they send ECP keys over HTTP.

**Safari websites cannot send SSDP (no UDP) and iPhone blocks free LAN scanning from public HTTPS pages.**  
A thin native shell fixes that — same UI, real discovery.

## What we implemented

| Piece | Role |
|--------|------|
| `RokuDiscoverPlugin` (iOS Swift) | SSDP `roku:ecp` + HTTP subnet fallback |
| `RokuDiscoverPlugin` (Android Java) | Same + multicast lock |
| `www/index.html` | Remote UI; calls `RokuDiscover.scan()` |
| CapacitorHttp | Native HTTP for keys (no CORS) |
| Info.plist / Manifest | Local Network + cleartext LAN HTTP |

## Install on your iPhone (free personal build)

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

In **Xcode**:

1. Connect iPhone  
2. Select device → **Signing** → your Apple ID  
3. **Run ▶**  
4. Phone: trust developer if asked  
5. Open **TV Remote** → **Allow Local Network**  
6. **Find my TV**

No App Store fee for installs on your own devices (free Apple ID).

## Android

```bash
cd ~/hisense-remote/mobile
npm run android
# open Android Studio → Run on device
```

## Update UI after web changes

```bash
cd ~/hisense-remote/mobile
# edit www/index.html (or copy from design)
npx cap sync
```

## Research references

- [Roku External Control API](https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md) — SSDP discovery  
- [matthewdowney/roku RokuScan.java](https://github.com/matthewdowney/roku) — M-SEARCH pattern  
- [grahamplata/roku-remote](https://github.com/grahamplata/roku-remote) — Go SSDP CLI  
- [msdrigg/Roam](https://github.com/msdrigg/Roam) — production Swift Roku remote  
