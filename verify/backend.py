"""Validated local and no-delete S3 options for executable verification harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendOptions:
    """One CLI backend selection for a disposable verification deployment."""

    name: str = "local"
    bucket: str | None = None
    region: str | None = None
    prefix: str | None = None

    def validate(self) -> None:
        if self.name == "local":
            if any(value is not None for value in (self.bucket, self.region, self.prefix)):
                raise ValueError("local backend does not accept S3 location values")
            return
        if self.name != "s3":
            raise ValueError(f"unsupported verification backend: {self.name}")
        if not all((self.bucket, self.region, self.prefix)):
            raise ValueError("S3 verification requires bucket, region, and prefix")
        assert self.prefix is not None
        child = self.prefix.removeprefix("groundhog-tests/")
        if child == self.prefix or not child or "/" in child:
            raise ValueError("S3 verification prefix must be groundhog-tests/<run-id>")

    def init_arguments(self, root: Path) -> list[str]:
        """Return backend arguments for one process-specific deployment prefix."""
        self.validate()
        if self.name == "local":
            return []
        assert self.bucket is not None
        assert self.region is not None
        assert self.prefix is not None
        return [
            "--backend",
            "s3",
            "--bucket",
            self.bucket,
            "--region",
            self.region,
            "--prefix",
            f"{self.prefix}/{root.name}",
        ]
