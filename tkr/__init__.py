"""Text Knowledge Reader staged hardening package."""

__version__ = "5.9.0-alpha1"

# Stage 6-R1 applies narrow deterministic correctness fixes before public
# submodules are imported. They grant no acceptance, release-candidate,
# certification, or freeze authority.
from .stage6_r1_remediation import apply_stage6_r1_remediation as _apply_stage6_r1_remediation

_apply_stage6_r1_remediation()
del _apply_stage6_r1_remediation

# Structured sources require one splice candidate per incoherent chapter
# suffix rather than hundreds of fixed-window transitions.
from . import anomaly_detection as _stage6_r1_anomaly
from .stage6_r1_collage import build_structured_anomaly_inspector as _build_structured_anomaly_inspector

_stage6_r1_anomaly.inspect_source_anomalies = _build_structured_anomaly_inspector(
    _stage6_r1_anomaly.inspect_source_anomalies
)
del _build_structured_anomaly_inspector
del _stage6_r1_anomaly
