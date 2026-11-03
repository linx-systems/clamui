---
title: Package signing
description: Verify published native release artifacts and maintain the signing workflow.
---

## Verify a release

Download artifacts only from the [official releases page](https://github.com/linx-systems/clamui/releases) or repository. Do not install a package when cryptographic verification fails. Verify the files actually published for the release; this guide does not itself establish availability or operating-system compatibility.

These checks validate downloaded v0.5.1 release artifacts; they do not make a local build, CI artifact, or older release into an installer asset. The v0.5.1 Rust/Tauri source is on `master`; the `v0.4.1` tag is the historical Python release. A helper repair requires an exact signed package published for that application's release and host architecture. A trusted already-installed protocol-v4 helper remains compatible and does not need replacement solely because the application was built from source.

### AppImage

The GitHub v0.5.1 AppImage is `ClamUI-0.5.1-x86_64.AppImage`; its `.zsync` metadata is `ClamUI-0.5.1-x86_64.AppImage.zsync`. Confirm that the downloaded filename matches the release asset. Do **not** run `--appimage-signature`: it executes the untrusted AppImage and only prints its signature. AppImageKit's continuous release does not publish a `validate` binary. Build the official validator from [the pinned AppImageKit source](https://github.com/AppImage/AppImageKit/tree/5735cc5bed206497cddfbd2a75e1982c2606c35d) using its [upstream build documentation](https://github.com/AppImage/AppImageKit/tree/5735cc5bed206497cddfbd2a75e1982c2606c35d#building).

Install a C/C++ compiler, CMake, Git, `pkg-config`, GObject/GLib, Cairo, OpenSSL, GPGME, libgcrypt, zlib, FUSE development headers, and `mksquashfs` development/runtime packages from the host distribution. The verification commands also require GNU binutils (`readelf` and `objcopy`), GnuPG, and bubblewrap. Then build only `validate` from the pinned revision:

```bash
git clone https://github.com/AppImage/AppImageKit.git
git -C AppImageKit checkout 5735cc5bed206497cddfbd2a75e1982c2606c35d
git -C AppImageKit submodule update --init --depth 1
cmake -S AppImageKit -B build -DUSE_SYSTEM_MKSQUASHFS=ON -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --target validate --parallel 2
```

Verify a downloaded artifact without executing it. This uses a disposable `objcopy` output, a private keyring, and a private `/tmp` because the upstream validator writes there. It also rejects the validator's historical zero-exit contiguity error. If a locally built validator has staged shared-library dependencies outside normal linker paths, set `VALIDATOR_LIBRARY_PATH` to that absolute directory before running the check.

```bash
set -euo pipefail
APPIMAGE="$(realpath ClamUI-0.5.1-x86_64.AppImage)"
VALIDATE="$(realpath build/src/validate)"
VALIDATOR_LIBRARY_PATH="${VALIDATOR_LIBRARY_PATH:-}"
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26
test -f "$APPIMAGE" && test -x "$VALIDATE"
command -v readelf >/dev/null && command -v objcopy >/dev/null
command -v gpg >/dev/null && command -v bwrap >/dev/null
objcopy --version | grep -F 'GNU objcopy' >/dev/null
readelf -W -S "$APPIMAGE" | grep -F '.sha256_sig' >/dev/null
readelf -W -S "$APPIMAGE" | grep -F '.sig_key' >/dev/null

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SIG_KEY="$WORK/embedded-signing-key.asc"
OBJ_COPY="$WORK/objcopy-output"
GNUPGHOME="$WORK/gnupg"
VALIDATE_LOG="$WORK/validate.log"
install -d -m 0700 "$GNUPGHOME" "$WORK/bin"
BEFORE_SHA256="$(sha256sum "$APPIMAGE")"
objcopy --dump-section ".sig_key=$SIG_KEY" "$APPIMAGE" "$OBJ_COPY"
rm -f "$OBJ_COPY"
test "$(sha256sum "$APPIMAGE")" = "$BEFORE_SHA256"
test -s "$SIG_KEY"

KEY_RECORDS="$WORK/embedded-key-records"
PRIMARY_FINGERPRINTS_FILE="$WORK/primary-fingerprints"
gpg --batch --no-options --homedir "$GNUPGHOME" --show-keys --with-colons "$SIG_KEY" >"$KEY_RECORDS"
awk -F: '$1 == "pub" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }' \
  "$KEY_RECORDS" >"$PRIMARY_FINGERPRINTS_FILE"
mapfile -t PRIMARY_FINGERPRINTS < "$PRIMARY_FINGERPRINTS_FILE"
test "${#PRIMARY_FINGERPRINTS[@]}" -eq 1
test "${PRIMARY_FINGERPRINTS[0]}" = "$EXPECTED_FINGERPRINT"
gpg --batch --no-options --homedir "$GNUPGHOME" --import "$SIG_KEY"
ln -s "$(command -v gpg)" "$WORK/bin/gpg2" # validate invokes gpg2 by name

bwrap --unshare-all --die-with-parent --new-session \
  --ro-bind / / --proc /proc --dev /dev --tmpfs /tmp \
  --bind "$WORK" "$WORK" --chdir "$WORK" \
  --setenv GNUPGHOME "$GNUPGHOME" --setenv LC_ALL C \
  --setenv PATH "$WORK/bin:/usr/bin:/bin" \
  --setenv LD_LIBRARY_PATH "$VALIDATOR_LIBRARY_PATH" \
  "$VALIDATE" "$APPIMAGE" >"$VALIDATE_LOG" 2>&1
LC_ALL=C grep -F 'Good signature from' "$VALIDATE_LOG" >/dev/null
```

Both the sandboxed validator and the positive `Good signature from` diagnostic are required; an exit status alone, an embedded signature section, or the absence of an error is not verification. Treat a missing declared signature or failed verification as a reason not to install the AppImage. Do not substitute a historical 0.4.1 Python AppImage for v0.5.1.

### Debian packages

The v0.5.1 Debian release is an architecture-specific application and helper pair:

```bash
DEB_ARCH="$(dpkg --print-architecture)"
APP="clamui_0.5.1_${DEB_ARCH}.deb"
HELPER="clamui-privileged-helper_0.5.1_${DEB_ARCH}.deb"
test -f "$APP" && test -f "$HELPER"
curl -fsSLo signing-key.asc https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc
EXPECTED_FINGERPRINT=037273A518BE90BA6EA27B3CDEF2A3E473DE1E26
ACTUAL_FINGERPRINT="$(gpg --show-keys --with-colons signing-key.asc | awk -F: '$1 == "fpr" { print $10; exit }')"
test "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" || { echo "Unexpected ClamUI signing-key fingerprint" >&2; exit 1; }
gpg --import signing-key.asc
dpkg-sig --verify "$APP" "$HELPER"
```

A valid verification reports `GOODSIG` for the expected fingerprint. An `_gpgbuilder` member alone is not authentication. A `BADSIG` result is a failed verification: do not install either package. The v0.5.1 packages use xz-compressed `control` and `data` archives so standard `dpkg-sig` verification reports `GOODSIG`; never bypass signature verification after a failure.

The helper package supplies the native `/usr/bin/clamui-apply-preferences` executable and canonical polkit policy. Its presence does not authorize a package whose signature, version, or architecture does not match.

### Fedora RPM packages

The v0.5.1 helper RPM release-asset names are `clamui-privileged-helper-0.5.1-1.x86_64.rpm` and `clamui-privileged-helper-0.5.1-1.aarch64.rpm`, each with an adjacent `.rpm.asc`. Verify a matching downloaded asset only after it is attached to the GitHub release. The RPM does not contain the ClamUI GUI or ClamAV. Use a temporary GPG home and RPM database so verification does not alter your user or system trust stores:

```bash
set -euo pipefail
VERSION=0.5.1
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

Flathub signs each Flatpak it publishes as part of its installation infrastructure. Its current ClamUI store package is the historical Python 0.4.1 release; that repository signature does not cover the separate GitHub v0.5.1 bundles `clamui-x86_64.flatpak` and `clamui-aarch64.flatpak`. Download those bundles only from the v0.5.1 GitHub release and confirm their exact release-asset names before installation.

## Maintainers: configure signing

Use a dedicated 4096-bit RSA signing key with a two-year expiration. Export only the public key to `signing-key.asc`; keep the encrypted private key and passphrase in GitHub Actions secrets `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE`.

```bash
gpg --full-generate-key
gpg --armor --export-secret-keys YOUR_KEY_ID > private.key
gpg --armor --export YOUR_KEY_ID > signing-key.asc
```

The release workflows sign `v*` tag pushes and optional manual dispatches with `sign: true`; normal pushes and pull requests build without signing. The matching workflow and packaging sources must be included in the release tag, and the matching signed release assets must be published before manual or in-app installation can use them. A successful local or architecture-specific job is not publication evidence and does not make its artifacts installer-eligible. Rotate keys before expiration and verify a published release on a known-good verifier.