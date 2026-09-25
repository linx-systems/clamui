"""
Hypothesis profile registration for ClamUI property tests.

Profiles:
    dev   - fast local iteration (default)
    ci    - more examples, tolerant of slow targets
    debug - minimal examples with verbose shrinking output

Select via HYPOTHESIS_PROFILE env var.
"""

import os

from hypothesis import HealthCheck, Verbosity, settings

settings.register_profile(
    "dev",
    max_examples=100,
    deadline=500,
)
settings.register_profile(
    "ci",
    max_examples=300,
    deadline=1000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.register_profile(
    "debug",
    max_examples=10,
    verbosity=Verbosity.verbose,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
