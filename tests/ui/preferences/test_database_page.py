# ClamUI Database Page Tests
"""Unit tests for the DatabasePage class."""

from unittest import mock

import pytest


class TestDatabasePageImport:
    """Tests for importing the DatabasePage."""

    def test_import_database_page(self, mock_gi_modules):
        """Test that DatabasePage can be imported."""
        from src.ui.preferences.database_page import DatabasePage

        assert DatabasePage is not None

    def test_database_page_is_class(self, mock_gi_modules):
        """Test that DatabasePage is a class."""
        from src.ui.preferences.database_page import DatabasePage

        assert isinstance(DatabasePage, type)

    def test_database_page_inherits_from_mixin(self, mock_gi_modules):
        """Test that DatabasePage inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.database_page import DatabasePage

        assert issubclass(DatabasePage, PreferencesPageMixin)


class TestDatabasePageCreation:
    """Tests for DatabasePage.create_page() method."""

    @pytest.fixture
    def mock_config_path(self):
        """Provide a mock config path."""
        return "/etc/clamav/freshclam.conf"

    @pytest.fixture
    def widgets_dict(self):
        """Provide an empty widgets dictionary."""
        return {}

    def test_create_page_returns_preferences_page(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Should create a PreferencesPage
        adw.PreferencesPage.assert_called()

    def test_create_page_sets_title_and_icon(self, mock_gi_modules, mock_config_path, widgets_dict):
        """Test create_page sets correct title and icon."""
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        adw.PreferencesPage.return_value = mock_page

        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Should set title and icon_name
        adw.PreferencesPage.assert_called_with(
            title="Database Updates",
            icon_name="software-update-available-symbolic",
        )

    def test_create_page_creates_file_location_group(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page creates file location group."""
        from src.ui.preferences.database_page import DatabasePage

        # We need to mock the helper's method
        with mock.patch(
            "src.ui.preferences.database_page._DatabasePageHelper._create_file_location_group"
        ) as mock_create_file_location:
            DatabasePage.create_page(mock_config_path, widgets_dict)

            # Should call _create_file_location_group
            mock_create_file_location.assert_called_once()

    def test_create_page_creates_all_widgets(self, mock_gi_modules, mock_config_path, widgets_dict):
        """Test create_page creates all required widgets."""
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Check that all expected widgets are in the dict
        expected_widgets = [
            # Paths group
            "DatabaseDirectory",
            "UpdateLogFile",
            "NotifyClamd",
            "LogVerbose",
            "LogSyslog",
            # Updates group
            "Checks",
            "DatabaseMirror",
            # Proxy group
            "HTTPProxyServer",
            "HTTPProxyPort",
            "HTTPProxyUsername",
            "HTTPProxyPassword",
        ]

        for widget_name in expected_widgets:
            assert widget_name in widgets_dict, f"Widget {widget_name} not created"

    def test_create_page_creates_entry_rows_with_icons(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page creates entry rows with appropriate icons."""
        adw = mock_gi_modules["adw"]
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Should create multiple ActionRows (via create_entry_row/create_switch_row compat)
        assert (
            adw.ActionRow.call_count >= 5
        )  # DatabaseDirectory, UpdateLogFile, NotifyClamd, DatabaseMirror, HTTPProxyServer + switches

        # Should create multiple Image icons
        assert gtk.Image.new_from_icon_name.call_count >= 5

    def test_create_page_creates_switch_rows(self, mock_gi_modules, mock_config_path, widgets_dict):
        """Test create_page creates switch rows for boolean settings."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Switch rows are now ActionRows via create_switch_row compat
        # Total ActionRow count includes both entry rows and switch rows
        assert adw.ActionRow.call_count >= 7  # 5 entry + 2 switch

    def test_create_page_creates_spin_buttons(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page creates SpinButtons for numeric settings (1.0+ compatible)."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Should create SpinButtons for Checks and HTTPProxyPort
        # (using create_spin_row helper which uses Gtk.SpinButton)
        assert gtk.SpinButton.call_count >= 2

    def test_create_page_creates_password_entry_row(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page creates password entry for proxy password (1.0+ compatible)."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Entry rows are now ActionRows via create_entry_row compat
        # (create_password_entry_row also uses create_entry_row internally)
        # 5 regular entries + 1 password entry + 2 switch rows = 8 ActionRows
        assert adw.ActionRow.call_count >= 8

    def test_create_page_creates_preference_groups(
        self, mock_gi_modules, mock_config_path, widgets_dict
    ):
        """Test create_page creates all preference groups."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.database_page import DatabasePage

        DatabasePage.create_page(mock_config_path, widgets_dict)

        # Should create at least 3 PreferencesGroups (Paths, Updates, Proxy)
        assert adw.PreferencesGroup.call_count >= 3


class TestDatabasePagePopulateFields:
    """Tests for DatabasePage.populate_fields() method."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config object."""
        config = mock.MagicMock()
        config.has_key = mock.MagicMock(return_value=True)
        config.get_value = mock.MagicMock(return_value="test_value")
        return config

    @pytest.fixture
    def mock_widgets(self):
        """Create mock widgets dictionary."""
        return {
            "DatabaseDirectory": mock.MagicMock(),
            "UpdateLogFile": mock.MagicMock(),
            "NotifyClamd": mock.MagicMock(),
            "LogVerbose": mock.MagicMock(),
            "LogSyslog": mock.MagicMock(),
            "Checks": mock.MagicMock(),
            "DatabaseMirror": mock.MagicMock(),
            "HTTPProxyServer": mock.MagicMock(),
            "HTTPProxyPort": mock.MagicMock(),
            "HTTPProxyUsername": mock.MagicMock(),
            "HTTPProxyPassword": mock.MagicMock(),
        }

    def test_populate_fields_handles_none_config(self, mock_gi_modules, mock_widgets):
        """Test populate_fields handles None config gracefully."""
        from src.ui.preferences.database_page import DatabasePage

        # Should not raise exception
        DatabasePage.populate_fields(None, mock_widgets)

    def test_populate_fields_sets_text_entries(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields sets text entry values."""
        from src.ui.preferences.database_page import DatabasePage

        mock_config.get_value.return_value = "/var/lib/clamav"

        DatabasePage.populate_fields(mock_config, mock_widgets)

        # Should call set_text on entry widgets
        mock_widgets["DatabaseDirectory"].set_text.assert_called_with("/var/lib/clamav")
        mock_widgets["UpdateLogFile"].set_text.assert_called_with("/var/lib/clamav")
        mock_widgets["NotifyClamd"].set_text.assert_called_with("/var/lib/clamav")
        mock_widgets["DatabaseMirror"].set_text.assert_called_with("/var/lib/clamav")

    def test_populate_fields_sets_switch_states(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields sets switch states correctly."""
        from src.ui.preferences.database_page import DatabasePage

        # Test "yes" value
        mock_config.get_value.return_value = "yes"
        DatabasePage.populate_fields(mock_config, mock_widgets)
        mock_widgets["LogVerbose"].set_active.assert_called_with(True)

        # Reset mocks
        mock_widgets["LogVerbose"].reset_mock()
        mock_widgets["LogSyslog"].reset_mock()

        # Test "no" value
        mock_config.get_value.return_value = "no"
        DatabasePage.populate_fields(mock_config, mock_widgets)
        mock_widgets["LogVerbose"].set_active.assert_called_with(False)
        mock_widgets["LogSyslog"].set_active.assert_called_with(False)

    def test_populate_fields_sets_numeric_values(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields sets numeric spin row values."""
        from src.ui.preferences.database_page import DatabasePage

        mock_config.get_value.return_value = "24"

        DatabasePage.populate_fields(mock_config, mock_widgets)

        # Should call set_value with integer
        mock_widgets["Checks"].set_value.assert_called_with(24)
        mock_widgets["HTTPProxyPort"].set_value.assert_called_with(24)

    def test_populate_fields_handles_invalid_numeric_values(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields handles invalid numeric values gracefully."""
        from src.ui.preferences.database_page import DatabasePage

        mock_config.get_value.return_value = "not_a_number"

        # Should not raise exception
        DatabasePage.populate_fields(mock_config, mock_widgets)

    def test_populate_fields_sets_proxy_credentials(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields sets proxy username and password."""
        from src.ui.preferences.database_page import DatabasePage

        mock_config.get_value.return_value = "proxy_user"

        DatabasePage.populate_fields(mock_config, mock_widgets)

        # Should call set_text on proxy widgets
        mock_widgets["HTTPProxyUsername"].set_text.assert_called_with("proxy_user")
        mock_widgets["HTTPProxyPassword"].set_text.assert_called_with("proxy_user")

    def test_populate_fields_skips_missing_keys(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields skips keys not in config."""
        from src.ui.preferences.database_page import DatabasePage

        # Simulate missing keys
        mock_config.has_key.return_value = False

        DatabasePage.populate_fields(mock_config, mock_widgets)

        # Should not call set_text/set_active for missing keys
        mock_widgets["DatabaseDirectory"].set_text.assert_not_called()


class TestDatabasePageCollectData:
    """Tests for DatabasePage.collect_data() method."""

    @pytest.fixture
    def mock_widgets(self):
        """Create mock widgets dictionary with default return values."""
        widgets = {
            "DatabaseDirectory": mock.MagicMock(),
            "UpdateLogFile": mock.MagicMock(),
            "NotifyClamd": mock.MagicMock(),
            "LogVerbose": mock.MagicMock(),
            "LogSyslog": mock.MagicMock(),
            "Checks": mock.MagicMock(),
            "DatabaseMirror": mock.MagicMock(),
            "HTTPProxyServer": mock.MagicMock(),
            "HTTPProxyPort": mock.MagicMock(),
            "HTTPProxyUsername": mock.MagicMock(),
            "HTTPProxyPassword": mock.MagicMock(),
        }

        # Set default return values
        widgets["DatabaseDirectory"].get_text.return_value = "/var/lib/clamav"
        widgets["UpdateLogFile"].get_text.return_value = "/var/log/clamav/freshclam.log"
        widgets["NotifyClamd"].get_text.return_value = "/etc/clamav/clamd.conf"
        widgets["LogVerbose"].get_active.return_value = True
        widgets["LogSyslog"].get_active.return_value = False
        widgets["Checks"].get_value.return_value = 24
        widgets["DatabaseMirror"].get_text.return_value = "database.clamav.net"
        widgets["HTTPProxyServer"].get_text.return_value = "proxy.example.com"
        widgets["HTTPProxyPort"].get_value.return_value = 8080
        widgets["HTTPProxyUsername"].get_text.return_value = "proxyuser"
        widgets["HTTPProxyPassword"].get_text.return_value = "proxypass"

        return widgets

    def test_collect_data_returns_dict(self, mock_gi_modules, mock_widgets):
        """Test collect_data returns a dictionary."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        assert isinstance(result, dict)

    def test_collect_data_includes_all_text_fields(self, mock_gi_modules, mock_widgets):
        """Test collect_data includes all text entry fields."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        assert result["DatabaseDirectory"] == "/var/lib/clamav"
        assert result["UpdateLogFile"] == "/var/log/clamav/freshclam.log"
        assert result["NotifyClamd"] == "/etc/clamav/clamd.conf"
        assert result["DatabaseMirror"] == "database.clamav.net"

    def test_collect_data_converts_switch_to_yes_no(self, mock_gi_modules, mock_widgets):
        """Test collect_data converts switch states to yes/no strings."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        # LogVerbose is True -> "yes"
        assert result["LogVerbose"] == "yes"
        # LogSyslog is False -> "no"
        assert result["LogSyslog"] == "no"

    def test_collect_data_converts_numeric_to_string(self, mock_gi_modules, mock_widgets):
        """Test collect_data converts numeric values to strings."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        assert result["Checks"] == "24"
        assert isinstance(result["Checks"], str)

    def test_collect_data_includes_proxy_settings(self, mock_gi_modules, mock_widgets):
        """Test collect_data includes all proxy settings."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        assert result["HTTPProxyServer"] == "proxy.example.com"
        assert result["HTTPProxyPort"] == "8080"
        assert result["HTTPProxyUsername"] == "proxyuser"
        assert result["HTTPProxyPassword"] == "proxypass"

    def test_collect_data_excludes_empty_text_fields(self, mock_gi_modules, mock_widgets):
        """Test collect_data excludes empty text fields."""
        from src.ui.preferences.database_page import DatabasePage

        # Set some fields to empty
        mock_widgets["DatabaseDirectory"].get_text.return_value = ""
        mock_widgets["DatabaseMirror"].get_text.return_value = ""

        result = DatabasePage.collect_data(mock_widgets)

        # Empty fields should not be in result
        assert "DatabaseDirectory" not in result
        assert "DatabaseMirror" not in result

    def test_collect_data_excludes_zero_proxy_port(self, mock_gi_modules, mock_widgets):
        """Test collect_data excludes proxy port when set to 0."""
        from src.ui.preferences.database_page import DatabasePage

        # Set proxy port to 0
        mock_widgets["HTTPProxyPort"].get_value.return_value = 0

        result = DatabasePage.collect_data(mock_widgets)

        # Port 0 should not be in result
        assert "HTTPProxyPort" not in result

    def test_collect_data_excludes_empty_proxy_credentials(self, mock_gi_modules, mock_widgets):
        """Test collect_data excludes empty proxy credentials."""
        from src.ui.preferences.database_page import DatabasePage

        # Set proxy credentials to empty
        mock_widgets["HTTPProxyUsername"].get_text.return_value = ""
        mock_widgets["HTTPProxyPassword"].get_text.return_value = ""

        result = DatabasePage.collect_data(mock_widgets)

        # Empty credentials should not be in result
        assert "HTTPProxyUsername" not in result
        assert "HTTPProxyPassword" not in result

    def test_collect_data_always_includes_switches(self, mock_gi_modules, mock_widgets):
        """Test collect_data always includes switch values."""
        from src.ui.preferences.database_page import DatabasePage

        result = DatabasePage.collect_data(mock_widgets)

        # Switches should always be present
        assert "LogVerbose" in result
        assert "LogSyslog" in result

    def test_collect_data_skips_missing_widgets_without_crashing(self, mock_gi_modules):
        """Test collect_data handles missing widget keys safely."""
        from src.ui.preferences.database_page import DatabasePage

        partial_widgets = {
            "LogVerbose": mock.MagicMock(get_active=lambda: True),
            "LogSyslog": mock.MagicMock(get_active=lambda: False),
        }

        result = DatabasePage.collect_data(partial_widgets)

        assert result["LogVerbose"] == "yes"
        assert result["LogSyslog"] == "no"
        assert "Checks" not in result
        assert "DatabaseDirectory" not in result

    def test_collect_data_returns_empty_when_page_never_created(self, mock_gi_modules):
        """collect_data must return {} for an empty widgets dict.

        Collecting from an empty dict would include an empty
        DatabaseCustomURL list, which Save & Apply translates into
        remove_key("DatabaseCustomURL") — stripping the user's custom
        signature URLs even though the Database page was never opened.
        """
        from src.ui.preferences.database_page import DatabasePage

        assert DatabasePage.collect_data({}) == {}

    def test_collect_data_skips_invalid_numeric_values(self, mock_gi_modules, mock_widgets):
        """Test collect_data ignores invalid numeric values instead of raising."""
        from src.ui.preferences.database_page import DatabasePage

        mock_widgets["Checks"].get_value.return_value = "invalid"
        mock_widgets["HTTPProxyPort"].get_value.return_value = "not-a-number"

        result = DatabasePage.collect_data(mock_widgets)

        assert "Checks" not in result
        assert "HTTPProxyPort" not in result


class TestDatabasePageHelper:
    """Tests for _DatabasePageHelper class."""

    def test_helper_inherits_from_mixin(self, mock_gi_modules):
        """Test that _DatabasePageHelper inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.database_page import _DatabasePageHelper

        assert issubclass(_DatabasePageHelper, PreferencesPageMixin)

    def test_helper_has_mixin_methods(self, mock_gi_modules):
        """Test that _DatabasePageHelper has mixin methods."""
        from src.ui.preferences.database_page import _DatabasePageHelper

        # Should have all mixin methods
        assert hasattr(_DatabasePageHelper, "_create_permission_indicator")
        assert hasattr(_DatabasePageHelper, "_create_file_location_group")

    def test_helper_can_be_instantiated(self, mock_gi_modules):
        """Test that _DatabasePageHelper can be instantiated."""
        from src.ui.preferences.database_page import _DatabasePageHelper

        # Should be able to create an instance
        instance = _DatabasePageHelper()
        assert instance is not None


class TestParseCustomUrls:
    """Tests for _parse_custom_urls function."""

    def test_single_url(self, mock_gi_modules):
        """Single URL is parsed correctly."""
        from src.ui.preferences.database_page import _parse_custom_urls

        result = _parse_custom_urls("https://example.com/sigs.ndb")
        assert result == ["https://example.com/sigs.ndb"]

    def test_multiline_urls(self, mock_gi_modules):
        """Multiple URLs separated by newlines."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """https://example.com/sig1.ndb
https://example.com/sig2.hdb"""
        result = _parse_custom_urls(text)
        assert result == [
            "https://example.com/sig1.ndb",
            "https://example.com/sig2.hdb",
        ]

    def test_strips_databasecustomurl_prefix(self, mock_gi_modules):
        """DatabaseCustomURL prefix is stripped."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = "DatabaseCustomURL https://example.com/sigs.ndb"
        result = _parse_custom_urls(text)
        assert result == ["https://example.com/sigs.ndb"]

    def test_prefix_case_insensitive(self, mock_gi_modules):
        """Prefix stripping is case-insensitive."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = "databasecustomurl https://example.com/sigs.ndb"
        result = _parse_custom_urls(text)
        assert result == ["https://example.com/sigs.ndb"]

    def test_skips_comments(self, mock_gi_modules):
        """Comment lines are skipped."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """# This is a comment
https://example.com/sigs.ndb
# Another comment"""
        result = _parse_custom_urls(text)
        assert result == ["https://example.com/sigs.ndb"]

    def test_skips_empty_lines(self, mock_gi_modules):
        """Empty lines are skipped."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """

https://example.com/sigs.ndb

"""
        result = _parse_custom_urls(text)
        assert result == ["https://example.com/sigs.ndb"]

    def test_skips_invalid_urls(self, mock_gi_modules):
        """Invalid URLs (no scheme) are skipped."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """https://example.com/valid.ndb
www.example.com/invalid.ndb
example.com/also-invalid.ndb"""
        result = _parse_custom_urls(text)
        assert result == ["https://example.com/valid.ndb"]

    def test_supports_all_schemes(self, mock_gi_modules):
        """All valid schemes are accepted."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """https://example.com/https.ndb
http://example.com/http.ndb
ftp://example.com/ftp.ndb
ftps://example.com/ftps.ndb
file:///var/lib/clamav/local.ndb"""
        result = _parse_custom_urls(text)
        assert len(result) == 5
        assert "https://example.com/https.ndb" in result
        assert "http://example.com/http.ndb" in result
        assert "ftp://example.com/ftp.ndb" in result
        assert "ftps://example.com/ftps.ndb" in result
        assert "file:///var/lib/clamav/local.ndb" in result

    def test_mixed_format(self, mock_gi_modules):
        """Mix of prefixed and raw URLs."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = """DatabaseCustomURL https://example.com/prefixed.ndb
https://example.com/raw.ndb"""
        result = _parse_custom_urls(text)
        assert result == [
            "https://example.com/prefixed.ndb",
            "https://example.com/raw.ndb",
        ]

    def test_empty_string(self, mock_gi_modules):
        """Empty string returns empty list."""
        from src.ui.preferences.database_page import _parse_custom_urls

        result = _parse_custom_urls("")
        assert result == []

    def test_whitespace_only(self, mock_gi_modules):
        """Whitespace-only string returns empty list."""
        from src.ui.preferences.database_page import _parse_custom_urls

        result = _parse_custom_urls("   \n  \n   ")
        assert result == []

    def test_urlhaus_real_url(self, mock_gi_modules):
        """URLhaus URL is parsed correctly."""
        from src.ui.preferences.database_page import _parse_custom_urls

        text = "DatabaseCustomURL https://urlhaus.abuse.ch/downloads/urlhaus.ndb"
        result = _parse_custom_urls(text)
        assert result == ["https://urlhaus.abuse.ch/downloads/urlhaus.ndb"]


class TestSuggestedSignatureUrls:
    """Tests for SUGGESTED_SIGNATURE_URLS constant."""

    def test_suggested_urls_exists(self, mock_gi_modules):
        """SUGGESTED_SIGNATURE_URLS constant exists."""
        from src.ui.preferences.database_page import SUGGESTED_SIGNATURE_URLS

        assert SUGGESTED_SIGNATURE_URLS is not None
        assert isinstance(SUGGESTED_SIGNATURE_URLS, list)

    def test_suggested_urls_contains_urlhaus(self, mock_gi_modules):
        """SUGGESTED_SIGNATURE_URLS contains URLhaus."""
        from src.ui.preferences.database_page import SUGGESTED_SIGNATURE_URLS

        urls = [sig["url"] for sig in SUGGESTED_SIGNATURE_URLS]
        assert "https://urlhaus.abuse.ch/downloads/urlhaus.ndb" in urls

    def test_suggested_urls_have_required_fields(self, mock_gi_modules):
        """Each suggested URL has required fields."""
        from src.ui.preferences.database_page import SUGGESTED_SIGNATURE_URLS

        for sig in SUGGESTED_SIGNATURE_URLS:
            assert "url" in sig
            assert "name" in sig
            assert "description" in sig
            assert sig["url"].startswith(("http://", "https://"))

    def test_suggested_urls_contains_interserver(self, mock_gi_modules):
        """SUGGESTED_SIGNATURE_URLS contains InterServer databases."""
        from src.ui.preferences.database_page import SUGGESTED_SIGNATURE_URLS

        urls = [sig["url"] for sig in SUGGESTED_SIGNATURE_URLS]
        assert "http://sigs.interserver.net/interserver256.hdb" in urls
        assert "http://sigs.interserver.net/shell.ldb" in urls


class TestThirdPartyProviders:
    """Tests for THIRD_PARTY_PROVIDERS constant."""

    def test_providers_exists(self, mock_gi_modules):
        """THIRD_PARTY_PROVIDERS constant exists and is a list."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        assert THIRD_PARTY_PROVIDERS is not None
        assert isinstance(THIRD_PARTY_PROVIDERS, list)
        assert len(THIRD_PARTY_PROVIDERS) >= 4

    def test_providers_have_required_fields(self, mock_gi_modules):
        """Each provider has all required fields."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        required_fields = {"name", "icon", "description", "detail", "url", "free", "registration"}
        for provider in THIRD_PARTY_PROVIDERS:
            assert required_fields.issubset(provider.keys()), (
                f"Provider {provider.get('name', '?')} missing fields: "
                f"{required_fields - provider.keys()}"
            )

    def test_providers_include_known_providers(self, mock_gi_modules):
        """Known providers are included."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        names = [p["name"] for p in THIRD_PARTY_PROVIDERS]
        assert "URLhaus" in names
        assert "SecuriteInfo" in names
        assert "SaneSecurity" in names
        assert "InterServer" in names

    def test_securiteinfo_requires_registration(self, mock_gi_modules):
        """SecuriteInfo is marked as requiring registration."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        securiteinfo = [p for p in THIRD_PARTY_PROVIDERS if p["name"] == "SecuriteInfo"]
        assert len(securiteinfo) == 1
        assert securiteinfo[0]["registration"] is True

    def test_urlhaus_no_registration(self, mock_gi_modules):
        """URLhaus is marked as not requiring registration."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        urlhaus = [p for p in THIRD_PARTY_PROVIDERS if p["name"] == "URLhaus"]
        assert len(urlhaus) == 1
        assert urlhaus[0]["registration"] is False

    def test_all_providers_are_free(self, mock_gi_modules):
        """All listed providers have free tiers."""
        from src.ui.preferences.database_page import THIRD_PARTY_PROVIDERS

        for provider in THIRD_PARTY_PROVIDERS:
            assert provider["free"] is True, f"{provider['name']} should be free"
