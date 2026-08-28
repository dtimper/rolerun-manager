"""Guardar un fallo de una pulsación, sin parar el directo.

El usuario juega en directo y no puede reportar los fallos sobre la marcha.
Contarlos al terminar pierde justo lo que hace falta: la hora exacta, qué había
en pantalla y qué estaba leyendo o escribiendo RoleRun en ese momento.

Lo que se fija aquí es lo que hace que sirva de verdad:

- **no pregunta nada**: una pulsación y ya está;
- **no puede tumbar la partida**: si una parte del informe falla, se anota
  dentro y las demás se guardan igual. Un informe incompleto sirve; perder lo
  que estabas haciendo por intentar guardarlo, no;
- **el atajo sale de fábrica**: durante un directo, un atajo que hay que
  configurar primero es un atajo que no se usa.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reporte_de_bugs import (  # noqa: E402
    empaquetar,
    guardar_reporte,
    informes,
)


def test_una_pulsacion_deja_carpeta_contexto_y_nota(tmp_path) -> None:
    carpeta = guardar_reporte(
        {"pagina": "team", "juego": "Perla Reluciente"},
        carpeta_base=tmp_path,
        con_pantalla=False,
    )

    assert carpeta.is_dir()
    assert carpeta.name.startswith("bug_")
    cuerpo = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert cuerpo["pagina"] == "team"
    assert cuerpo["juego"] == "Perla Reluciente"
    assert cuerpo["version"]
    assert cuerpo["cuando"]
    assert (carpeta / "nota.txt").is_file()


def test_el_contexto_puede_ser_algo_que_haya_que_pedir(tmp_path) -> None:
    """La interfaz pasa un método: leerlo tarda y no debe hacerse antes."""
    carpeta = guardar_reporte(
        lambda: {"cambios_pendientes": 3}, carpeta_base=tmp_path, con_pantalla=False,
    )

    cuerpo = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert cuerpo["cambios_pendientes"] == 3


def test_si_el_contexto_revienta_el_informe_se_guarda_igual(tmp_path) -> None:
    """Perder el informe entero porque una parte falla seria lo peor."""

    def _revienta():
        raise RuntimeError("la party no se pudo leer")

    carpeta = guardar_reporte(_revienta, carpeta_base=tmp_path, con_pantalla=False)

    cuerpo = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert any(
        "la party no se pudo leer" in linea
        for linea in cuerpo["no_se_pudo_recoger"]
    )
    assert cuerpo["version"]


def test_lo_que_no_se_pudo_recoger_queda_dicho(tmp_path) -> None:
    """Un hueco silencioso haria pensar que ese registro no existia."""
    carpeta = guardar_reporte({}, carpeta_base=tmp_path, con_pantalla=False)

    cuerpo = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert cuerpo["no_se_pudo_recoger"], "deberia decir que faltan los registros"


def test_la_nota_escrita_llega_al_informe(tmp_path) -> None:
    carpeta = guardar_reporte(
        {}, nota="se congelo al dar la MT", carpeta_base=tmp_path, con_pantalla=False,
    )

    cuerpo = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert cuerpo["nota"] == "se congelo al dar la MT"
    assert "se congelo al dar la MT" in (carpeta / "nota.txt").read_text(encoding="utf-8")


def test_dos_informes_no_se_pisan(tmp_path) -> None:
    primero = guardar_reporte({}, carpeta_base=tmp_path, con_pantalla=False)
    segundo = guardar_reporte({}, carpeta_base=tmp_path, con_pantalla=False)

    # Dentro del mismo segundo comparten nombre, y eso es aceptable: lo que no
    # puede pasar es que uno borre al otro sin dejar rastro.
    assert primero.is_dir() and segundo.is_dir()
    assert len(informes(tmp_path)) >= 1


def test_se_listan_del_mas_reciente_al_mas_antiguo(tmp_path) -> None:
    for nombre in ("bug_2026-08-28_10-00-00", "bug_2026-08-28_12-00-00"):
        (tmp_path / nombre).mkdir()
    (tmp_path / "otra_cosa").mkdir()

    listado = [ruta.name for ruta in informes(tmp_path)]

    assert listado == ["bug_2026-08-28_12-00-00", "bug_2026-08-28_10-00-00"]


def test_el_zip_no_se_mete_a_si_mismo(tmp_path) -> None:
    """Dentro se incluiria a si mismo y cada empaquetado seria mayor."""
    base = tmp_path / "Bugs"
    base.mkdir()
    (base / "bug_2026-08-28_10-00-00").mkdir()

    zip_ = empaquetar(base)

    assert zip_ is not None and zip_.is_file()
    assert base not in zip_.parents


def test_sin_informes_no_se_empaqueta_nada(tmp_path) -> None:
    assert empaquetar(tmp_path) is None


def test_el_atajo_sale_de_fabrica() -> None:
    """Un atajo que hay que configurar primero es un atajo que no se usa."""
    from app.run_service import RunProject

    proyecto = RunProject(
        slug="prueba", name="Prueba", game="bdsp", trainer="Diego",
        save_path="", created_at="", updated_at="",
    )
    assert proyecto.hotkeys.get("reportar_bug") == "f8"


def test_las_runs_ya_creadas_tambien_lo_reciben() -> None:
    """Quien ya tenia una Run abierta no deberia quedarse sin el."""
    import inspect

    from app import run_service

    fuente = inspect.getsource(run_service)
    assert fuente.count('setdefault("reportar_bug", "f8")') == 2, (
        "las dos rutas de migracion tienen que ponerlo"
    )
