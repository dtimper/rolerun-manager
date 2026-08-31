from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PendingDraft:
    role: str
    category: str
    pool_key: str
    move_id: int
    move: str
    # Un drafteo recuperado de los guardados ya se pagó al guardarlo. Sin esto,
    # enseñarlo más tarde cobraría el mismo drafteo dos veces.
    ya_pagado: bool = False


@dataclass(slots=True)
class PendingChange:
    role: str
    pokemon_slot: int
    pokemon: str
    species: str
    move_slot: int
    old_move: str
    old_move_id: int
    new_move: str
    new_move_id: int
    # Identidad estable opcional. Permite editar movimientos de un Pokémon que
    # acaba de entrar desde el PC antes de haber escrito la reorganización al save.
    pokemon_identity: str = ""


@dataclass(slots=True)
class PendingTMTeach:
    """MT que se enseñará al guardar o en la RAM del juego.

    En los flujos que consumen MT (p. ej. BDSP) se mantiene separada de
    ``PendingChange`` para que movimiento y mochila sean atómicos. ORAS usa MT
    reutilizables: el selector comprueba que la máquina esté disponible, pero
    la escritura viva solo modifica el PK6 y no depende de calibrar la mochila.
    """

    role: str
    pokemon_slot: int
    pokemon: str
    species: str
    move_slot: int
    old_move: str
    old_move_id: int
    new_move: str
    new_move_id: int
    pokemon_identity: str
    item_id: int
    tm_number: int
    item_name: str
    quantity_before: int
    # Huella histórica para compatibilidad con Runs antiguas/otros flujos.
    # Desde alpha.36 ORAS no la necesita para enseñar una MT reutilizable.
    inventory_witnesses: tuple[tuple[str, int, int, int], ...] = ()
    # Solo BDSP consume la máquina. En Gen 6/7 las MT son reutilizables y
    # deben permanecer disponibles tanto en la mochila real como en cualquier
    # proyección de UI mientras el cambio está pendiente o tras su readback.
    consumes_item: bool = False


@dataclass(slots=True)
class PendingRoleChange:
    pokemon_slot: int
    pokemon: str
    species: str
    old_role: str
    new_role: str
    # Identidad estable del Pokémon. Desde 1.12.5 los cambios de rol pueden
    # convivir con una reorganización Equipo ↔ PC y ya no dependen de que el
    # Pokémon siga ocupando el mismo slot al guardar.
    pokemon_identity: str = ""
    # BDSP puede aplicar rol+EV como una única transacción PB8. Vacío mantiene
    # compatibilidad con Runs y backends anteriores.
    old_evs: tuple[int, int, int, int, int, int] | None = None
    new_evs: tuple[int, int, int, int, int, int] | None = None


@dataclass(slots=True)
class PendingPartyHeal:
    """Curación completa de un miembro de la party viva.

    La identidad estable permite que el writer rechace cualquier reordenación
    ocurrida entre el clic y la doble lectura de precondición.
    """

    pokemon_slot: int
    pokemon: str
    species: str
    pokemon_identity: str


@dataclass(slots=True)
class PendingInventoryChange:
    item_key: str
    item_name: str
    quantity: int
    # ``(bolsillo, posición, id de objeto, cantidad)`` del último guardado.
    # Una posición negativa representa que ese objeto no estaba presente y
    # ayuda a no confundir una copia vieja de la mochila con la activa.
    inventory_witnesses: tuple[tuple[str, int, int, int], ...] = ()
    # X/Y: copia del bloque Misc del último guardado. Solo se usa como huella
    # estructural para localizar la copia viva antes de escribir el dinero;
    # Money/Badges/BP se excluyen de la huella, así que pueden haber cambiado.
    # Sol/Luna reutiliza este campo como bloque Misc ORIGINAL exacto (0x200)
    # únicamente para calibrar el backing FCRAM antes de tocar Money.
    save_misc_witness: bytes = b""
    # Sol/Luna: bloques exactos original/modificado generados por PKHeX a partir
    # del mismo ``main``. El escritor vivo no interpreta el formato para inventar
    # inserciones: exige que el diff esté confinado al registro/campo documentado
    # y usa estos bytes como prueba antes de escribir RAM.
    save_inventory_witness: bytes = b""
    desired_inventory_witness: bytes = b""
    desired_misc_witness: bytes = b""


