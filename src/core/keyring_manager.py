# ClamUI Keyring Manager
"""
Secure API key storage using system keyring with fallback to settings.json.

This module provides secure storage for the VirusTotal API key using the
system keyring (GNOME Keyring, KWallet, etc.) as primary storage, with
a fallback to the settings.json file if keyring is unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .i18n import _

if TYPE_CHECKING:
    from .settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# Keyring configuration
SERVICE_NAME = "clamui"
VT_API_KEY_NAME = "virustotal_api_key"
PM_API_TOKEN_NAME = "portmaster_api_token"  # noqa: S105 - keyring entry name, not a password
PM_SETTINGS_KEY = "portmaster_api_token"


def _get_keyring():
    """
    Import and return keyring module, or None if unavailable.

    Returns:
        The keyring module if available, None otherwise.
    """
    try:
        import keyring

        return keyring
    except ImportError:
        logger.warning("keyring module not available, will use settings fallback")
        return None


def get_api_key(settings_manager: SettingsManager | None = None) -> str | None:
    """
    Get VirusTotal API key from keyring or settings fallback.

    Attempts to retrieve the API key from the system keyring first.
    If the keyring is unavailable or the key is not found, falls back
    to the settings.json file.

    Args:
        settings_manager: Optional SettingsManager instance for fallback.
                         If None, creates a new instance.

    Returns:
        The API key if found, None otherwise.
    """
    # Try keyring first
    keyring = _get_keyring()
    if keyring is not None:
        try:
            key = keyring.get_password(SERVICE_NAME, VT_API_KEY_NAME)
            if key:
                logger.debug("Retrieved VirusTotal API key from keyring")
                return key
        except Exception as e:
            logger.warning(f"Failed to read from keyring: {e}")

    # Fall back to settings
    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()

    key = settings_manager.get("virustotal_api_key")
    if key:
        logger.debug("Retrieved VirusTotal API key from settings")
    return key


def set_api_key(
    api_key: str, settings_manager: SettingsManager | None = None
) -> tuple[bool, str | None]:
    """
    Store VirusTotal API key in keyring or settings fallback.

    Attempts to store the API key in the system keyring first.
    If the keyring is unavailable, falls back to settings.json.

    Args:
        api_key: The API key to store.
        settings_manager: Optional SettingsManager instance for fallback.
                         If None, creates a new instance.

    Returns:
        Tuple of (success, message). On success, message is None if stored
        in the keyring, or a warning string if stored in the plaintext
        settings fallback. On failure, message is an error string.
    """
    if not api_key:
        return False, _("API key cannot be empty")

    # Validate API key format (VirusTotal keys are 64 hex characters)
    if len(api_key) != 64 or not all(c in "0123456789abcdef" for c in api_key.lower()):
        return False, _("Invalid API key format (expected 64 hexadecimal characters)")

    # Try keyring first
    keyring = _get_keyring()
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, VT_API_KEY_NAME, api_key)
            logger.info("Stored VirusTotal API key in keyring")
            return True, None
        except Exception as e:
            logger.warning(f"Failed to store in keyring: {e}, considering settings fallback")

    # Keyring unavailable — only persist plaintext to settings if the user has
    # explicitly opted in, since settings.json is readable by any process
    # running as the same user (backup tools, sync clients, later compromise).
    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()

    if not settings_manager.get("allow_plaintext_api_key_fallback"):
        logger.warning(
            "Keyring unavailable and plaintext fallback disabled — refusing to store API key"
        )
        return False, _(
            "System keyring is unavailable. To store the API key without a keyring, "
            "enable the plaintext fallback in preferences (less secure)."
        )

    if settings_manager.set("virustotal_api_key", api_key):
        logger.info("Stored VirusTotal API key in settings (plaintext fallback)")
        return True, _("Stored in settings file (keyring unavailable — less secure)")

    return False, _("Failed to save API key to settings")


def delete_api_key(settings_manager: SettingsManager | None = None) -> bool:
    """
    Remove VirusTotal API key from both keyring and settings.

    Attempts to delete from both storage locations to ensure
    complete removal.

    Args:
        settings_manager: Optional SettingsManager instance.
                         If None, creates a new instance.

    Returns:
        True if deletion was successful from at least one location.
    """
    deleted = False

    # Try to delete from keyring
    keyring = _get_keyring()
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, VT_API_KEY_NAME)
            logger.info("Deleted VirusTotal API key from keyring")
            deleted = True
        except Exception as e:
            # Key might not exist, which is fine
            logger.debug(f"Could not delete from keyring: {e}")

    # Also clear from settings
    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()

    if settings_manager.set("virustotal_api_key", None):
        logger.info("Cleared VirusTotal API key from settings")
        deleted = True

    return deleted


def has_api_key(settings_manager: SettingsManager | None = None) -> bool:
    """
    Check if a VirusTotal API key is configured.

    Args:
        settings_manager: Optional SettingsManager instance for fallback.

    Returns:
        True if an API key is configured, False otherwise.
    """
    return get_api_key(settings_manager) is not None


def mask_api_key(api_key: str | None) -> str:
    """
    Return a masked version of the API key for display.

    Shows only the first 8 characters followed by ellipsis.
    This prevents accidental exposure of the full key in logs or UI.

    Args:
        api_key: The API key to mask.

    Returns:
        Masked API key string (e.g., "a1b2c3d4...") or "Not set" if None.
    """
    if not api_key:
        return _("Not set")
    if len(api_key) < 8:
        return "****"
    return f"{api_key[:8]}..."


def validate_api_key_format(api_key: str) -> tuple[bool, str | None]:
    """
    Validate the format of a VirusTotal API key.

    VirusTotal API keys are 64 hexadecimal characters.

    Args:
        api_key: The API key to validate.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not api_key:
        return False, _("API key cannot be empty")

    if len(api_key) != 64:
        return False, _("API key must be 64 characters (got {length})").format(length=len(api_key))

    if not all(c in "0123456789abcdefABCDEF" for c in api_key):
        return False, _("API key must contain only hexadecimal characters")

    return True, None


