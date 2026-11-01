---
title: Package signing
description: Verify published native release artifacts and maintain the signing workflow.
---

## Verify a release

Download artifacts only from the [official releases page](https://github.com/linx-systems/clamui/releases) or repository. Do not install a package when cryptographic verification fails. Verify the files actually published for the release; this guide does not itself establish availability or operating-system compatibility.

These checks validate downloaded release artifacts; they do not make a local build, CI artifact, or older release into an installer asset. The public 0.4.1 release predates the current Rust/Tauri development source on `migration/rust-tauri`, rather than the default `master` branch; do not treat its helper assets, or a coincident version string, as matching a source checkout. A helper repair requires an exact signed package published for that application's release and the host architecture. The only exception is an explicitly published same-version architecture-independent Debian helper fallback. A trusted already-installed protocol-v4 helper remains compatible and does not need replacement solely because the application was built from source.

### AppImage

```bash
APPIMAGE=ClamUI-0.4.1-x86_64.AppImage
test -f "$APPIMAGE"
./"$APPIMAGE" --appimage-signature
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/validate-x86_64.AppImage
chmod +x validate-x86_64.AppImage
./validate-x86_64.AppImage "$APPIMAGE"
```

The published `ClamUI-0.4.1-x86_64.AppImage` has an embedded GPG signature. Confirm its displayed fingerprint using the public key below. It is the published Python v0.4.1 application, not the current Rust/Tauri development checkout.

### Debian packages

The following verifies the published Python v0.4.1 stable pair only; it does not verify a current Rust/Tauri source checkout. Both published Debian packages are architecture-independent:

```bash
APP=clamui_0.4.1_all.deb
HELPER=clamui-privileged-helper_0.4.1_all.deb
test -f "$APP" && test -f "$HELPER"
curl -fsSLo signing-key.asc https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26
ACTUAL_FINGERPRINT="$(gpg --show-keys --with-colons signing-key.asc | awk -F: '$1 == "fpr" { print $10; exit }')"
test "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" || { echo "Unexpected ClamUI signing-key fingerprint" >&2; exit 1; }
gpg --import signing-key.asc
dpkg-sig --verify "$APP" "$HELPER"
```

Future native Rust/Tauri releases require published application and helper assets with the same version and host architecture. An architecture-independent helper is acceptable only if that release explicitly publishes it as the signed same-version fallback.

A valid verification reports `GOODSIG` for the expected fingerprint. An `_gpgbuilder` member alone is not authentication. Some `dpkg-sig` verifier/toolchain combinations report `BADSIG`; use a verifier that reports `GOODSIG` for the imported ClamUI key instead of installing unverified artifacts.

The helper package supplies the native `/usr/bin/clamui-apply-preferences` executable and canonical polkit policy. Its presence does not authorize a package whose signature, version, or architecture does not match.

### Fedora RPM packages

No Fedora helper RPM is published for v0.4.1 or the current Rust/Tauri development checkout. Do not use a local CI/download artifact as an installer. If a future official release publishes both a signed `clamui-privileged-helper-<VERSION>-1.<ARCH>.rpm` and its adjacent `.rpm.asc` for your host, use the procedure below. The RPM is helper-only; it does not contain the ClamUI GUI or ClamAV. The `x86_64` and `aarch64` naming convention describes possible future release assets; it does not claim that either architecture is published for a given release. Current RPM packaging and workflow files are local, untracked work and are absent from a fresh `migration/rust-tauri` clone, so they are not evidence of a published Fedora auto-install feature.

Use a temporary GPG home and RPM database so verification does not alter your user or system trust stores. Enter the expected version shown on that future published release page; the procedure derives the host RPM architecture locally and never trusts the package to supply the expected version:
```bash
set -euo pipefail
read -r -p "Published ClamUI release version: " VERSION
test -n "$VERSION"
ARCH="$(rpm --eval '%{_arch}')"
test -n "$ARCH"
RPM="clamui-privileged-helper-${VERSION}-1.${ARCH}.rpm"
ASC="${RPM}.asc"
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26

test -f "$RPM" && test -f "$ASC"
verify_dir="$(mktemp -d)"
trap 'rm -rf "$verify_dir"' EXIT
downloaded_key="$verify_dir/downloaded-signing-key.asc"
pinned_key="$verify_dir/clamui-pinned-key.gpg"
gpg_home="$verify_dir/gnupg"
rpmdb="$verify_dir/rpmdb"
install -d -m 0700 "$gpg_home" "$rpmdb"
curl -fsSLo "$downloaded_key" https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
mapfile -t PRIMARY_FINGERPRINTS < <(gpg --batch --no-options --homedir "$gpg_home" --show-keys --with-colons "$downloaded_key" | awk -F: '$1 == "pub" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }')
test "${#PRIMARY_FINGERPRINTS[@]}" -eq 1
test "${PRIMARY_FINGERPRINTS[0]}" = "$EXPECTED_FINGERPRINT"

gpg --batch --no-options --homedir "$gpg_home" --import "$downloaded_key"
gpg --batch --no-options --homedir "$gpg_home" --armor --export "$EXPECTED_FINGERPRINT" > "$pinned_key"
test -s "$pinned_key"
gpg_status="$(gpg --batch --no-options --homedir "$gpg_home" --status-fd=1 --verify "$ASC" "$RPM" 2>/dev/null)"
printf '%s\n' "$gpg_status" | grep -F "[GNUPG:] VALIDSIG $EXPECTED_FINGERPRINT "

rpm --dbpath "$rpmdb" --define '_keyring rpmdb' --initdb
rpm --dbpath "$rpmdb" --define '_keyring rpmdb' --define '_pkgverify_level all' --import "$pinned_key"
rpm --dbpath "$rpmdb" --define '_keyring rpmdb' --define '_pkgverify_level all' --checksig --verbose "$RPM"
test "$(rpm --query --package --queryformat '%{NAME} %{EPOCH}:%{VERSION}-%{RELEASE}.%{ARCH}' "$RPM")" = "clamui-privileged-helper 0:${VERSION}-1.${ARCH}"
```

The check rejects a downloaded key bundle unless it contains exactly one primary key with the pinned fingerprint, then exports only that primary key into `$pinned_key`. The detached check pins the signing fingerprint and the isolated RPM check requires every package verification class. Do not replace it with a bare [`rpmkeys --checksig`](https://rpm.org/docs/latest/man/rpmkeys.8): its default policy can accept an unsigned RPM. The temporary keyrings above do **not** authorize DNF to install anything.

With `set -e`, a nonzero RPM exit status stops the procedure. Do not parse its verbose output to decide success: RPM versions use different signature wording, and individual verbose results are not the final verification-policy result.

On Fedora Workstation or Server, continue in the **same shell** after successful verification. Manual DNF installation needs a persistent system RPM-key import. Import only `$pinned_key`, the fingerprint-pinned key just verified, and only after you accept that lasting trust decision; then keep [`localpkg_gpgcheck`](https://dnf5.readthedocs.io/en/stable/dnf5.conf.5.html) enabled:

```bash
sudo rpm --import "$pinned_key"
sudo dnf --setopt=localpkg_gpgcheck=1 install -y "./$RPM"
```

Never use `--nogpgcheck`, disable global signature checking, or substitute a repo key. On Fedora Atomic desktops, do not import the key as part of this repair. After the same verification above, layer the RPM and reboot as documented by [rpm-ostree](https://coreos.github.io/rpm-ostree/administrator-handbook/):

```bash
sudo rpm-ostree install "./$RPM"
systemctl reboot
```

### Flathub

Flathub signs each Flatpak it publishes as part of its installation infrastructure, so no manual ClamUI signature step is needed. That signature applies only to the Flatpak version actually published there; it does not make the current Rust/Tauri source checkout or an older native helper asset a matching deployment.

## Maintainers: configure signing

Use a dedicated 4096-bit RSA signing key with a two-year expiration. Export only the public key to `signing-key.asc`; keep the encrypted private key and passphrase in GitHub Actions secrets `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE`.

```bash
gpg --full-generate-key
gpg --armor --export-secret-keys YOUR_KEY_ID > private.key
gpg --armor --export YOUR_KEY_ID > signing-key.asc
```

The release workflows sign `v*` tag pushes and optional manual dispatches with `sign: true`; normal pushes and pull requests build without signing. The matching workflow and packaging sources must be included in the release tag, and the matching signed release assets must be published before manual or in-app installation can use them. A successful local or architecture-specific job is not publication evidence and does not make its artifacts installer-eligible. Rotate keys before expiration and verify a published release on a known-good verifier.