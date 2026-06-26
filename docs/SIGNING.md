# Package Signing

ClamUI releases are signed to verify their authenticity. This document explains how to verify package signatures and how
to set up signing for releases.

## Verifying Package Signatures

### AppImage

AppImage files can be verified using the built-in signature command or the AppImageKit validate tool:

```bash
# Display signature info (quick check)
./ClamUI-*.AppImage --appimage-signature

# Full validation (requires AppImageKit validate tool)
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/validate-x86_64.AppImage
chmod +x validate-x86_64.AppImage
./validate-x86_64.AppImage ./ClamUI-*.AppImage
```

On tagged releases the AppImage is GPG-signed (the signature is embedded by `appimagetool --sign`), so `--appimage-signature`
displays the signing key's fingerprint. Import the project's public signing key (see the Debian section below) to confirm it
matches.

### Debian Package

Debian packages are signed using `dpkg-sig`. To verify:

```bash
# Import ClamUI's public signing key
curl -fsSL https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc | gpg --import

# Verify the package signature
dpkg-sig --verify clamui_*.deb

# Expected output for valid signature:
# GOODSIG _gpgbuilder <key-fingerprint>
```

> **Note:** The `.deb` is signed in CI with `dpkg-sig --sign builder` on Ubuntu 22.04. The `dpkg-sig --verify` command has a
> known BADSIG bug on that toolchain version and may report a failure even for a valid signature. To confirm the signature
> member is present without relying on `--verify`, run `ar t clamui_*.deb | grep _gpgbuilder` — a `_gpgbuilder` entry means
> the package was signed.

> **Security Note:** Before importing keys, verify you're downloading from the official repository. You can also
> download `signing-key.asc` directly
> from [the repository](https://github.com/linx-systems/clamui/blob/master/signing-key.asc) and import it manually with
`gpg --import signing-key.asc`.

### Flatpak (via Flathub)

Flatpak packages installed from Flathub are automatically signed by Flathub's infrastructure. Signature verification
happens automatically during installation - no manual steps required.

---

## Setting Up Signing (Maintainers)

This section is for project maintainers who need to configure the CI signing infrastructure.

### 1. Generate a Dedicated CI Signing Key

Create a GPG key specifically for CI use:

```bash
gpg --full-generate-key
```

Recommended settings:

- **Key type**: RSA and RSA
- **Key size**: 4096 bits
- **Expiration**: 2 years (allows for rotation)
- **Email**: `ci@clamui.org` or similar dedicated address

### 2. Export the Keys

```bash
# Export private key (for GitHub secrets)
gpg --armor --export-secret-keys YOUR_KEY_ID > private.key

# Export public key (for repository)
gpg --armor --export YOUR_KEY_ID > signing-key.asc
```

### 3. Add GitHub Secrets

Go to repository **Settings → Secrets and variables → Actions** and add:

| Secret Name       | Value                     |
|-------------------|---------------------------|
| `GPG_PRIVATE_KEY` | Contents of `private.key` |
| `GPG_PASSPHRASE`  | Key passphrase            |

### 4. Add Public Key to Repository

Commit `signing-key.asc` to the repository root so users can import it for verification.

### 5. Test the Setup

Push a tag (e.g., `v0.2.0-test`) to trigger a signed build:

```bash
git tag v0.2.0-test
git push origin v0.2.0-test
```

Download the artifacts from GitHub Actions and verify the signatures work.

### 6. Clean Up Test Tags

```bash
git tag -d v0.2.0-test
git push origin :refs/tags/v0.2.0-test
```

---

## Security Considerations

- **Private key storage**: The GPG private key is stored as an encrypted GitHub secret and is only accessible during
  workflow runs
- **Passphrase protection**: The passphrase is stored as a separate secret, never exposed in logs
- **Release signing**: Packages are signed on tag pushes (releases), or on a manual `workflow_dispatch` with the `sign`
  input set to `true`; never on PR or ordinary branch builds
- **Key rotation**: Consider rotating the signing key every 2 years (matching the recommended expiration)
- **Public key distribution**: The public key is committed to the repository for transparency and easy verification

---

## Workflow Behavior

| Event            | Signing                 |
|------------------|-------------------------|
| Push to `master` | No signing (build only) |
| Pull request     | No signing (build only) |
| Tag push (`v*`)  | **Signed**              |
| Manual dispatch  | Optional (via `sign` input) |

Tag pushes are always signed. Manual dispatches can optionally sign by setting the `sign` input to `true`.
