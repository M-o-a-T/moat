# noqa:D100 pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

import json
import pytest
import subprocess


@pytest.fixture(autouse=True)
def check_no_new_coredumps():
    """
    Fixture that ensures no new coredumps are created during test execution.

    This fixture records the current coredump state before tests run, and
    verifies after tests complete that no new coredumps have been created.
    """
    # Get initial coredump state before tests
    try:
        result = subprocess.run(
            ["coredumpctl", "-1", "--json=short"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            initial_dumps = json.loads(result.stdout)
        else:
            # No coredumps exist yet
            initial_dumps = []
    except (FileNotFoundError, json.JSONDecodeError):
        # coredumpctl not available or no dumps
        initial_dumps = []

    # Run the tests
    yield

    # Check for new coredumps after tests
    try:
        result = subprocess.run(
            ["coredumpctl", "-1", "--json=short"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            final_dumps = json.loads(result.stdout)
        else:
            final_dumps = []
    except (FileNotFoundError, json.JSONDecodeError):
        final_dumps = []

    # Compare dumps
    if initial_dumps != final_dumps:
        msg = (
            "New coredump(s) detected during test execution!\n"
            f"Initial: {initial_dumps}\n"
            f"Final: {final_dumps}"
        )
        pytest.fail(msg)
