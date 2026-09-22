#!/usr/bin/env python3
"""
Prepare Apple code-signing for TV Remote using only an App Store Connect API key.

Same approach as the Rize build: no Xcode IDE, no automatic signing (fails on a
team with no registered devices), no cloud signing. Everything goes through the
App Store Connect API and the local keychain.

What it does:
  1. Registers the bundle ID with Apple if it is not registered yet.
  2. Finds an Apple Distribution certificate whose private key is in the local
     keychain (matched by SHA-1 fingerprint). If there is none, it creates one
     from a fresh CSR and imports it (--create-cert), together with Apple's
     WWDR intermediates so the identity is valid.
  3. Creates (or recreates) an App Store provisioning profile for the bundle ID
     tied to that certificate and installs it in ~/Library/MobileDevice.
  4. Prints the certificate SHA-1 and the profile name/UUID for ExportOptions.

Dependencies: python3 (stdlib only), openssl, macOS `security` tool.

Environment:
  ASC_KEY_ID, ASC_ISSUER_ID   App Store Connect API key (App Manager role)
  ASC_KEY_PATH                path to AuthKey_<ID>.p8
                              (default ~/.appstoreconnect/private_keys/AuthKey_<ID>.p8)
  BUNDLE_ID, APP_NAME, PROFILE_NAME, KEYCHAIN (default: login keychain)
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

API = "https://api.appstoreconnect.apple.com"


def env(name, default=None):
    v = os.environ.get(name)
    return v if v else default


KEY_ID = env("ASC_KEY_ID")
ISSUER_ID = env("ASC_ISSUER_ID")
KEY_PATH = env("ASC_KEY_PATH", os.path.expanduser(f"~/.appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8"))
BUNDLE_ID = env("BUNDLE_ID", "com.kurbaitaev.tvremote")
APP_NAME = env("APP_NAME", "TV Remote")
PROFILE_NAME = env("PROFILE_NAME", "TV Remote App Store")
KEYCHAIN = env("KEYCHAIN")  # None = default (login) keychain
CREATE_CERT = "--create-cert" in sys.argv


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- JWT (ES256 via openssl)

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_to_raw_sig(der: bytes) -> bytes:
    """Convert an ASN.1 DER ECDSA signature to the raw r||s form JWT expects."""
    assert der[0] == 0x30
    i = 2
    assert der[i] == 0x02
    rlen = der[i + 1]
    r = der[i + 2:i + 2 + rlen]
    i = i + 2 + rlen
    assert der[i] == 0x02
    slen = der[i + 1]
    s = der[i + 2:i + 2 + slen]
    return r[-32:].rjust(32, b"\0") + s[-32:].rjust(32, b"\0")


def make_token() -> str:
    header = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": ISSUER_ID, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
    signing_input = b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        b64url(json.dumps(payload, separators=(",", ":")).encode())
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(signing_input.encode())
        path = f.name
    try:
        der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", KEY_PATH, path],
                             check=True, capture_output=True).stdout
    finally:
        os.unlink(path)
    return signing_input + "." + b64url(der_to_raw_sig(der))


def api(path, data=None, method="GET"):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode() if data else None,
        method=method,
        headers={"Authorization": "Bearer " + make_token(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        die(f"App Store Connect API {method} {path} -> {e.code}: {e.read().decode()[:600]}")


# ---------------------------------------------------------------- keychain helpers

def keychain_args():
    return [KEYCHAIN] if KEYCHAIN else []


def local_identities():
    """SHA-1 fingerprints of valid Apple Distribution identities in the keychain."""
    out = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"] + keychain_args(),
                         capture_output=True, text=True).stdout
    return {m.group(1).upper() for m in re.finditer(r"\)\s+([0-9A-F]{40})\s+\"Apple Distribution", out)}


def install_wwdr():
    with tempfile.TemporaryDirectory() as tmp:
        for c in ("AppleWWDRCAG3", "AppleWWDRCAG6"):
            p = os.path.join(tmp, c + ".cer")
            urllib.request.urlretrieve(f"https://www.apple.com/certificateauthority/{c}.cer", p)
            subprocess.run(["security", "import", p, "-A"] + (["-k", KEYCHAIN] if KEYCHAIN else []),
                           capture_output=True)


# ---------------------------------------------------------------- main

def main():
    if not KEY_ID or not ISSUER_ID:
        die("ASC_KEY_ID and ASC_ISSUER_ID must be set")
    if not os.path.exists(KEY_PATH):
        die(f"API key not found at {KEY_PATH}. Download it from App Store Connect → Users and Access → "
            "Integrations → App Store Connect API and put it there.")

    # 1) bundle id
    ids = [d for d in api("/v1/bundleIds?limit=200")["data"] if d["attributes"]["identifier"] == BUNDLE_ID]
    if ids:
        bid = ids[0]["id"]
        print(f"   bundle id {BUNDLE_ID} already registered")
    else:
        bid = api("/v1/bundleIds", {"data": {"type": "bundleIds", "attributes": {
            "identifier": BUNDLE_ID, "name": APP_NAME, "platform": "IOS"}}}, "POST")["data"]["id"]
        print(f"   registered bundle id {BUNDLE_ID}")

    # 2) distribution certificate that we hold the private key for
    certs = [d for d in api("/v1/certificates?limit=200")["data"]
             if d["attributes"]["certificateType"] == "DISTRIBUTION"]
    by_sha = {}
    for c in certs:
        der = base64.b64decode(c["attributes"]["certificateContent"])
        by_sha[hashlib.sha1(der).hexdigest().upper()] = c
    have = local_identities()
    usable = [sha for sha in by_sha if sha in have]

    if usable:
        sha = usable[0]
        cert = by_sha[sha]
        print(f"   using Apple Distribution certificate {sha[:8]}… already in the keychain")
    elif CREATE_CERT:
        print("   no usable distribution certificate in the keychain; creating one")
        with tempfile.TemporaryDirectory() as tmp:
            key, csr, cer, pem, p12 = (os.path.join(tmp, n) for n in ("dist.key", "dist.csr", "dist.cer", "dist.pem", "dist.p12"))
            run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr,
                 "-subj", f"/CN={APP_NAME} Distribution/O={APP_NAME}/C=US"])
            cert = api("/v1/certificates", {"data": {"type": "certificates", "attributes": {
                "csrContent": open(csr).read(), "certificateType": "DISTRIBUTION"}}}, "POST")["data"]
            der = base64.b64decode(cert["attributes"]["certificateContent"])
            open(cer, "wb").write(der)
            sha = hashlib.sha1(der).hexdigest().upper()
            run(["openssl", "x509", "-inform", "DER", "-in", cer, "-out", pem])
            # -legacy: OpenSSL 3 default PKCS#12 MAC is unreadable by macOS ("MAC verification failed")
            run(["openssl", "pkcs12", "-export", "-inkey", key, "-in", pem, "-out", p12, "-passout", "pass:tvremote",
                 "-name", "Apple Distribution", "-legacy", "-macalg", "sha1",
                 "-keypbe", "PBE-SHA1-3DES", "-certpbe", "PBE-SHA1-3DES"])
            run(["security", "import", p12, "-P", "tvremote", "-A", "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"]
                + (["-k", KEYCHAIN] if KEYCHAIN else []))
            print(f"   created and imported distribution certificate {sha[:8]}…")
        install_wwdr()
        if KEYCHAIN:
            # Let codesign use the key without a UI prompt on CI keychains.
            subprocess.run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
                            "-s", "-k", env("KEYCHAIN_PASSWORD", ""), KEYCHAIN], capture_output=True)
    else:
        die("No Apple Distribution certificate with a private key in this keychain.\n"
            "       Re-run with --create-cert to make one through the API (Apple allows a few per team),\n"
            "       or import the .p12 you exported from the Mac that built Rize.")

    # 3) App Store provisioning profile
    for p in api("/v1/profiles?limit=200")["data"]:
        if p["attributes"]["name"] == PROFILE_NAME:
            api("/v1/profiles/" + p["id"], method="DELETE")
            print("   removed previous profile")
    prof = api("/v1/profiles", {"data": {"type": "profiles",
        "attributes": {"name": PROFILE_NAME, "profileType": "IOS_APP_STORE"},
        "relationships": {"bundleId": {"data": {"id": bid, "type": "bundleIds"}},
                          "certificates": {"data": [{"id": cert["id"], "type": "certificates"}]}}}}, "POST")["data"]
    d = os.path.expanduser("~/Library/MobileDevice/Provisioning Profiles")
    os.makedirs(d, exist_ok=True)
    uuid = prof["attributes"]["uuid"]
    with open(os.path.join(d, uuid + ".mobileprovision"), "wb") as f:
        f.write(base64.b64decode(prof["attributes"]["profileContent"]))
    print(f"   installed profile '{PROFILE_NAME}' ({uuid})")

    # 4) machine-readable summary for the caller
    if out := env("SIGNING_OUTPUT"):
        with open(out, "w") as f:
            json.dump({"cert_sha1": sha, "profile_name": PROFILE_NAME, "profile_uuid": uuid,
                       "bundle_id": BUNDLE_ID}, f)


if __name__ == "__main__":
    main()
