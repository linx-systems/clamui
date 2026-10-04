from unittest.mock import MagicMock


def test_selected_row_notifies_callback_and_ignores_empty_selection(mock_gi_modules):
    from src.ui.sidebar import NavigationSidebar

    callback = MagicMock()
    sidebar = NavigationSidebar(on_view_selected=callback)

    sidebar._on_row_selected(sidebar._list_box, None)
    sidebar._on_row_selected(sidebar._list_box, sidebar._rows["logs"])

    callback.assert_called_once_with("logs")
