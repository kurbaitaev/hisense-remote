#!/usr/bin/env bash
# Build a signed Sofaclick .ipa and upload it to TestFlight — entirely from the
# command line, the same way the Rize app is shipped:
#
#   * archive UNSIGNED (automatic signing fails on a team with no registered
#     devices, and Xcode cloud signing refuses from the CLI)
#   * sign at export with an Apple Distribution certificate + App Store profile
#     that scripts/apple_signing.py creates through the App Store Connect API
#   * upload with `xcrun altool` using the same API key
#
# No Xcode IDE needed: the release Xcode command-line tools are enough.
#
# One-time on this Mac:
#   ~/.appstoreconnect/private_keys/AuthKey_<KEY_ID>.p8 must exist (the same
#   key Rize uses; defaults below match it). App Store Connect must have an app
#   record for the bundle id — creating that record is the one thing Apple
#   offers no API for.
#
# Usage:
#   ./scripts/testflight.sh              # build + sign + upload to TestFlight
#   SKIP_UPLOAD=1 ./scripts/testflight.sh   # build + sign only (mobile/ios/build/export/App.ipa)
#
# Optional env:
#   BUILD_NUMBER (default: UTC timestamp), MARKETING_VERSION (default: project value)
#   ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, APPLE_TEAM_ID, BUNDLE_ID, PROFILE_NAME
#   DEVELOPER_DIR (default: /Applications/Xcode.app/Contents/Developer)
#   CREATE_CERT=1  let apple_signing.py create a distribution certificate if the
#                  keychain has none (CI does this on a throwaway keychain)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOBILE="$ROOT/mobile"
IOS="$MOBILE/ios"
BUILD_DIR="$IOS/build"
ARCHIVE="$BUILD_DIR/App.xcarchive"
EXPORT_DIR="$BUILD_DIR/export"

# Same Apple account as Rize.
: "${APPLE_TEAM_ID:=A58FFUY6DF}"
: "${ASC_KEY_ID:=AQZ687BDBN}"
: "${ASC_ISSUER_ID:=4cd18058-a288-478e-9bf4-4d8accc67911}"
: "${ASC_KEY_PATH:=$HOME/.appstoreconnect/private_keys/AuthKey_${ASC_KEY_ID}.p8}"
: "${BUNDLE_ID:=com.kurbaitaev.tvremote}"
: "${PROFILE_NAME:=Sofaclick App Store}"
: "${DEVELOPER_DIR:=/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR ASC_KEY_ID ASC_ISSUER_ID ASC_KEY_PATH BUNDLE_ID PROFILE_NAME
export APP_NAME="Sofaclick"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: iOS archives can only be built on macOS." >&2
  exit 1
fi
if [[ ! -x "$DEVELOPER_DIR/usr/bin/xcodebuild" ]]; then
  echo "error: no Xcode at $DEVELOPER_DIR (set DEVELOPER_DIR to a release Xcode, not a beta — Apple rejects beta builds)." >&2
  exit 1
fi
if [[ ! -f "$ASC_KEY_PATH" ]]; then
  echo "error: App Store Connect API key not found at $ASC_KEY_PATH" >&2
  echo "       (App Store Connect → Users and Access → Integrations → App Store Connect API)" >&2
  exit 1
fi

BUILD_NUMBER="${BUILD_NUMBER:-$(date -u +%Y%m%d%H%M)}"
VERSION_ARGS=("CURRENT_PROJECT_VERSION=$BUILD_NUMBER")
[[ -n "${MARKETING_VERSION:-}" ]] && VERSION_ARGS+=("MARKETING_VERSION=$MARKETING_VERSION")

echo ""
echo "  Sofaclick — TestFlight build"
echo "  ────────────────────────────"
echo "  Xcode:        $("$DEVELOPER_DIR/usr/bin/xcodebuild" -version | head -1)"
echo "  Team:         $APPLE_TEAM_ID"
echo "  Bundle id:    $BUNDLE_ID"
echo "  Build number: $BUILD_NUMBER"
echo ""

echo "==> Signing credentials (bundle id, distribution certificate, App Store profile)"
SIGNING_JSON="$(mktemp)"
SIGNING_OUTPUT="$SIGNING_JSON" python3 "$ROOT/scripts/apple_signing.py" \
  $([[ "${CREATE_CERT:-0}" == "1" ]] && echo --create-cert)
CERT_SHA1="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['cert_sha1'])" "$SIGNING_JSON")"
rm -f "$SIGNING_JSON"

echo "==> Installing npm packages and syncing web assets"
cd "$MOBILE"
if [[ -f package-lock.json ]]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
npx cap sync ios

echo "==> Archiving (unsigned, Release)"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
xcodebuild archive \
  -project "$IOS/App/App.xcodeproj" \
  -scheme App \
  -configuration Release \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  "${VERSION_ARGS[@]}" \
  | tee "$BUILD_DIR/archive.log" | grep -E "error:|\*\* ARCHIVE" || true
[[ -d "$ARCHIVE" ]] || { echo "error: archive failed, see $BUILD_DIR/archive.log" >&2; exit 1; }

echo "==> Exporting signed .ipa"
sed -e "s/__TEAM_ID__/$APPLE_TEAM_ID/" \
    -e "s/__BUNDLE_ID__/$BUNDLE_ID/" \
    -e "s/__PROFILE_NAME__/$PROFILE_NAME/" \
    -e "s/__CERT_SHA1__/$CERT_SHA1/" \
    "$IOS/ExportOptions.plist" > "$BUILD_DIR/ExportOptions.plist"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$BUILD_DIR/ExportOptions.plist" \
  | tee "$BUILD_DIR/export.log" | grep -E "error:|\*\* EXPORT" || true
IPA="$(find "$EXPORT_DIR" -name '*.ipa' 2>/dev/null | head -1 || true)"
[[ -n "$IPA" ]] || { echo "error: export failed, see $BUILD_DIR/export.log" >&2; exit 1; }
echo "    $IPA"

if [[ "${SKIP_UPLOAD:-0}" == "1" ]]; then
  echo ""
  echo "  Signed IPA ready (upload skipped)."
  exit 0
fi

echo "==> Uploading to App Store Connect"
# altool looks for AuthKey_<ID>.p8 in ~/.appstoreconnect/private_keys or $API_PRIVATE_KEYS_DIR
export API_PRIVATE_KEYS_DIR="$(dirname "$ASC_KEY_PATH")"
xcrun altool --upload-app -f "$IPA" -t ios \
  --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"

echo ""
echo "  Uploaded build $BUILD_NUMBER. It appears in App Store Connect → TestFlight"
echo "  after Apple finishes processing (usually 5–15 minutes)."
echo ""
