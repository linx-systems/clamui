"""
Internationalization (i18n) support for ClamUI.

This module initializes gettext for the ClamUI application and exports
the translation functions used throughout the codebase.

Usage:
    from ..core.i18n import _, ngettext, N_, pgettext

    label.set_text(_("Scan Complete"))
    label.set_text(_("Found {count} threats").format(count=n))
    msg = ngettext("{n} file scanned", "{n} files scanned", count).format(n=count)

    # Module-level constants (deferred translation):
    ITEMS = [N_("Scan"), N_("Update")]
    # At display time: _(item)
"""

import gettext
import logging
import os

DOMAIN = "clamui"

__all__ = [
    "DOMAIN",
    "N_",
    "_",
    "apply_language_override",
    "get_available_languages",
    "ngettext",
    "pgettext",
]

logger = logging.getLogger(__name__)


def _get_locale_dir() -> str | None:
    """
    Determine the locale directory based on the runtime context.

    Checks in order:
    1. AppImage: $APPDIR/usr/share/locale
    2. Flatpak: /app/share/locale
    3. Development / pip install: src/locale relative to this file
    4. System: /usr/share/locale (fallback)

    Returns:
        Path to the locale directory, or None to use system default.
    """
    # AppImage bundles locale in $APPDIR/usr/share/locale
    appdir = os.environ.get("APPDIR")
    if appdir:
        locale_dir = os.path.join(appdir, "usr", "share", "locale")
        if os.path.isdir(locale_dir):
            return locale_dir

    # Flatpak uses /app/share/locale
    if os.path.exists("/.flatpak-info"):
        locale_dir = "/app/share/locale"
        if os.path.isdir(locale_dir):
            return locale_dir

    # Development / editable install: src/locale relative to this module
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dev_locale = os.path.join(src_dir, "locale")
    if os.path.isdir(dev_locale):
        return dev_locale

    # System install fallback
    system_locale = "/usr/share/locale"
    if os.path.isdir(system_locale):
        return system_locale

    return None


def _init_gettext():
    """Initialize gettext with the appropriate locale directory."""
    locale_dir = _get_locale_dir()

    if locale_dir:
        gettext.bindtextdomain(DOMAIN, locale_dir)

    gettext.textdomain(DOMAIN)


def apply_language_override(language_code: str) -> None:
    """
    Apply a language override by setting the LANGUAGE environment variable.

    Call this BEFORE _init_gettext() (i.e. before this module is imported
    elsewhere) for it to take effect on all gettext lookups.

    Args:
        language_code: An ISO language code (e.g. "de", "zh_CN") or
                       "auto" to use the system default.
    """
    if language_code and language_code != "auto":
        os.environ["LANGUAGE"] = language_code
        logger.info("Language override applied: %s", language_code)


def get_available_languages() -> list[tuple[str, str]]:
    """
    Return a list of available languages as (code, display_name) tuples.

    Reads the po/LINGUAS file (or scans the locale directory) to discover
    which translations are available. Always includes "auto" as the first
    entry for system-default detection.

    Returns:
        List of (language_code, display_name) tuples.
        The first entry is always ("auto", "Automatic (System)").
    """
    # Human-readable names for language codes
    language_names: dict[str, str] = {
        "ar": "العربية",
        "cs": "Čeština",
        "da": "Dansk",
        "de": "Deutsch",
        "el": "Ελληνικά",
        "en": "English",
        "es": "Español",
        "fi": "Suomi",
        "fr": "Français",
        "he": "עברית",
        "hi": "हिन्दी",
        "hu": "Magyar",
        "id": "Bahasa Indonesia",
        "it": "Italiano",
        "ja": "日本語",
        "ko": "한국어",
        "nb": "Norsk Bokmål",
        "nl": "Nederlands",
        "pl": "Polski",
        "pt": "Português",
        "pt_BR": "Português (Brasil)",
        "ro": "Română",
        "ru": "Русский",
        "sv": "Svenska",
        "th": "ไทย",
        "tr": "Türkçe",
        "uk": "Українська",
        "vi": "Tiếng Việt",
        "zh_CN": "简体中文",
        "zh_TW": "繁體中文",
    }

    languages: list[tuple[str, str]] = []

    # Try to find LINGUAS file relative to this module
    # src/core/i18n.py -> src/ -> project_root/po/LINGUAS
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(src_dir)
    linguas_path = os.path.join(project_root, "po", "LINGUAS")

    # In AppImage/Flatpak, LINGUAS isn't bundled - scan locale dir instead
    if not os.path.isfile(linguas_path):
        locale_dir = _get_locale_dir()
        if locale_dir and os.path.isdir(locale_dir):
            for entry in sorted(os.listdir(locale_dir)):
                mo_path = os.path.join(locale_dir, entry, "LC_MESSAGES", "clamui.mo")
                if os.path.isfile(mo_path):
                    name = language_names.get(entry, entry)
                    languages.append((entry, name))
            return languages
        return languages

    with open(linguas_path, encoding="utf-8") as f:
        for line in f:
            code = line.split("#", 1)[0].strip()
            if not code:
                continue
            name = language_names.get(code, code)
            languages.append((code, name))

    languages.sort(key=lambda x: x[1])
    return languages


# Initialize on import
_init_gettext()

# Export translation functions
_ = gettext.gettext
ngettext = gettext.ngettext
pgettext = gettext.pgettext
_TRANSLATION_FUNCTIONS = (_, ngettext, pgettext)

# N_ marks strings for extraction by xgettext but returns them unchanged.
# The actual translation happens when _() is called at display time.
# This must NOT call gettext.gettext -- it's an identity function.


def N_(message: str) -> str:
    """Mark a string for translation extraction without translating it."""
    return message
