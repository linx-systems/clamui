---
title: Package signing
description: Verify release artifacts and maintain the signing workflow.
---

## Verify a release

Download artifacts only from the [official releases page](https://github.com/linx-systems/clamui/releases) or repository. Do not install a package when cryptographic verification fails.

### AppImage

```bash
./ClamUI-*.AppImage --appimage-signature
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/validate-x86_64.AppImage
chmod +x validate-x86_64.AppImage
./validate-x86_64.AppImage ./ClamUI-*.AppImage
```

Tagged AppImages have an embedded GPG signature. Confirm its displayed fingerprint using the public key below.

### Debian packages

Verify matching application and privileged-helper packages:

```bash
curl -fsSLo signing-key.asc https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26
ACTUAL_FINGERPRINT="$(gpg --show-keys --with-colons signing-key.asc | awk -F: '$1 == "fpr" { print $10; exit }')"
test "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" || { echo "Unexpected ClamUI signing-key fingerprint" >&2; exit 1; }
gpg --import signing-key.asc
dpkg-sig --verify clamui_*.deb clamui-privileged-helper_*.deb
```

A valid verification reports `GOODSIG` for the expected fingerprint. An `_gpgbuilder` member alone is not authentication. Some `dpkg-sig` verifier/toolchain combinations report `BADSIG`; use a verifier that reports `GOODSIG` for the imported ClamUI key instead of installing unverified artifacts.

### Flathub

Flathub signs Flatpak packages as part of its installation infrastructure; no manual ClamUI signature step is needed.

## Maintainers: configure signing

Use a dedicated 4096-bit RSA signing key with a two-year expiration. Export only the public key to `signing-key.asc`; keep the encrypted private key and passphrase in GitHub Actions secrets `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE`.

```bash
gpg --full-generate-key
gpg --armor --export-secret-keys YOUR_KEY_ID > private.key
gpg --armor --export YOUR_KEY_ID > signing-key.asc
```

Signing runs for `v*` tag pushes and optional manual dispatches with `sign: true`; normal pushes and pull requests build without signing. Rotate keys before expiration and validate a signed release on a known-good verifier.