"""La guía del formato (IntegratedFormatHelpView) se reescribió el
09-09-2026 con las reglas reales de RoleRun, dictadas por el usuario -ver
memoria `project_rolerun_format_rules.md`-. Estos tests fijan los números
concretos en el texto de verdad, para que no se puedan desviar sin darse
cuenta en un refactor futuro.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ui_views.format_help_view import IntegratedFormatHelpView


def _all_texts(widget) -> list[str]:
    texts = []
    try:
        texts.append(str(widget.cget("text")))
    except Exception:
        pass
    for child in widget.winfo_children():
        texts.extend(_all_texts(child))
    return texts


@pytest.fixture
def view():
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1200x900")
        root.update_idletasks()
        body = ctk.CTkFrame(root)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        role_guide = {
            role: {"summary": "resumen", "allowed": "permitido", "limits": "límites"}
            for role in ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support")
        }
        instance = IntegratedFormatHelpView(
            body,
            logo_path=Path("no-existe.png"),
            role_order=tuple(role_guide),
            role_guide=role_guide,
            global_role_note="nota global",
            role_symbols={role: "*" for role in role_guide},
            on_back=lambda: None,
            on_open_team=lambda: None,
            on_open_moves=lambda: None,
        )
        root.update_idletasks()
        yield instance
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_the_lives_rule_states_the_real_numbers(view) -> None:
    texts = " ".join(_all_texts(view.frame))
    assert "Empiezas con 10 vidas" in texts
    assert "sumas una vida" in texts
    # Corregido por el usuario el 2026-09-26: la vida se pierde en cualquier
    # combate; solo ganarla depende del combate de seis Pokémon.
    assert "en cualquier combate, te resta una vida" in texts
    assert "Solo se gana vida en un combate de seis Pokémon" in texts
    assert "no cualquier combate suelto" not in texts


def test_drafts_and_potions_are_tied_to_the_right_battles(view) -> None:
    texts = " ".join(_all_texts(view.frame))
    assert "también te da un drafteo" in texts
    assert "líder de gimnasio, ganas una curación" in texts


def test_dualrole_scoring_is_explained_and_not_claimed_as_tracked_by_the_app(view) -> None:
    texts = " ".join(_all_texts(view.frame))
    assert "mejor de tres" in texts
    assert "3ª medalla" in texts and "6ª medalla" in texts
    assert "pierdes el DualRole" in texts
    # No debe insinuar que el programa lleva la cuenta de puntos por el usuario.
    assert "no lleva la cuenta de estos puntos" in texts
