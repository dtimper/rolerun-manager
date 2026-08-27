"""Instrumentación de tiempos (Fase 1 de la auditoría del 27-08-2026).

Lo que estas pruebas protegen es una única promesa: **medir no puede cambiar el
comportamiento del programa**. Por eso se comprueba que apagada no envuelve
nada, que encendida devuelve los mismos valores y propaga las mismas
excepciones, que nunca revienta por un fallo de disco y que los tests que
inspeccionan el código fuente de ``ui.py`` siguen viendo la función original.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import perf  # noqa: E402


@pytest.fixture(autouse=True)
def _perf_apagada_al_terminar():
    """Recargar ``app.perf`` afecta a toda la sesión de pytest.

    Sin esta restauración, un test que enciende la medición dejaría escribiendo
    en ``Documents/RoleRun Manager/Logs`` a todos los que vinieran después.
    """
    yield
    os.environ.pop("ROLERUN_PERF", None)
    importlib.reload(perf)


def _reload_perf(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, log_dir: Path):
    """Recarga ``app.perf`` con la variable de entorno en el estado pedido."""
    monkeypatch.setenv("ROLERUN_PERF", "1" if enabled else "0")
    module = importlib.reload(perf)
    monkeypatch.setattr(module, "LOG_DIR", log_dir, raising=False)
    monkeypatch.setattr(module, "session_path", lambda: log_dir / "perf_test.jsonl")
    return module


def _read_records(module, path: Path) -> list[dict]:
    writer = module._get_writer()
    if writer is not None:
        writer.close()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# Coste cero cuando está apagada
# --------------------------------------------------------------------------

def test_apagada_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROLERUN_PERF", raising=False)
    module = importlib.reload(perf)
    assert module.ENABLED is False


def test_apagada_devuelve_la_funcion_sin_envolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=False, log_dir=tmp_path)

    def original() -> int:
        return 7

    decorada = module.timed("x")(original)
    # No es un envoltorio: es exactamente el mismo objeto función.
    assert decorada is original
    assert module.timed_aggregate("x")(original) is original


def test_apagada_no_escribe_nada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=False, log_dir=tmp_path)
    module.record("op", 12.0)
    module.mark("otra")
    with module.span("bloque"):
        pass
    module.aggregate("rapida", 1.0)
    assert list(tmp_path.glob("*.jsonl")) == []


# --------------------------------------------------------------------------
# Encendida: mide sin alterar la semántica
# --------------------------------------------------------------------------

def test_encendida_conserva_valor_de_retorno(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)

    @module.timed("suma")
    def suma(a: int, b: int, *, c: int = 0) -> int:
        return a + b + c

    assert suma(2, 3, c=4) == 9


def test_encendida_propaga_la_excepcion_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)
    path = tmp_path / "perf_test.jsonl"

    @module.timed("falla")
    def falla() -> None:
        raise ValueError("motivo original")

    with pytest.raises(ValueError, match="motivo original"):
        falla()

    registros = _read_records(module, path)
    assert [item["op"] for item in registros] == ["falla"]
    # El error se anota, pero no se traga.
    assert registros[0]["error"] == "ValueError"


def test_span_registra_campos_y_reexpone_la_excepcion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)
    path = tmp_path / "perf_test.jsonl"

    with module.span("bloque", adapter="b2w2") as medida:
        medida.add(regions=41)

    with pytest.raises(RuntimeError):
        with module.span("bloque_roto"):
            raise RuntimeError("boom")

    registros = _read_records(module, path)
    por_op = {item["op"]: item for item in registros}
    assert por_op["bloque"]["adapter"] == "b2w2"
    assert por_op["bloque"]["regions"] == 41
    assert por_op["bloque"]["ms"] >= 0.0
    assert por_op["bloque_roto"]["error"] == "RuntimeError"


def test_registro_incluye_hilo_y_marca_de_tiempo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)
    path = tmp_path / "perf_test.jsonl"
    module.record("op", 3.5, command="read")
    registros = _read_records(module, path)
    assert len(registros) == 1
    entrada = registros[0]
    # El hilo principal es el de Tk: es el que nunca debe bloquearse.
    assert entrada["thread"] == "tk"
    assert entrada["op"] == "op"
    assert entrada["ms"] == 3.5
    assert entrada["command"] == "read"
    assert entrada["t"]


# --------------------------------------------------------------------------
# Robustez: medir jamás puede tumbar una operación real
# --------------------------------------------------------------------------

def test_un_fallo_de_disco_no_rompe_la_funcion_medida(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)

    def explota(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(module, "_get_writer", explota)

    @module.timed("critica")
    def critica() -> str:
        return "resultado intacto"

    assert critica() == "resultado intacto"


def test_agregador_resume_por_ventana(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)
    path = tmp_path / "perf_test.jsonl"

    # Sesenta ticks de un bucle a 60 Hz deben producir un solo resumen, no
    # sesenta líneas: si no, la propia medición sería el cuello de botella.
    for _ in range(60):
        module.aggregate("ui.poll_gamepad", 0.4)
    module._aggregator.flush()

    registros = _read_records(module, path)
    assert len(registros) == 1
    entrada = registros[0]
    assert entrada["kind"] == "aggregate"
    assert entrada["count"] == 60
    assert entrada["avg_ms"] == pytest.approx(0.4, abs=0.01)


# --------------------------------------------------------------------------
# Compatibilidad con la suite existente
# --------------------------------------------------------------------------

def test_getsource_sigue_viendo_la_funcion_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Muchos tests afirman que cierta cadena existe en el cuerpo de un método.

    ``functools.wraps`` conserva ``__wrapped__`` e ``inspect.getsource`` lo
    desenvuelve, así que esos asertos siguen siendo válidos con la medición
    encendida. Este test lo fija para que nadie lo rompa sin enterarse.
    """
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)

    @module.timed("inspeccionable")
    def inspeccionable() -> int:
        CADENA_TESTIGO = 1
        return CADENA_TESTIGO

    assert "CADENA_TESTIGO" in inspect.getsource(inspeccionable)


