"""Lo que destruye datos del usuario sin poder recuperarlos.

Estos tres defectos salieron de la auditoría del 29-08-2026 y ninguno tenía una
sola prueba que lo cubriera.

1. **El historial se borraba entero ante un fallo de lectura pasajero.** La
   lectura capturaba `OSError` además de `JSONDecodeError` y devolvía `[]`; los
   seis escritores leían con ella y reescribían el archivo completo. Un `OSError`
   de un instante —OneDrive, el antivirus— y el siguiente evento (basta con que
   muera un Pokémon) dejaba el historial con un único evento.

2. **`config.json` se escribía truncando.** Ahí vive TODO el estado de la Run.
   Un corte dentro de esa ventana la dejaba imposible de abrir.

3. **Ctrl+Z devolvía contadores sin devolver su contrapartida.** Guardar una
   tirada cuesta un drafteo; Ctrl+Z devolvía el contador y dejaba el movimiento
   en MOVIMIENTOS. Drafteos infinitos.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.run_service import (  # noqa: E402
    HistorialIlegible,
    RunProject,
    RunProjectService,
    escribir_json_atomico,
)
from app.ui import RoleRunManager  # noqa: E402


@pytest.fixture()
def servicio(tmp_path):
    return RunProjectService(tmp_path)


@pytest.fixture()
def proyecto(servicio, tmp_path):
    partida = tmp_path / "partida.sav"
    partida.write_bytes(b"\x00" * 16)
    return servicio.open_or_create("bdsp", "Diego", partida)


# ------------------------------------------------------ el historial

def test_un_historial_ilegible_no_se_reescribe_en_silencio(servicio, proyecto) -> None:
    """Es el defecto crítico: un evento nuevo se llevaba la partida entera."""
    for numero in range(4):
        servicio.append_history(proyecto, {"type": "prueba", "n": numero})
    assert len(servicio.history(proyecto)) == 4

    historial = servicio.folder(proyecto) / "history.json"
    historial.write_text("{ esto no es una lista", encoding="utf-8")

    servicio.append_history(proyecto, {"type": "muerte", "pokemon": "Absol"})

    apartados = list(servicio.folder(proyecto).glob("history-ilegible-*.json"))
    assert len(apartados) == 1, "el archivo ilegible se ha perdido"
    assert apartados[0].read_text(encoding="utf-8") == "{ esto no es una lista"


def test_el_historial_nuevo_dice_lo_que_ha_pasado(servicio, proyecto) -> None:
    """Perder el registro es malo. Perderlo sin decirlo es peor."""
    servicio.append_history(proyecto, {"type": "prueba"})
    (servicio.folder(proyecto) / "history.json").write_text("no soy json", encoding="utf-8")

    servicio.append_history(proyecto, {"type": "muerte"})

    eventos = servicio.history(proyecto)
    assert eventos[0]["type"] == "history_unreadable"
    assert eventos[0]["backup"].startswith("history-ilegible-")
    assert eventos[-1]["type"] == "muerte"


def test_un_historial_que_no_existe_no_es_un_accidente(servicio, proyecto) -> None:
    """Una Run nueva no tiene historial, y eso no se aparta ni se denuncia."""
    (servicio.folder(proyecto) / "history.json").unlink(missing_ok=True)

    assert servicio.history(proyecto) == []
    servicio.append_history(proyecto, {"type": "primero"})

    assert not list(servicio.folder(proyecto).glob("history-ilegible-*.json"))
    assert [e["type"] for e in servicio.history(proyecto)] == ["primero"]


def test_leer_distingue_no_existe_de_no_puedo_leerlo(servicio, proyecto) -> None:
    (servicio.folder(proyecto) / "history.json").unlink(missing_ok=True)
    assert servicio._leer_historial(proyecto) == []

    (servicio.folder(proyecto) / "history.json").write_text("{}", encoding="utf-8")
    with pytest.raises(HistorialIlegible):
        servicio._leer_historial(proyecto)


def test_mostrar_el_historial_nunca_revienta_ni_escribe(servicio, proyecto) -> None:
    """`history()` la usa la interfaz para pintar: no puede tener efectos."""
    historial = servicio.folder(proyecto) / "history.json"
    historial.write_text("roto", encoding="utf-8")

    assert servicio.history(proyecto) == []
    assert historial.read_text(encoding="utf-8") == "roto", "una lectura ha escrito"
    assert not list(servicio.folder(proyecto).glob("history-ilegible-*.json"))


def test_ningun_escritor_lee_por_la_via_destructiva() -> None:
    """Los seis leen antes de reescribir el archivo entero."""
    import app.run_service as modulo

    fuente = inspect.getsource(modulo)
    cuerpo = fuente[fuente.index("class RunProjectService"):]
    assert "events = self.history(project)" not in cuerpo, (
        "un escritor volvió a leer con history(), que devuelve [] si falla"
    )
    assert cuerpo.count("self._historial_para_escribir(project)") >= 6


# --------------------------------------------------- la escritura atómica

def test_el_archivo_bueno_sobrevive_a_un_fallo_a_media_escritura(tmp_path) -> None:
    """`write_text` trunca antes de escribir; esto no."""
    destino = tmp_path / "config.json"
    destino.write_text('{"bueno": true}', encoding="utf-8")

    class NoSerializable:
        pass

    with pytest.raises(TypeError):
        escribir_json_atomico(destino, {"malo": NoSerializable()})

    assert json.loads(destino.read_text(encoding="utf-8")) == {"bueno": True}
    assert not list(tmp_path.glob("*.tmp")), "el lateral se ha quedado ahí"


def test_la_config_y_el_historial_se_escriben_sin_truncar() -> None:
    import app.run_service as modulo

    fuente = inspect.getsource(modulo)
    cuerpo = fuente[fuente.index("class RunProjectService"):]
    assert "path.write_text(json.dumps" not in cuerpo
    assert 'escribir_json_atomico(self.folder(project) / "config.json"' in cuerpo


def test_guardar_y_releer_conserva_la_run(servicio, proyecto) -> None:
    proyecto.counters["drafteos"] = 7
    proyecto.saved_drafts = [{"move_id": 53, "move": "Lanzallamas", "role": "Mago"}]
    servicio.save(proyecto)

    releido = servicio.load(proyecto.slug)
    assert releido is not None
    assert releido.counters["drafteos"] == 7
    assert releido.saved_drafts[0]["move"] == "Lanzallamas"


# ------------------------------------------------------------- Ctrl+Z

def test_el_snapshot_lleva_las_dos_mitades_de_cada_cobro() -> None:
    """Un contador sin su contrapartida es una moneda que se imprime sola."""
    fuente = inspect.getsource(RoleRunManager._capture_edit_snapshot)

    for campo in ("counters", "saved_drafts", "pending_faints", "graveyard_pokemon"):
        assert f'"{campo}"' in fuente, campo


def test_lo_capturado_es_exactamente_lo_restaurado() -> None:
    """Capturar sin restaurar deja el Ctrl+Z a medias y no avisa."""
    captura = inspect.getsource(RoleRunManager._capture_edit_snapshot)
    restaura = inspect.getsource(RoleRunManager._restore_edit_snapshot)

    claves = {
        linea.split('"')[1]
        for linea in captura.splitlines()
        if linea.strip().startswith('"') and ":" in linea
    }
    for clave in claves:
        assert f'snapshot.get("{clave}"' in restaura, f"se captura {clave} y no se restaura"


def test_deshacer_devuelve_el_drafteo_y_tambien_se_lleva_el_guardado() -> None:
    """El caso exacto del informe: drafteos infinitos.

    Se monta sobre el método real. Con el snapshot antiguo, `antes` y `despues`
    solo se distinguían en el contador: restaurar devolvía el drafteo y dejaba
    el movimiento en la lista, y la jugada se podía repetir sin límite.
    """
    from types import SimpleNamespace

    proyecto = RunProject(
        slug="x", name="X", game="bdsp", trainer="Diego",
        save_path="", created_at="", updated_at="",
    )
    proyecto.counters["drafteos"] = 3
    app = SimpleNamespace(
        project=proyecto,
        run=SimpleNamespace(pending_changes=[], role_rules_activation_pending=False),
    )

    antes = RoleRunManager._capture_edit_snapshot(app)

    # Guardar una tirada: cuesta un drafteo y deja el movimiento esperando.
    proyecto.counters["drafteos"] = 2
    proyecto.saved_drafts = [{"move_id": 53, "move": "Lanzallamas", "role": "Mago"}]
    despues = RoleRunManager._capture_edit_snapshot(app)

    assert antes["counters"]["drafteos"] == 3
    assert antes["saved_drafts"] == []
    assert despues["saved_drafts"], "el guardado no viaja en el snapshot"
    # Restaurar `antes` devuelve las DOS mitades, no solo el contador.
    assert antes != despues


def test_lo_que_hace_el_juego_no_entra_en_la_pila_de_deshacer() -> None:
    fuente = inspect.getsource(RoleRunManager._asumir_estado_del_juego)
    assert "self._edit_last_snapshot = self._capture_edit_snapshot()" in fuente
    assert "_edit_undo_stack" not in fuente, "no puede vaciar los pasos legítimos"

    muerte = inspect.getsource(RoleRunManager._publish_registered_faint)
    assert "self._asumir_estado_del_juego()" in muerte

    contador = inspect.getsource(RoleRunManager.adjust_run_counter)
    assert "self._asumir_estado_del_juego()" in contador
    assert "if self._counter_is_automatic(counter):" in contador
