# TV Remote — iPhone / Android app

Native shell so the phone can **find your Roku on Wi‑Fi like official apps**  
(SSDP + Local Network). No physical remote needed — only power on the TV.

## Why the website alone can’t do this

Safari on a public HTTPS page is not allowed to search your LAN the way apps can.  
Official remotes use **native Local Network + SSDP**. This app does the same.

## Install on your iPhone (free, personal device)

Needs a Mac with Xcode (you already have this machine).

```bash
cd ~/hisense-remote
./scripts/run-ios-app.sh
```

Then in Xcode:

1. Plug in your iPhone  
2. Select your phone as the run destination  
3. **Signing & Capabilities** → choose your Apple ID team (free account works)  
4. Press **Run ▶**  
5. On iPhone: Settings → General → VPN & Device Management → Trust your developer  
6. Open **TV Remote**  
7. When asked **Local Network** → **Allow**  
8. Tap **Find my TV**

## After install

- Phone only, same Wi‑Fi as TV  
- Power TV on  
- **Find my TV** → SSDP finds it → control  

No computer after the first install. No App Store fee for personal use.

## Update the app UI later

```bash
cd ~/hisense-remote
cp web/index.html web/manifest.webmanifest mobile/www/
cd mobile && npx cap sync ios
# Run again from Xcode
```
