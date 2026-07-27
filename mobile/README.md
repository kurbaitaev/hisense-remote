# TV Remote — native iPhone / Android app

## Research: how free remotes find your TV

Every serious open-source Roku remote uses the same stack as the official apps:

| Project | Stack | Discovery |
|---------|--------|-----------|
| [msdrigg/Roam](https://github.com/msdrigg/Roam) | Swift (App Store) | SSDP bind → `ST: roku:ecp`, continuous re-send |
| [wseemann/RoMote](https://github.com/wseemann/RoMote) | Android | MulticastLock + SSDP + ECP HTTP |
| [grahamplata/roku-remote](https://github.com/grahamplata/roku-remote) | Go CLI | `roku-remote find` via SSDP |
| [matthewdowney/roku](https://github.com/matthewdowney/roku) | Java | M-SEARCH → LOCATION → ECP |
| [jcarbaugh/python-roku](https://github.com/jcarbaugh/python-roku) | Python | SSDP + ECP REST |

Protocol (Roku External Control API):

```
UDP M-SEARCH → 239.255.255.250:1900
ST: roku:ecp
→ LOCATION: http://192.168.x.x:8060/
→ POST http://TV:8060/keypress/Home
```

**Safari / GitHub Pages cannot do SSDP** (no raw UDP).  
This folder is a Capacitor shell: same UI + real native discovery.

## What we built

| Piece | Role |
|--------|------|
| `RokuDiscoverPlugin` (iOS Swift) | Bind UDP, M-SEARCH burst + re-send, LOCATION + sender IP, HTTP /24 fallback, `probe` for reconnect |
| `RokuDiscoverPlugin` (Android Java) | Same + MulticastLock (required on Android) |
| `www/index.html` | Remote UI; auto-scan on launch; saved-TV reconnect |
| CapacitorHttp | Native HTTP for keys (no CORS) |
| Info.plist / Manifest | Local Network + cleartext LAN HTTP |

## Install on your iPhone (free personal build)

**You need full Xcode from the Mac App Store** (Command Line Tools alone are not enough).

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

In **Xcode**:

1. Connect iPhone (cable)  
2. Select your **iPhone** as run target  
3. **Signing & Capabilities** → Team → your free Apple ID  
4. **Run ▶**  
5. Phone: trust developer if asked  
6. Open **TV Remote** → **Allow Local Network**  
7. App auto-searches (or tap **Find my TV**)

No App Store fee for installs on your own devices.

### TV setting (if keys do nothing)

On the Roku / Hisense Roku:

**Settings → System → Advanced system settings → Control by mobile apps → Enabled**

## Android

```bash
cd ~/hisense-remote/mobile
npm run android
# Android Studio → Run on device
```

## Update UI after editing www/

```bash
cd ~/hisense-remote/mobile
npx cap sync
```

Do **not** copy `web/` over `www/` — the native app UI lives in `mobile/www/`.

## Verified on this network

From Mac (same Wi‑Fi as the TV), Python SSDP finds:

```text
192.168.0.154  (Roku / Hisense)
```

The phone app uses the same multicast query from native code.
