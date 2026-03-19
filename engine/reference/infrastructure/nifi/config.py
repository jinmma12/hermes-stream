"""NiFi Integration Configuration.

Pydantic settings model for configuring the Hermes-NiFi connection.
All settings can be overridden via environment variables prefixed with
``VESSEL_NIFI_``.

Example environment variables::

    VESSEL_NIFI_BASE_URL=https://nifi.internal:8443/nifi-api
    VESSEL_NIFI_USERNAME=admin
    VESSEL_NIFI_PASSWORD=secret
    VESSEL_NIFI_ENABLED=true
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class NiFiConfig(BaseSettings):
    """Configuration for connecting Hermes to an Apache NiFi instance.

    Attributes:
        base_url: NiFi REST API base URL (no trailing slash).
        username: Username for NiFi token-based authentication.
        password: Password for NiFi token-based authentication.
        token: Pre-existing bearer token (skips login if provided).
        token_refresh_interval: How often to refresh the auth token, in seconds.
        provenance_poll_interval: Polling interval when waiting for provenance
            results, in seconds.
        provenance_max_wait: Maximum time to wait for a provenance query or
            flow-file completion, in seconds.
        sync_interval: Interval for periodic sync of NiFi process groups to
            Hermes pipelines, in seconds.
        request_timeout: HTTP request timeout for individual API calls, in seconds.
        max_retries: Maximum number of retries for transient HTTP errors.
        enabled: Master switch. When ``False``, the NiFi integration is dormant
            and no API calls are made.
    """

    base_url: str = Field(
        default="http://localhost:8080/nifi-api",
        description="NiFi REST API base URL",
    )
    username: Optional[str] = Field(
        default=None,
        description="Username for token-based auth",
    )
    password: Optional[str] = Field(
        default=None,
        description="Password for token-based auth",
    )
    token: Optional[str] = Field(
        default=None,
        description="Pre-existing bearer token (skips login)",
    )
    token_refresh_interval: int = Field(
        default=300,
        ge=30,
        description="Token refresh interval in seconds",
    )
    provenance_poll_interval: float = Field(
        default=1.0,
        gt=0,
        description="Provenance polling interval in seconds",
    )
    provenance_max_wait: int = Field(
        default=300,
        ge=10,
        description="Max wait for provenance query completion in seconds",
    )
    sync_interval: int = Field(
        default=60,
        ge=10,
        description="Process group sync interval in seconds",
    )
    request_timeout: float = Field(
        default=30.0,
        gt=0,
        description="HTTP request timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Max retries for transient HTTP errors",
    )
    enabled: bool = Field(
        default=False,
        description="Enable NiFi integration (opt-in)",
    )

    model_config = {
        "env_prefix": "VESSEL_NIFI_",
        "env_file": ".env",
        "case_sensitive": False,
    }