@dataclass(slots=True)
class PendingPCRoleChange:
    box: int
    box_slot: int
    pokemon: str
    species: str
    pokemon_identity: str
    old_role: str
    new_role: str
    # Dos o más identidades del mismo PC permiten localizar con seguridad la
    # matriz viva cuando una ROM modifica el layout de memoria de ORAS.
    box_witnesses: tuple[tuple[int, str], ...] = ()


@dataclass(slots=True)
class PendingTeamChange:
    operation: str  # party-to-box | box-to-party | swap-party-box | replace-fainted | move-box-slot
    party_slot: int
    box: int | None = None
    box_slot: int | None = None
    outgoing_pokemon: str = ""
    outgoing_species: str = ""
    incoming_pokemon: str = ""
    incoming_species: str = ""
    incoming_role: str = ""
    remove_move_slots: list[int] = field(default_factory=list)
    incoming_snapshot: dict[str, object] = field(default_factory=dict)
    outgoing_snapshot: dict[str, object] = field(default_factory=dict)
    # Identidades estables y testigos de caja para comprobar que la party y el
    # PC vivos siguen conteniendo exactamente los dos Pokémon que se eligieron.
    # Sin estas huellas un cambio de caja dentro del propio juego podría hacer
    # que una sustitución pendiente escribiese sobre otra criatura.
    incoming_identity: str = ""
    outgoing_identity: str = ""
    box_witnesses: tuple[tuple[int, str], ...] = ()
    # Testigos de CUALQUIER caja: ``(caja, hueco, identidad)``. La matriz de
    # cajas es una sola tabla contigua, así que un Pokémon real de otra caja
    # demuestra su dirección base exactamente igual que un vecino de la misma
    # caja. Es lo único que permite soltar en una caja vacía, donde
    # ``box_witnesses`` no puede aportar nada y un hueco vacío nunca vale como
    # ancla.
    pc_anchor_witnesses: tuple[tuple[int, int, str], ...] = ()
    # Operación especial de baja: el sustituto sale de ``box/box_slot`` y el
    # Pokémon debilitado se deposita en esta posición de la caja de Cementerio.
    graveyard_box: int | None = None
    graveyard_box_slot: int | None = None
    # PC→PC conserva ``box/box_slot`` como origen y declara el destino exacto
    # por separado. Nunca se interpreta como un traslado de party.
    destination_box: int | None = None
    destination_box_slot: int | None = None
    # B2/W2 compacta físicamente la party al depositar, pero RoleRun ordena la
    # interfaz por roles. El mapa se captura antes del write y conserva cada rol
    # por identidad después del cambio de índice físico.
    party_role_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RunSession:
    """Estado central de una sesión de RoleRun."""

    save_path: Path | None = None
    game: str = ""
    trainer: str = ""
    role: str | None = None
    draft: PendingDraft | None = None
    pokemon_slot: int | None = None
    move_slot: int | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    pending_changes: list[PendingChange | PendingTMTeach | PendingRoleChange | PendingPartyHeal | PendingInventoryChange | PendingPCRoleChange | PendingTeamChange] = field(default_factory=list)
    role_rules_activation_pending: bool = False

    def reset_after_save_change(self) -> None:
        self.role = None
        self.draft = None
        self.pokemon_slot = None
        self.move_slot = None
        self.role_rules_activation_pending = False

    def reset_after_role_change(self) -> None:
        self.draft = None
        self.pokemon_slot = None
        self.move_slot = None

    def reset_after_draft_change(self) -> None:
        self.pokemon_slot = None
        self.move_slot = None
