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

TestFlight needs a **paid Apple Developer Program** membership ($99/year). A free Apple ID can only install on your own phone via Xcode (section above).

One-time setup in [App Store Connect](https://appstoreconnect.apple.com):

1. **Certificates, IDs & Profiles → Identifiers** → register App ID `com.tvremote.free`
2. **Apps → +** → New App → bundle ID `com.tvremote.free`, name "TV Remote"
3. Note your **Team ID** (Membership details)

### From your Mac

```bash
cd ~/hisense-remote
APPLE_TEAM_ID=ABCDE12345 ./scripts/testflight.sh
```

The script runs `cap sync`, archives a Release build with automatic signing (uses the Apple ID signed in to Xcode → Settings → Accounts), and uploads it. The build shows up in App Store Connect → TestFlight after Apple processes it (5–15 min). Add testers there (internal testers need no review; external testers need a short Beta App Review).

Options: `BUILD_NUMBER=42` (default: timestamp), `MARKETING_VERSION=1.0.1`, `SKIP_UPLOAD=1` (writes `mobile/ios/build/App.ipa` instead of uploading).

### From GitHub Actions (no Mac needed)

The **iOS TestFlight** workflow (`.github/workflows/ios-testflight.yml`) does the same on a macOS runner. Run it from the **Actions** tab (or push a `v*` tag) after adding these repository secrets:

| Secret | Where to get it |
|--------|-----------------|
| `APPLE_TEAM_ID` | App Store Connect → Membership details |
| `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` | Users and Access → Integrations → App Store Connect API → generate key (role **App Manager**). `ASC_KEY_P8` is the text of the downloaded `.p8` file |
| `IOS_DIST_CERT_P12`, `IOS_DIST_CERT_PASSWORD` | Xcode → Settings → Accounts → Manage Certificates → + Apple Distribution, then export it from Keychain Access as `.p12` and `base64 -i cert.p12 \| pbcopy` |

The build number is the workflow run number, so every run is a new TestFlight build.

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
