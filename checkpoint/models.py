from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import datetime


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class StepRecord:
    run_id: str
    step: str
    status: StepStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    duration_ms: Optional[float] = None


@dataclass
class RunRecord:
    run_id: str
    created_at: Optional[datetime.datetime] = None
    metadata: Optional[dict] = field(default=None)
