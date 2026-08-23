"""Regression tests for shared pytest fixtures."""

import importlib
import inspect
import os
import sys
from typing import Any, cast

from tests import conftest


def test_mock_gi_modules_restores_preexisting_flatpak_module():
    """GI mocking must not invalidate the Flatpak module used by autouse setup."""
    module_name = "src.core.flatpak"
    original_module = importlib.import_module(module_name)

    fixture = inspect.unwrap(conftest.mock_gi_modules)()
    next(fixture)
    try:
        replacement_module = importlib.import_module(module_name)
        assert replacement_module is not original_module
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass

    assert sys.modules[module_name] is original_module


def test_reset_flatpak_cache_restores_state_after_test_failure():
    """The autouse fixture must restore global state when a test raises."""
    flatpak_module = cast(Any, importlib.import_module("src.core.flatpak"))
    flatpak_module._flatpak_detected = True
    original_exists = os.path.exists

    fixture = inspect.unwrap(conftest.reset_flatpak_cache)()
    next(fixture)
    assert flatpak_module._flatpak_detected is None
    assert os.path.exists is not original_exists

    try:
        fixture.throw(RuntimeError("simulated test failure"))
    except RuntimeError:
        pass

    assert flatpak_module._flatpak_detected is True
    assert os.path.exists is original_exists
