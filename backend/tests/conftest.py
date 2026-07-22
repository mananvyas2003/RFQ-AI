"""Shared pytest fixtures for RFQ-AI backend tests."""
from __future__ import annotations

import pytest

import app.services.optimizer as optimizer_mod
from app.services.catalog.mock_provider import MockProvider
from app.services.catalog.registry import ProviderRegistry


@pytest.fixture
def mock_only_registry(monkeypatch: pytest.MonkeyPatch) -> ProviderRegistry:
    """Force the optimizer to use only the built-in mock catalog.

    Live providers (Nexar / local scrape DB) mask the alias→exact-lookup seam
    that these tests target, so pin the registry to mock-only.
    """
    mock = MockProvider()
    mock.enabled = True
    registry = ProviderRegistry(providers=[mock])
    monkeypatch.setattr(optimizer_mod, "registry", registry)
    return registry
