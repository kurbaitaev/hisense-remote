#!/usr/bin/env bash
# Archive the iOS app and upload it to TestFlight.
#
# Works on a Mac with Xcode (uses the Apple ID signed in to Xcode) and on CI
# (uses an App Store Connect API key). Requires a paid Apple Developer Program
# membership — a free Apple ID can install on your own phone but cannot use
# TestFlight.
#
# Required:
#   APPLE_TEAM_ID       10-character team ID (App Store Connect → Membership)
#
# Optional:
#   BUILD_NUMBER        CFBundleVersion. Default: UTC timestamp (always increasing)
#   MARKETING_VERSION   CFBundleShortVersionString. Default: value in the Xcode project
#   SKIP_UPLOAD=1       Export an .ipa into mobile/ios/build/ instead of uploading
#   ASC_KEY_ID          App Store Connect API key ID          (CI / headless)
#   ASC_ISSUER_ID       App Store Connect API issuer ID       (CI / headless)
#   ASC_KEY_PATH        Path to the AuthKey_XXXXXXXXXX.p8     (CI / headless)
#
# Usage:
#   APPLE_TEAM_ID=ABCDE12345 ./scripts/testflight.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOBILE="$ROOT/mobile"
IOS="$MOBILE/ios"
BUILD_DIR="$IOS/build"
ARCHIVE="$BUILD_DIR/App.xcarchive"
EXPORT_PLIST="$BUILD_DIR/ExportOptions.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: iOS archives can only be built on macOS with Xcode installed." >&2
  exit 1
fi
if ! xcode-select -p >/dev/null 2>&1 || [[ ! -d "$(xcode-select -p)/Platforms/iPhoneOS.platform" ]]; then
  echo "error: full Xcode is required (Command Line Tools alone cannot build iOS apps)." >&2
  echo "       Install Xcode from the Mac App Store, then: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  exit 1
fi
if [[ -z "${APPLE_TEAM_ID:-}" ]]; then
  echo "error: APPLE_TEAM_ID is not set (App Store Connect → Membership details → Team ID)." >&2
  exit 1
fi

BUILD_NUMBER="${BUILD_NUMBER:-$(date -u +%Y%m%d%H%M)}"
DESTINATION="upload"
[[ "${SKIP_UPLOAD:-0}" == "1" ]] && DESTINATION="export"

AUTH_ARGS=()
if [[ -n "${ASC_KEY_ID:-}" && -n "${ASC_ISSUER_ID:-}" && -n "${ASC_KEY_PATH:-}" ]]; then
  AUTH_ARGS=(
    -authenticationKeyPath "$ASC_KEY_PATH"
    -authenticationKeyID "$ASC_KEY_ID"
    -authenticationKeyIssuerID "$ASC_ISSUER_ID"
  )
fi

VERSION_ARGS=("CURRENT_PROJECT_VERSION=$BUILD_NUMBER")
[[ -n "${MARKETING_VERSION:-}" ]] && VERSION_ARGS+=("MARKETING_VERSION=$MARKETING_VERSION")

echo ""
echo "  TV Remote — TestFlight build"
echo "  ────────────────────────────"
echo "  Team:         $APPLE_TEAM_ID"
echo "  Build number: $BUILD_NUMBER"
echo "  Destination:  $DESTINATION"
echo ""

echo "==> Installing npm packages and syncing web assets into the iOS project"
cd "$MOBILE"
if [[ -f package-lock.json ]]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
npx cap sync ios

echo "==> Archiving (Release)"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
xcodebuild archive \
  -project "$IOS/App/App.xcodeproj" \
  -scheme App \
  -configuration Release \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates \
  ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} \
  DEVELOPMENT_TEAM="$APPLE_TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  "${VERSION_ARGS[@]}" \
  | tee "$BUILD_DIR/archive.log" | grep -E "error:|warning: .*deprecated|\*\* ARCHIVE" || true
[[ -d "$ARCHIVE" ]] || { echo "error: archive failed, see $BUILD_DIR/archive.log" >&2; exit 1; }

echo "==> Exporting ($DESTINATION)"
sed -e "s/__TEAM_ID__/$APPLE_TEAM_ID/" -e "s/__DESTINATION__/$DESTINATION/" \
  "$IOS/ExportOptions.plist" > "$EXPORT_PLIST"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$EXPORT_PLIST" \
  -exportPath "$BUILD_DIR" \
  -allowProvisioningUpdates \
  ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} \
  | tee "$BUILD_DIR/export.log" | grep -E "error:|\*\* EXPORT|Upload" || true
grep -q "EXPORT SUCCEEDED" "$BUILD_DIR/export.log" || { echo "error: export failed, see $BUILD_DIR/export.log" >&2; exit 1; }

echo ""
if [[ "$DESTINATION" == "upload" ]]; then
  echo "  Uploaded build $BUILD_NUMBER. It appears in App Store Connect → TestFlight"
  echo "  after Apple finishes processing (usually 5–15 minutes)."
else
  echo "  IPA written to: $BUILD_DIR/App.ipa"
fi
echo ""