def test_las_funciones_instrumentadas_conservan_su_nombre(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _reload_perf(monkeypatch, enabled=True, log_dir=tmp_path)

    @module.timed("op")
    def nombre_original(a: int) -> int:
        """Documentación intacta."""
        return a

    assert nombre_original.__name__ == "nombre_original"
    assert nombre_original.__doc__ == "Documentación intacta."


def test_puntos_de_medicion_declarados_en_el_codigo_real() -> None:
    """Los enganches de la Fase 1 deben seguir existiendo donde se acordó.

    Se busca el identificador de la operación, no la sintaxis exacta de la
    llamada: reformatear una línea no debe hacer fallar este test, pero
    borrar un punto de medición sí.
    """
    raiz = Path(__file__).resolve().parent.parent
    esperado = {
        "app/save_engine_client.py": ["engine.run"],
        "app/realtime/core.py": [
            "realtime.capture_monitor",
            "realtime.capture_full",
            "realtime.read_pc",
            "realtime.apply_changes",
        ],
        "app/obs_sync.py": ["obs.sync"],
        "app/run_service.py": ["run.append_history"],
        "app/b2w2_live.py": [
            "b2w2.region_walk",
            "b2w2.read_party",
            "b2w2.read_pc",
        ],
        "app/ui.py": [
            "ui.poll_gamepad",
            "ui.smooth_render_page",
            "ui.render_page",
            "ui.navigation_transition",
            "ui.save_pending_changes",
            "ui.save_live_changes",
            "ui.finalize_live_changes",
            "ui.reload_from_watched_save",
        ],
    }
    for relativo, operaciones in esperado.items():
        contenido = (raiz / relativo).read_text(encoding="utf-8")
        assert "perf" in contenido, f"{relativo} ya no importa la instrumentación"
        for operacion in operaciones:
            marca = f'"{operacion}"'
            assert marca in contenido, f"{relativo} perdió el punto de medición {operacion}"
