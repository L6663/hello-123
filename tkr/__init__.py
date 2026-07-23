"""Text Knowledge Reader staged hardening and literary knowledge package."""

__version__ = "6.0.0-alpha1"

# Historical Stage 6-R1 deterministic correctness fixes remain active for the
# v5.9 base runtime inherited by v6. They grant no acceptance, release-candidate,
# certification, or freeze authority.
from .stage6_r1_remediation import apply_stage6_r1_remediation as _apply_stage6_r1_remediation

_apply_stage6_r1_remediation()
del _apply_stage6_r1_remediation

from .stage6_r1_heading_patch import apply_stage6_r1_heading_patch as _apply_stage6_r1_heading_patch

_apply_stage6_r1_heading_patch()
del _apply_stage6_r1_heading_patch

# Structured sources require one splice candidate per incoherent chapter
# suffix rather than hundreds of fixed-window transitions.
from . import anomaly_detection as _stage6_r1_anomaly
from .stage6_r1_collage import build_structured_anomaly_inspector as _build_structured_anomaly_inspector

_stage6_r1_anomaly.inspect_source_anomalies = _build_structured_anomaly_inspector(
    _stage6_r1_anomaly.inspect_source_anomalies
)
del _build_structured_anomaly_inspector
del _stage6_r1_anomaly

# Stage 6 Notion R1 hardening is applied before public Notion modules are
# imported so installed commands and bundled Skill commands share one contract.
from .stage6_notion_r1 import apply_stage6_notion_r1 as _apply_stage6_notion_r1

_apply_stage6_notion_r1()
del _apply_stage6_notion_r1
