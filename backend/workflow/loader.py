from __future__ import annotations
import json
from pathlib import Path
from .models import WorkflowIR

def load_workflow(path: str | Path) -> WorkflowIR:
    return WorkflowIR.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
