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

## TestFlight (share the iPhone app with other people)

Same pipeline as the Rize app: no Xcode IDE, no EAS, no cloud signing. Everything is driven by the App Store Connect API key you already have.

| Setting | Value (defaults baked into the scripts) |
|---------|------------------------------------------|
| Team ID | `A58FFUY6DF` |
| Bundle ID | `com.kurbaitaev.tvremote` |
| API key | `~/.appstoreconnect/private_keys/AuthKey_AQZ687BDBN.p8` (the Rize key) |
| Profile | `TV Remote App Store` (created automatically) |

**One manual step, once:** App Store Connect → **Apps → + → New App** → iOS, name "TV Remote", bundle ID `com.kurbaitaev.tvremote` (register it under **Identifiers** first if the dropdown does not list it, or just run the script once — it registers the bundle ID through the API), SKU `tvremote`. Apple exposes no API for creating the app record, so this is the only click required.

### From your Mac

```bash
cd ~/hisense-remote
./scripts/testflight.sh
```

What it does:

1. `scripts/apple_signing.py` registers the bundle ID if needed, finds the Apple Distribution certificate already in your keychain (the one Rize uses), and creates + installs an App Store provisioning profile for TV Remote.
2. `cap sync ios`, then an **unsigned** archive with the release Xcode command-line tools (`/Applications/Xcode.app`; override with `DEVELOPER_DIR`). Automatic signing is avoided on purpose — it fails on a team with no registered devices.
3. Export a signed `.ipa` with that certificate + profile.
4. `xcrun altool --upload-app` with the API key.

The build shows up in App Store Connect → TestFlight after processing (5–15 min). Internal testers need no review; external testers need a short Beta App Review.

Options: `SKIP_UPLOAD=1` (just produce `mobile/ios/build/export/App.ipa`), `BUILD_NUMBER=42` (default: timestamp), `MARKETING_VERSION=1.0.1`, `CREATE_CERT=1` (make a new distribution certificate through the API if the keychain has none).

### From GitHub Actions (no Mac needed)

The **iOS TestFlight** workflow (`.github/workflows/ios-testflight.yml`) runs the same script on a macOS runner. It needs one repository secret, `ASC_KEY_P8`, containing the text of `AuthKey_AQZ687BDBN.p8`. Run it from the **Actions** tab or push a `v*` tag. The build number is the workflow run number.

The runner has no keychain with your distribution key, so it creates a distribution certificate through the API on a throwaway keychain each run. Apple limits distribution certificates per team (currently 3), so prefer the Mac script for routine uploads and revoke stale CI certificates under **Certificates, Identifiers & Profiles** if the workflow ever reports the limit.

### What was fixed for App Store / TestFlight

- The `RokuDiscover` plugin lives in the app target, so `cap sync` never registers it. `ViewController.swift` now registers it in `capacitorDidLoad()` — without this the app said "RokuDiscover plugin missing".
- `UIRequiredDeviceCapabilities` was `armv7` (App Store Connect rejects it); now `arm64`.
- `NSAllowsArbitraryLoads` removed — `NSAllowsLocalNetworking` is all the LAN HTTP calls need, and App Review asks for a justification otherwise.
- `ITSAppUsesNonExemptEncryption = NO` so TestFlight does not block each build on the export-compliance question.
- `PrivacyInfo.xcprivacy` added (required-reason API declaration for UserDefaults).
- Shared `App` scheme added so `xcodebuild` works headlessly.

## Android

```bash
cd ~/hisense-remote/mobile
npm run android
# Android Studio → Run on device
```

The **Mobile CI** workflow builds a debug APK on every push touching `mobile/` — download it from the workflow run's artifacts.

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
