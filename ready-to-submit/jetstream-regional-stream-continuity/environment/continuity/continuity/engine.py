"""Regional continuity controller used by continuityctl."""

from __future__ import annotations

from .consumers import ConsumerMixin
from .fencing import FencingMixin
from .generation import GenerationMixin
from .policy import ContinuityEngine as BaseContinuityEngine
from .publish import PublishMixin
from .reconcile import ReconcileMixin
from .replay import ReplayMixin
from .retention import RetentionMixin


class ContinuityEngine(
    PublishMixin,
    GenerationMixin,
    ConsumerMixin,
    ReconcileMixin,
    ReplayMixin,
    FencingMixin,
    RetentionMixin,
    BaseContinuityEngine,
):
    """Operator-facing continuity controller."""
