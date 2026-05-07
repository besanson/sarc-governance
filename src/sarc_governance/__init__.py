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
from sarc_governance.context import ExecutionContext
from sarc_governance.escalation import EscalationHandler, EscalationRouter
from sarc_governance.governance import ConstraintViolation, GovernanceToolset, MemoryProtocol, ToolsetProtocol
from sarc_governance.trace import ActionEvent, TraceRecord, new_action_id
from sarc_governance.audit import audit_trace
from sarc_governance.specs import load_spec, load_spec_from_string, safe_load_spec
from sarc_governance import predicates
from sarc_governance.policy import (
    PolicyBundle,
    PolicyMetadata,
    diff_policies,
    inspect_policy,
    policy_checksum,
)
from sarc_governance.hashchain import (
    ChainBreak,
    ChainError,
    append_record,
    canonical_event_hash,
    chain_records,
    verify_chain,
)
from sarc_governance.handlers import WebhookEscalationHandler
from sarc_governance.stores import (
    JSONLTraceStore,
    MemoryTraceStore,
    SQLiteTraceStore,
    TraceStore,
)

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
    # execution context
    "ExecutionContext",
    # governance
    "ConstraintViolation",
    "GovernanceToolset",
    "MemoryProtocol",
    "ToolsetProtocol",
    # escalation
    "EscalationHandler",
    "EscalationRouter",
    "WebhookEscalationHandler",
    # trace
    "ActionEvent",
    "TraceRecord",
    "new_action_id",
    # audit
    "audit_trace",
    # spec loading
    "load_spec",
    "load_spec_from_string",
    "safe_load_spec",
    # predicate registry module
    "predicates",
    # policy lifecycle
    "PolicyBundle",
    "PolicyMetadata",
    "diff_policies",
    "inspect_policy",
    "policy_checksum",
    # hash chain
    "ChainBreak",
    "ChainError",
    "append_record",
    "canonical_event_hash",
    "chain_records",
    "verify_chain",
    # trace stores
    "JSONLTraceStore",
    "MemoryTraceStore",
    "SQLiteTraceStore",
    "TraceStore",
    # version
    "__version__",
]
