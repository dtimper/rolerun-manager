import sys
import types
from types import SimpleNamespace

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.models import PendingTMTeach
from app.ui import RoleRunManager


class FakeTM:
    def __init__(self, item_id, move_id):
        self.item_id = item_id
        self.move_id = move_id


class FakeProfile:
    def __init__(self):
        self.mapping = {
            1: FakeTM(101, 10),  # válida
            2: FakeTM(102, 20),  # ya conocida
            3: FakeTM(103, 30),  # incompatible con el rol
            4: FakeTM(104, 40),  # la ROM dice no aprendible: RoleRun debe ignorarlo
            5: FakeTM(105, 50),  # no está en mochila
        }
        self.tms = dict(self.mapping)

    def tm(self, number):
        return self.mapping.get(number)

    def can_learn(self, species_id, form, number):
        return number != 4


class CandidateManager:
    _build_tm_candidates = RoleRunManager._build_tm_candidates

    def __init__(self):
        self.engine = SimpleNamespace(
            allowed_move_ids={10, 20, 30, 40, 50},
            move=lambda move_id: {"name_es": f"Movimiento {move_id}"},
        )

    def _effective_moves_for_review(self, pokemon):
        return ["Viejo", "Conocido", "—", "—"], [1, 20, 0, 0]

    def _effective_role(self, pokemon):
        return "Mago", "♥"

    def _tm_move_compatible_with_role(self, pokemon, role, move_id, move_slot):
        return move_id != 30

    def _damage_class_for_move(self, move_id):
        return "special"

    def _draft_move_metadata(self, move_id):
        return {"type_id": 12, "description": f"Descripción de {move_id}."}


class QueueManager:
    _queue_tm_teach = RoleRunManager._queue_tm_teach

    def __init__(self):
        self.run = SimpleNamespace(pending_changes=[])
        self.save_engine = SimpleNamespace(key="bdsp")
        self._oras_live_active = False
        self.toasts = 0

    def _effective_moves_for_review(self, pokemon):
        return ["Ataque incompatible", "Segundo", "—", "—"], [123, 456, 0, 0]

    def _pokemon_identity(self, pokemon):
        return "pk-test"

    def _effective_role(self, pokemon):
        return "Mago", "♥"

    def _capture_body_scroll_px(self):
        return 0

    def _capture_body_scroll_fraction(self):
        return 0.0

    def _update_top_status(self):
        pass

    def _smooth_render_page(self, preserve_scroll=False):
        pass

    def after(self, _delay, callback):
        callback()

    def _show_change_toast(self):
        self.toasts += 1

    def _request_oras_live_auto_apply_since(self, _pending_ids_before):
        pass


class InventoryProjectionManager:
    _pending_adjusted_tm_inventory = RoleRunManager._pending_adjusted_tm_inventory

    def __init__(self, pending_changes):
        self.run = SimpleNamespace(pending_changes=list(pending_changes))


def test_tm_candidates_ignore_species_compatibility_but_keep_role_inventory_game_and_duplicates():
    manager = CandidateManager()
    pokemon = SimpleNamespace(species_id=25, form=0)
    inventory = {101: 1, 102: 1, 103: 1, 104: 1, 105: 0}

    candidates = manager._build_tm_candidates(pokemon, 1, FakeProfile(), inventory)

    assert [candidate["move_id"] for candidate in candidates] == [10, 40]
    assert [candidate["item_id"] for candidate in candidates] == [101, 104]


def test_tm_teach_can_replace_an_occupied_incompatible_slot():
    manager = QueueManager()
    pokemon = SimpleNamespace(slot=1, nickname="Prueba", species="Gardevoir")
    candidate = {
        "move_name": "Psíquico",
        "move_id": 94,
        "item_id": 201,
        "number": 29,
        "quantity": 1,
        "consumes_item": True,
    }

    manager._queue_tm_teach(pokemon, 1, candidate)

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert isinstance(change, PendingTMTeach)
    assert change.move_slot == 1
    assert change.old_move == "Ataque incompatible"
    assert change.old_move_id == 123
    assert change.new_move == "Psíquico"
    assert change.new_move_id == 94
    assert change.consumes_item is True
    assert manager.toasts == 1


def test_oras_tm_queue_does_not_require_inventory_witnesses():
    manager = QueueManager()
    manager.save_engine = SimpleNamespace(key="oras")
    manager._oras_live_active = True
    manager._oras_inventory_witnesses = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no debe consultar mochila"))
    pokemon = SimpleNamespace(slot=1, nickname="Prueba", species="Gardevoir")
    candidate = {
        "move_name": "Psíquico",
        "move_id": 94,
        "item_id": 201,
        "number": 29,
        "quantity": 1,
    }

    manager._queue_tm_teach(pokemon, 1, candidate)

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert isinstance(change, PendingTMTeach)
    assert change.inventory_witnesses == ()
    assert change.consumes_item is False


def test_pending_tm_inventory_only_reserves_consumable_bdsp_items():
    reusable = PendingTMTeach(
        role="Líbero", pokemon_slot=1, pokemon="Uno", species="Mawile",
        move_slot=1, old_move="Viejo", old_move_id=1,
        new_move="Nuevo", new_move_id=2, pokemon_identity="one",
        item_id=101, tm_number=1, item_name="MT01", quantity_before=1,
        consumes_item=False,
    )
    consumable = PendingTMTeach(
        role="Mago", pokemon_slot=2, pokemon="Dos", species="Abra",
        move_slot=1, old_move="Viejo", old_move_id=1,
        new_move="Nuevo", new_move_id=2, pokemon_identity="two",
        item_id=202, tm_number=2, item_name="MT02", quantity_before=2,
        consumes_item=True,
    )
    manager = InventoryProjectionManager([reusable, consumable])

    projected = manager._pending_adjusted_tm_inventory({101: 1, 202: 2})

    assert projected == {101: 1, 202: 1}
