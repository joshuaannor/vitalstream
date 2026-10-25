"""Shared pytest fixtures. Sample data lives in samples.py."""

import pytest

from samples import make_bundle


@pytest.fixture
def bundle() -> dict:
    """A fresh, valid FHIR bundle; each test gets its own copy to modify."""
    return make_bundle()
