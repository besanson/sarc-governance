"""sarc_kaos — SARC runtime governance layer for tool-using agentic systems.

Public API summary
------------------
Constraints::

    from sarc_kaos import (
        Constraint, ConstraintClass, ConstraintSpec,
        EnforcementPoint, Response,
    )

Governance toolset wrapper::

    from sarc_kaos import GovernanceToolset, ConstraintViolation

Escalation::

    from sarc_kaos import EscalationRouter, EscalationHandler

Trace records::

    from sarc_kaos import TraceRecord, ActionEvent

Audit::

    from sarc_kaos import audit_trace

Spec loading::

    from sarc_kaos import load_spec, load_spec_from_string

Predicate registry::

    from sarc_kaos import predicates          # module
    from sarc_kaos.predicates import register
"""

from sarc_kaos.constraints import (
    Constraint,
    ConstraintClass,
    ConstraintSpec,
    EnforcementPoint,
    PredicateProtocol,
    Response,
    allowed_points,
    is_compatible,
)
from sarc_kaos.escalation import EscalationHandler, EscalationRouter
from sarc_kaos.governance import ConstraintViolation, GovernanceToolset, MemoryProtocol, ToolsetProtocol
from sarc_kaos.trace import ActionEvent, TraceRecord, new_action_id
from sarc_kaos.audit import audit_trace
from sarc_kaos.specs import load_spec, load_spec_from_string
from sarc_kaos import predicates

__version__ = "0.1.0"

__all__ = [
    # constraints
    "Constraint",
    "ConstraintClass",
    "ConstraintSpec",
    "EnforcementPoint",
    "PredicateProtocol",
    "Response",
    "allowed_points",
    "is_compatible",
    # governance
    "ConstraintViolation",
    "GovernanceToolset",
    "MemoryProtocol",
    "ToolsetProtocol",
    # escalation
    "EscalationHandler",
    "EscalationRouter",
    # trace
    "ActionEvent",
    "TraceRecord",
    "new_action_id",
    # audit
    "audit_trace",
    # spec loading
    "load_spec",
    "load_spec_from_string",
    # predicate registry module
    "predicates",
    # version
    "__version__",
]
