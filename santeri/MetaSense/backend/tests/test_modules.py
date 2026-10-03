"""Small module-level checks for the deliberately synthetic pipeline."""

import pytest

from app.config import AllsolveConfig, AllsolveConfigurationError
from app.models import DesignInput
from app.optimization import rank_toy_designs


def test_allsolve_host_validation() -> None:
    config = AllsolveConfig(access_key="id", secret_key="secret", host="https://example.com/path")
    with pytest.raises(AllsolveConfigurationError, match="root HTTPS URL"):
        config.validate()
    AllsolveConfig(access_key="id", secret_key="secret").validate()


def test_toy_ranking_is_deterministic() -> None:
    smaller = DesignInput(pillar_diameter_nm=200)
    larger = DesignInput(pillar_diameter_nm=300)
    assert rank_toy_designs([smaller, larger]) == [larger, smaller]
