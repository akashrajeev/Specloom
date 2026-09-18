from __future__ import annotations

import os

from .aws import AwsProjectRepository
from .repository import MemoryProjectRepository, ProjectRepository


def get_project_repository() -> ProjectRepository:
    if os.getenv("SPECL00M_STORAGE_MODE", "memory").lower() == "aws":
        return AwsProjectRepository()
    return MemoryProjectRepository()
