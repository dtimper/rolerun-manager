"""Estado de presentación compartido por las vistas de RoleRun Manager.

Este paquete no contiene reglas de juego, acceso a memoria ni decisiones de
persistencia.  Solo describe qué debe comunicar la interfaz.
"""

from .operation_status import OperationMessage, OperationStatusStore
from .path_actions import ExplorerTarget, resolve_explorer_target
from .navigation import DEFAULT_PAGE, PRIMARY_NAVIGATION, normalize_navigation_target, primary_page_for
from .team_pc_state import (
    CANONICAL_ROLE_ORDER,
    TMTeachFlowState,
    TeamPCDropIntent,
    TeamPCSelectionState,
    build_fixed_team_slots,
    resolve_team_pc_drop,
)

__all__ = [
    "DEFAULT_PAGE",
    "PRIMARY_NAVIGATION",
    "OperationMessage",
    "OperationStatusStore",
    "ExplorerTarget",
    "resolve_explorer_target",
    "CANONICAL_ROLE_ORDER",
    "TMTeachFlowState",
    "TeamPCDropIntent",
    "TeamPCSelectionState",
    "build_fixed_team_slots",
    "resolve_team_pc_drop",
    "normalize_navigation_target",
    "primary_page_for",
]
