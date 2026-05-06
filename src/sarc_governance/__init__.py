"""sarc_governance — SARC runtime governance layer for tool-using agentic systems.

Public API summary
------------------
Constraints::

    from sarc_governance import (
        Constraint, ConstraintClass, ConstraintSpec,
        EnforcementPoint, Response,
    )

Governance toolset wrapper::

    from sarc_governance import GovernanceToolset, ConstraintViolation

Escalation::

    from sarc_governance import EscalationRouter, EscalationHandler

Trace records::

    from sarc_governance import TraceRecord, ActionEvent

Audit::

    from sarc_governance import audit_trace

Spec loading::

    from sarc_governance import load_spec, load_spec_from_string

Predicate registry::

    from sarc_governance import predicates          # module
    from sarc_governance.predicates import register
"""

from sarc_governance.constraints import (
    Constraint,
    ConstraintClass,
    ConstraintSpec,
    EnforcementPoint,
    PredicateProtocol,
    Response,
    allowed_points,
    is_compatible,
)
from sarc_governance.escalation import EscalationHandler, EscalationRouter
from sarc_governance.governance import ConstraintViolation, GovernanceToolset, MemoryProtocol, ToolsetProtocol
from sarc_governance.trace import ActionEvent, TraceRecord, new_action_id
from sarc_governance.audit import audit_trace
from sarc_governance.specs import load_spec, load_spec_from_string
from sarc_governance import predicates

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
