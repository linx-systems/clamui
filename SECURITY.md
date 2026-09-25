# Security Policy

## Reporting a Vulnerability

We take the security of ClamUI seriously. If you believe you have found a security vulnerability, please report it to us
as described below.

### Primary Method: GitHub Security Advisories (Preferred)

**Please report security vulnerabilities
using [GitHub Security Advisories](https://github.com/linx-systems/clamui/security/advisories/new).**

This is the preferred method as it allows for:

- Private disclosure and discussion
- Coordinated vulnerability disclosure
- CVE assignment through GitHub
- Draft security advisories before public disclosure

### Secondary Method: Email

If you prefer not to use GitHub Security Advisories, you can email security reports to:

**clamui@rooki.xyz**

Please include:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Any suggested fixes (if available)

## Supported Versions

ClamUI is currently in early development. Security updates are provided for the latest minor release:

| Version | Supported          |
|---------|--------------------|
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

As the project matures, this policy will be updated to reflect long-term support commitments.

## What to Report

Please report any security vulnerabilities including but not limited to:

### High Priority

- **Command Injection**: Improper sanitization of paths or user input passed to shell commands
- **Path Traversal**: Ability to access files outside intended directories
- **Privilege Escalation**: Unauthorized elevation of permissions
- **Information Disclosure**: Exposure of sensitive data (API keys, scan results, system information)
- **Arbitrary Code Execution**: Ability to execute unauthorized code

### Medium Priority

- **Denial of Service**: Crashes or resource exhaustion
- **Log Injection**: Ability to inject malicious content into logs
- **Symlink Attacks**: Improper handling of symbolic links
- **Race Conditions**: Time-of-check to time-of-use vulnerabilities

### Areas of Concern

- ClamAV command execution (`src/core/scanner.py`, `src/core/daemon_scanner.py`)
- Scheduled scan commands (`src/core/scheduler.py`)
- Flatpak host command execution (`src/core/flatpak.py`)
- Quarantine file handling (`src/core/quarantine/`)
- Input sanitization (`src/core/sanitize.py`, `src/core/path_validation.py`)
- API key storage (`src/core/keyring_manager.py`)

## What NOT to Report

The following are **not** considered security vulnerabilities:

- ClamAV detection capabilities (report to ClamAV project)
- False positives/negatives from virus scans
- UI/UX issues without security impact
- Performance issues without DoS potential
- Issues requiring physical access to an unlocked system

## Disclosure Process

1. **Report Received**: We aim to acknowledge receipt within 48 hours
2. **Initial Assessment**: We will assess the severity and impact within 7 days
3. **Coordinated Disclosure**: We will work with you to understand and fix the issue
4. **Fix Development**: We will develop and test a fix
5. **Release**: We will release a patched version
6. **Public Disclosure**: After users have had time to update (typically 7-14 days), we will publicly disclose the
   vulnerability

## Security Best Practices

When using ClamUI:

- **Keep Updated**: Always use the latest version of ClamUI and ClamAV
- **Limit Permissions**: Run ClamUI with minimal necessary permissions
- **Validate Sources**: Only scan files from trusted sources when possible
- **Secure API Keys**: Use the built-in keyring storage for VirusTotal API keys
- **Review Exclusions**: Regularly audit exclusion patterns to ensure they're still needed
- **Monitor Logs**: Check scan logs for suspicious activity

## Security Features

ClamUI implements several security measures:

- **Input Sanitization**: All user input and file paths are sanitized before use
- **Path Validation**: Paths are validated to prevent directory traversal
- **Symlink Safety**: Symlinks are checked before following
- **Command Escaping**: Shell commands use `shlex.quote()` for safe execution
- **Quarantine Integrity**: SHA-256 verification for quarantined files
- **Secure Storage**: API keys stored in system keyring (GNOME Keyring, KWallet)
- **Flatpak Sandboxing**: Additional isolation when running as Flatpak

## Contact

- **Security Issues**: [GitHub Security Advisories](https://github.com/linx-systems/clamui/security/advisories) or
  clamui@rooki.xyz
- **General Issues**: [GitHub Issues](https://github.com/linx-systems/clamui/issues)
- **Project**: https://github.com/linx-systems/clamui

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [ClamAV Security](https://www.clamav.net/documents/security)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
