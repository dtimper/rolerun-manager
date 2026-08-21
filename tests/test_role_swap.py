import sys
import types
from types import SimpleNamespace

# La suite de lógica puede ejecutarse también en entornos CI sin la dependencia
# gráfica. En una instalación normal se usa customtkinter real.
try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.ui import RoleRunManager


class DummyWindow:
    def __init__(self):
        self.destroyed = False

    def winfo_exists(self):
        return not self.destroyed

    def destroy(self):
        self.destroyed = True


class DummyManager:
    assign_role = RoleRunManager.assign_role

    def __init__(self, edited, holder):
        self.project = object()
        self.current_game = object()
        self.edited = edited
        self.holder = holder
        self.swap_calls = []
        self.direct_assignments = []

    def _effective_role(self, pokemon):
        return pokemon.role, ""

    def _pokemon_identity(self, pokemon):
        return pokemon.identity

    def _projected_party(self):
        return [self.edited, self.holder]

    def _move_pokemon_to_role_by_drag(self, pokemon, target_role, context="main"):
        self.swap_calls.append((pokemon.identity, target_role, context))
        old_role = pokemon.role
        target = next(p for p in self._projected_party() if p.identity != pokemon.identity and p.role == target_role)
        target.role = old_role
        pokemon.role = target_role

    def _apply_role_assignment(self, pokemon, role, window=None):
        self.direct_assignments.append((pokemon.identity, role))


def test_assigning_an_occupied_role_swaps_the_two_roles_without_unassigned_member():
    edited = SimpleNamespace(identity="A", role="Mago")
    holder = SimpleNamespace(identity="B", role="Tanque")
    manager = DummyManager(edited, holder)
    window = DummyWindow()

    manager.assign_role(edited, "Tanque", window)

    assert window.destroyed is True
    assert manager.swap_calls == [("A", "Tanque", "main")]
    assert manager.direct_assignments == []
    assert edited.role == "Tanque"
    assert holder.role == "Mago"
    assert "SIN ROL" not in {edited.role, holder.role}


def test_assigning_a_free_role_still_uses_the_normal_assignment_path():
    edited = SimpleNamespace(identity="A", role="Mago")
    holder = SimpleNamespace(identity="B", role="Tanque")
    manager = DummyManager(edited, holder)

    manager.assign_role(edited, "Support", None)

    assert manager.swap_calls == []
    assert manager.direct_assignments == [("A", "Support")]
