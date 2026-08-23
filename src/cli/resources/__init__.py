# ClamUI CLI resource data
"""
Installed-package resources for the :mod:`src.cli` subpackage.

This package exists so that data files shipped inside the wheel (currently the
polkit policy for the privileged helper) can be located with
``importlib.resources`` after installation, where the source checkout's
top-level ``data/`` directory no longer exists.
"""
