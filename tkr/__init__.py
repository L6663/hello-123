"""Text Knowledge Reader staged hardening package."""

__version__ = "5.9.0-alpha1"

# Stage 6-R1 applies three narrow correctness fixes before any public submodule
# is imported.  The remediation is deterministic and grants no acceptance,
# release-candidate, certification, or freeze authority.
from .stage6_r1_remediation import apply_stage6_r1_remediation as _apply_stage6_r1_remediation

_apply_stage6_r1_remediation()
del _apply_stage6_r1_remediation
