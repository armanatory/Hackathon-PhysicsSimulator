"""Server-side Allsolve configuration; secret values never enter API responses."""

import importlib.util
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


class AllsolveConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class AllsolveConfig:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    host: str = "https://allsolve.quanscient.com/"

    @property
    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def validate(self) -> None:
        if not self.configured:
            raise AllsolveConfigurationError(
                "Allsolve mode requires ALLSOLVE_ACCESS_KEY and ALLSOLVE_SECRET_KEY on the server"
            )
        parsed = urlparse(self.host)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise AllsolveConfigurationError("ALLSOLVE_HOST must be a root HTTPS URL")


def allsolve_config_from_environment() -> AllsolveConfig:
    return AllsolveConfig(
        access_key=os.getenv("ALLSOLVE_ACCESS_KEY", "").strip(),
        secret_key=os.getenv("ALLSOLVE_SECRET_KEY", "").strip(),
        host=os.getenv("ALLSOLVE_HOST", "https://allsolve.quanscient.com/").strip(),
    )


def allsolve_sdk_installed() -> bool:
    return importlib.util.find_spec("allsolve") is not None
