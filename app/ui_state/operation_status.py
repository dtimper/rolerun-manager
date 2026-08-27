from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Literal


OperationKind = Literal[
    "neutral",
    "prepared",
    "applying",
    "verifying",
    "confirmed",
    "failed",
    "restored",
    "warning",
    "intervention",
    "disconnected",
    "pending",
]


PERSISTENT_KINDS = frozenset({"failed", "intervention", "disconnected"})
AUTO_COLLAPSE_KINDS = frozenset({"confirmed", "restored"})


@dataclass(frozen=True, slots=True)
class OperationMessage:
    """Mensaje semántico de la barra inferior.

    El modelo es deliberadamente independiente de CustomTkinter. Las acciones
    son identificadores de presentación; la UI decide qué callback corresponde
    a cada uno. Un error nunca desaparece por tiempo por defecto.
    """

    kind: OperationKind = "neutral"
    title: str = "ROLERUN PREPARADO"
    detail: str = "Selecciona una acción para continuar."
    actions: tuple[str, ...] = ()
    persistent: bool | None = None
    revision: int = 0

    @property
    def stays_visible(self) -> bool:
        if self.persistent is not None:
            return bool(self.persistent)
        return self.kind in PERSISTENT_KINDS

    @property
    def may_auto_collapse(self) -> bool:
        return not self.stays_visible and self.kind in AUTO_COLLAPSE_KINDS


class OperationStatusStore:
    """Fuente única y comprobable para el mensaje operativo de la shell."""

    def __init__(self, initial: OperationMessage | None = None) -> None:
        self._message = initial or OperationMessage()
        self._listeners: list[Callable[[OperationMessage], None]] = []

    @property
    def message(self) -> OperationMessage:
        return self._message

    def subscribe(self, callback: Callable[[OperationMessage], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)
        callback(self._message)

    def publish(
        self,
        kind: OperationKind,
        title: str,
        detail: str,
        *,
        actions: tuple[str, ...] = (),
        persistent: bool | None = None,
    ) -> OperationMessage:
        self._message = OperationMessage(
            kind=kind,
            title=str(title).strip() or "ROLERUN",
            detail=str(detail).strip(),
            actions=tuple(actions),
            persistent=persistent,
            revision=self._message.revision + 1,
        )
        for listener in tuple(self._listeners):
            listener(self._message)
        return self._message

    def collapse_if_current(self, revision: int) -> bool:
        if self._message.revision != int(revision) or not self._message.may_auto_collapse:
            return False
        self._message = replace(
            self._message,
            kind="neutral",
            title="ROLERUN PREPARADO",
            detail="El último cambio quedó confirmado.",
            actions=(),
            persistent=False,
            revision=self._message.revision + 1,
        )
        for listener in tuple(self._listeners):
            listener(self._message)
        return True
