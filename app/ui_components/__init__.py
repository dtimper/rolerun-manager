"""Componentes visuales reutilizables de la interfaz evolucionada."""

from .integrated_window import IntegratedWindowSurface
from .loading_indicator import CenteredLoadingIndicator
from .operation_bar import OperationStatusBar
from .role_info_popover import IntegratedRoleInfoPopover
from .role_icons import RoleIconProvider
from .transparent_window import TransparentWindowSurface
from .repintado import configurar_si_cambia

__all__ = [
    "IntegratedRoleInfoPopover",
    "IntegratedWindowSurface",
    "TransparentWindowSurface",
    "CenteredLoadingIndicator",
    "OperationStatusBar",
    "RoleIconProvider",
    "configurar_si_cambia",
]
