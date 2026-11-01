---
title: Package signing
description: Verify published native release artifacts and maintain the signing workflow.
---

## Verify a release

Download artifacts only from the [official releases page](https://github.com/linx-systems/clamui/releases) or repository. Do not install a package when cryptographic verification fails. Verify the files actually published for the release; this guide does not itself establish availability or operating-system compatibility.

These checks validate downloaded v0.5.0 release artifacts; they do not make a local build, CI artifact, or older release into an installer asset. The v0.5.0 Rust/Tauri source is on `master`; the `v0.4.1` tag is the historical Python release. A helper repair requires an exact signed package published for that application's release and host architecture. A trusted already-installed protocol-v4 helper remains compatible and does not need replacement solely because the application was built from source.

### AppImage

The GitHub v0.5.0 AppImage is `ClamUI-0.5.0-x86_64.AppImage`; its `.zsync` metadata is `ClamUI-0.5.0-x86_64.AppImage.zsync`. Confirm that the downloaded filename matches the release asset. If the release declares an embedded AppImage signature, verify it before running the file:

```bash
APPIMAGE=ClamUI-0.5.0-x86_64.AppImage
test -f "$APPIMAGE"
./"$APPIMAGE" --appimage-signature
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/validate-x86_64.AppImage
chmod +x validate-x86_64.AppImage
./validate-x86_64.AppImage "$APPIMAGE"
```

Treat a missing declared signature or a failed verification as a reason not to install the AppImage. Do not substitute a historical 0.4.1 Python AppImage for v0.5.0.

### Debian packages

The v0.5.0 Debian release is an architecture-specific application and helper pair:

```bash
DEB_ARCH="$(dpkg --print-architecture)"
APP="clamui_0.5.0_${DEB_ARCH}.deb"
HELPER="clamui-privileged-helper_0.5.0_${DEB_ARCH}.deb"
test -f "$APP" && test -f "$HELPER"
curl -fsSLo signing-key.asc https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26
ACTUAL_FINGERPRINT="$(gpg --show-keys --with-colons signing-key.asc | awk -F: '$1 == "fpr" { print $10; exit }')"
test "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" || { echo "Unexpected ClamUI signing-key fingerprint" >&2; exit 1; }
gpg --import signing-key.asc
dpkg-sig --verify "$APP" "$HELPER"
```

A valid verification reports `GOODSIG` for the expected fingerprint. An `_gpgbuilder` member alone is not authentication. Some `dpkg-sig` verifier/toolchain combinations report `BADSIG`; use a verifier that reports `GOODSIG` for the imported ClamUI key instead of installing unverified artifacts.

The helper package supplies the native `/usr/bin/clamui-apply-preferences` executable and canonical polkit policy. Its presence does not authorize a package whose signature, version, or architecture does not match.

### Fedora RPM packages

The v0.5.0 helper RPM release-asset names are `clamui-privileged-helper-0.5.0-1.x86_64.rpm` and `clamui-privileged-helper-0.5.0-1.aarch64.rpm`, each with an adjacent `.rpm.asc`. Verify a matching downloaded asset only after it is attached to the GitHub release. The RPM does not contain the ClamUI GUI or ClamAV. Use a temporary GPG home and RPM database so verification does not alter your user or system trust stores:

```bash
set -euo pipefail
VERSION=0.5.0
ARCH="$(rpm --eval '%{_arch}')"
case "$ARCH" in x86_64|aarch64) ;; *) echo "Unsupported ClamUI helper RPM architecture: $ARCH" >&2; exit 1 ;; esac
RPM="clamui-privileged-helper-${VERSION}-1.${ARCH}.rpm"
ASC="${RPM}.asc"
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26

test -f "$RPM" && test -f "$ASC"
verify_dir="$(mktemp -d)"
trap 'rm -rf "$verify_dir"' EXIT
downloaded_key="$verify_dir/downloaded-signing-key.asc"
PINNED_KEY="$verify_dir/clamui-pinned-key.gpg"
GPG_HOME="$verify_dir/gnupg"
RPMDB="$verify_dir/rpmdb"
install -d -m 0700 "$GPG_HOME" "$RPMDB"
curl -fsSLo "$downloaded_key" https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
mapfile -t PRIMARY_FINGERPRINTS < <(gpg --batch --no-options --homedir "$GPG_HOME" --show-keys --with-colons "$downloaded_key" | awk -F: '$1 == "pub" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }')
test "${#PRIMARY_FINGERPRINTS[@]}" -eq 1
test "${PRIMARY_FINGERPRINTS[0]}" = "$EXPECTED_FINGERPRINT"

gpg --batch --no-options --homedir "$GPG_HOME" --import "$downloaded_key"
gpg --batch --no-options --homedir "$GPG_HOME" --armor --export "$EXPECTED_FINGERPRINT" > "$PINNED_KEY"
test -s "$PINNED_KEY"
gpg_status="$(gpg --batch --no-options --homedir "$GPG_HOME" --status-fd=1 --verify "$ASC" "$RPM" 2>/dev/null)"
printf '%s\n' "$gpg_status" | grep -F "[GNUPG:] VALIDSIG $EXPECTED_FINGERPRINT "

rpm --dbpath "$RPMDB" --define '_keyring rpmdb' --initdb
rpm --dbpath "$RPMDB" --define '_keyring rpmdb' --define '_pkgverify_level all' --import "$PINNED_KEY"
rpm --dbpath "$RPMDB" --define '_keyring rpmdb' --define '_pkgverify_level all' --checksig --verbose "$RPM"
test "$(rpm --query --package --queryformat '%{NAME} %{EPOCH}:%{VERSION}-%{RELEASE}.%{ARCH}' "$RPM")" = "clamui-privileged-helper 0:${VERSION}-1.${ARCH}"
```


The check rejects a downloaded key bundle unless it contains exactly one primary key with the pinned fingerprint, then exports only that primary key into `$PINNED_KEY`. The detached check pins the signing fingerprint and the isolated RPM check requires every package verification class. Do not replace it with a bare [`rpmkeys --checksig`](https://rpm.org/docs/latest/man/rpmkeys.8): its default policy can accept an unsigned RPM. The temporary keyrings above do **not** authorize DNF to install anything.

With `set -e`, a nonzero RPM exit status stops the procedure. Do not parse its verbose output to decide success: RPM versions use different signature wording, and individual verbose results are not the final verification-policy result.

On Fedora Workstation or Server, continue in the **same shell** after successful verification. Manual DNF installation needs a persistent system RPM-key import. Import only `$PINNED_KEY`, the fingerprint-pinned key just verified, and only after you accept that lasting trust decision; then keep [`localpkg_gpgcheck`](https://dnf5.readthedocs.io/en/stable/dnf5.conf.5.html) enabled:

```bash
sudo rpm --import "$PINNED_KEY"
sudo dnf --setopt=localpkg_gpgcheck=1 install -y "./$RPM"
```

Never use `--nogpgcheck`, disable global signature checking, or substitute a repo key. On Fedora Atomic desktops, do not import the key as part of this repair. After the same verification above, layer the RPM and reboot as documented by [rpm-ostree](https://coreos.github.io/rpm-ostree/administrator-handbook/):

```bash
sudo rpm-ostree install "./$RPM"
systemctl reboot
```

### Flathub and GitHub Flatpak bundles

Flathub signs each Flatpak it publishes as part of its installation infrastructure. Its current ClamUI store package is the historical Python 0.4.1 release; that repository signature does not cover the separate GitHub v0.5.0 bundles `clamui-x86_64.flatpak` and `clamui-aarch64.flatpak`. Download those bundles only from the v0.5.0 GitHub release and confirm their exact release-asset names before installation.

## Maintainers: configure signing

Use a dedicated 4096-bit RSA signing key with a two-year expiration. Export only the public key to `signing-key.asc`; keep the encrypted private key and passphrase in GitHub Actions secrets `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE`.

```bash
gpg --full-generate-key
gpg --armor --export-secret-keys YOUR_KEY_ID > private.key
gpg --armor --export YOUR_KEY_ID > signing-key.asc
```

The release workflows sign `v*` tag pushes and optional manual dispatches with `sign: true`; normal pushes and pull requests build without signing. The matching workflow and packaging sources must be included in the release tag, and the matching signed release assets must be published before manual or in-app installation can use them. A successful local or architecture-specific job is not publication evidence and does not make its artifacts installer-eligible. Rotate keys before expiration and verify a published release on a known-good verifier.