# =============================================================================
# Portmaster API token accessors
# =============================================================================
#
# Portmaster's developer API issues opaque tokens via the /api/v1/app/auth
# authorization flow. Format is undocumented and may change, so we treat the
# token as an opaque string and skip format validation.


def get_portmaster_token(settings_manager: SettingsManager | None = None) -> str | None:
    """Return the stored Portmaster API token, or None if not configured."""
    keyring = _get_keyring()
    if keyring is not None:
        try:
            token = keyring.get_password(SERVICE_NAME, PM_API_TOKEN_NAME)
            if token:
                return token
        except Exception as e:
            logger.warning(f"Failed to read Portmaster token from keyring: {e}")

    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()
    return settings_manager.get(PM_SETTINGS_KEY)


def set_portmaster_token(
    token: str, settings_manager: SettingsManager | None = None
) -> tuple[bool, str | None]:
    """Persist the Portmaster API token (keyring preferred, settings fallback gated)."""
    if not token:
        return False, _("Token cannot be empty")

    keyring = _get_keyring()
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, PM_API_TOKEN_NAME, token)
            logger.info("Stored Portmaster token in keyring")
            return True, None
        except Exception as e:
            logger.warning(f"Failed to store Portmaster token in keyring: {e}")

    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()

    if not settings_manager.get("allow_plaintext_api_key_fallback"):
        return False, _(
            "System keyring is unavailable. To store the Portmaster token without a keyring, "
            "enable the plaintext fallback in preferences (less secure)."
        )

    if settings_manager.set(PM_SETTINGS_KEY, token):
        logger.info("Stored Portmaster token in settings (plaintext fallback)")
        return True, _("Stored in settings file (keyring unavailable — less secure)")
    return False, _("Failed to save Portmaster token to settings")


def delete_portmaster_token(settings_manager: SettingsManager | None = None) -> bool:
    """Remove the Portmaster API token from keyring and settings fallback."""
    deleted = False

    keyring = _get_keyring()
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, PM_API_TOKEN_NAME)
            deleted = True
        except Exception as e:
            logger.debug(f"Could not delete Portmaster token from keyring: {e}")

    if settings_manager is None:
        from .settings_manager import SettingsManager

        settings_manager = SettingsManager()

    if settings_manager.set(PM_SETTINGS_KEY, None):
        deleted = True
    return deleted
