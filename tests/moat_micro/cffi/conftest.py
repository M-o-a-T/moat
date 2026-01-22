"""
Create the solib if it doesn't exist
"""

from __future__ import annotations

from pathlib import Path

here = Path(__file__).parent
if not (here / "itest.so").exists():
    from subprocess import run

    run(["cc", "--shared", "-o", "itest.so", "itest.c"], check=True, cwd=str(here))


def pytest_configure(config):
    """Register custom markers and configure warnings."""
    config.addinivalue_line(
        "filterwarnings", "ignore:cannot collect test class 'Test':pytest.PytestCollectionWarning"
    )
