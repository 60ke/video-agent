from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VersionedContract(Contract):
    schema_version: int = 3
