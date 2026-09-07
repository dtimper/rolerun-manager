"""Como mucho un hilo de parcheo del anuncio en RAM a la vez, por juego.

2026-09-04: el usuario reportó que "todo el programa va lag" tras probar
SM extensamente. El log en vivo (``escrituras_vivas.jsonl``) mostraba
``sm_levelup_announcement_cache_parcheado`` disparándose varias veces por
minuto -cada cambio de rol, más el sondeo periódico- y cada invocación
puede tardar "1-2s por especie" (docstring propio de
``_sync_sm_levelup_announcement_cache``): localizar en RAM huésped +
escanear la región FCRAM real (decenas de MB) para traducir a direcciones
de Windows. Ese escaneo mantiene el GIL ocupado en ráfagas -no es una
llamada de red que lo libere-, así que varios hilos a la vez competían por
CPU y la interfaz entera se sentía lenta. Estas pruebas fijan que, sin el
candado ``_sm_levelup_announcement_cache_running``/
``_usum_levelup_announcement_cache_running``, no se lanza un segundo hilo
mientras uno ya está en curso.

2026-09-05: X/Y se sumó al mismo mecanismo (``_sync_xy_levelup_announcement_cache``,
mismo módulo compartido ``usum_levelup_announcement_cache.py``, sin
calibración de base porque X/Y usa una dirección de party constante) tras
validar en la partida real que el cartel de aprendizaje podía anunciar un
nombre viejo aunque el archivo del mod y la red de seguridad ya tuvieran
el resultado correcto. Mismo candado, mismas pruebas.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

import unittest

from app.ui import RoleRunManager


def _fake_manager(*, engine_key: str, running: bool) -> SimpleNamespace:
    fake = SimpleNamespace(
        save_engine=SimpleNamespace(key=engine_key),
        _sm_levelup_moves_vanilla_entries={1: ((1, 1, "a"),)},
        _usum_levelup_moves_vanilla_entries={1: ((1, 1, "a"),)},
        _xy_levelup_moves_vanilla_entries={1: ((1, 1, "a"),)},
        sm_live_reader=object(),
        usum_live_reader=object(),
        _sm_levelup_announcement_cache_running=running,
        _usum_levelup_announcement_cache_running=running,
        _xy_levelup_announcement_cache_running=running,
        _xy_levelup_announcement_cache_pending=None,
        _xy_levelup_announcement_cache_pending_blob=None,
        _registrar_intento_vivo=lambda *a, **k: None,
    )
    fake._sync_sm_levelup_announcement_cache = (
        RoleRunManager._sync_sm_levelup_announcement_cache.__get__(fake)
    )
    fake._sync_usum_levelup_announcement_cache = (
        RoleRunManager._sync_usum_levelup_announcement_cache.__get__(fake)
    )
    fake._sync_xy_levelup_announcement_cache = (
        RoleRunManager._sync_xy_levelup_announcement_cache.__get__(fake)
    )
    return fake


class AnnouncementCacheConcurrencyTests(unittest.TestCase):
    def test_sm_no_lanza_un_segundo_hilo_si_ya_hay_uno_en_curso(self) -> None:
        fake = _fake_manager(engine_key="sm", running=True)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch("app.ui.sm_levelup_moves_mod.parse_levelup_garc") as parse,
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_sm_levelup_announcement_cache(game, {1: "Mago"}, b"blob")
        parse.assert_not_called()
        thread_cls.assert_not_called()

    def test_usum_no_lanza_un_segundo_hilo_si_ya_hay_uno_en_curso(self) -> None:
        fake = _fake_manager(engine_key="usum", running=True)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch("app.ui.usum_levelup_moves_mod.parse_levelup_garc") as parse,
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_usum_levelup_announcement_cache(game, {1: "Mago"}, b"blob")
        parse.assert_not_called()
        thread_cls.assert_not_called()

    def test_xy_no_lanza_un_segundo_hilo_si_ya_hay_uno_en_curso(self) -> None:
        fake = _fake_manager(engine_key="xy", running=True)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch("app.ui.xy_levelup_moves_mod.parse_levelup_garc") as parse,
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_xy_levelup_announcement_cache(game, {1: "Mago"}, b"blob")
        parse.assert_not_called()
        thread_cls.assert_not_called()

    def test_xy_una_peticion_llegada_ocupado_se_encola_en_vez_de_perderse(self) -> None:
        """Bug real, 2026-09-05: un barrido de 5 especies por cambio de rol
        podía tardar 10+ segundos; el aviso urgente de un cruce de nivel
        real, llegado mientras ese barrido seguía en curso, se descartaba
        en silencio -ni error ni éxito en el log-, justo lo que le pasó a
        Zigzagoon. Ahora esa segunda petición se guarda para que el propio
        hilo la recoja en cuanto termine, en vez de perderse.
        """
        fake = _fake_manager(engine_key="xy", running=True)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch("app.ui.xy_levelup_moves_mod.parse_levelup_garc") as parse,
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_xy_levelup_announcement_cache(game, {1: "Mago"}, b"blob-viejo")
            fake._sync_xy_levelup_announcement_cache(game, {2: "Asesino"}, b"blob-nuevo")
        parse.assert_not_called()
        thread_cls.assert_not_called()
        # Las dos peticiones se fusionan -no se pisa la primera-, y se
        # queda con el blob más reciente para cuando el hilo la recoja.
        self.assertEqual(fake._xy_levelup_announcement_cache_pending, {1: "Mago", 2: "Asesino"})
        self.assertEqual(fake._xy_levelup_announcement_cache_pending_blob, b"blob-nuevo")

    def test_sm_si_lanza_el_hilo_cuando_no_hay_ninguno_en_curso_y_marca_el_candado(self) -> None:
        fake = _fake_manager(engine_key="sm", running=False)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch(
                "app.ui.sm_levelup_moves_mod.parse_levelup_garc",
                return_value={1: ((1, 1, "a"),)},
            ),
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_sm_levelup_announcement_cache(game, {1: "Mago"}, b"blob")
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs.get("daemon"), True)
        # Se marca "en curso" ANTES de lanzar el hilo -el propio hilo (aquí
        # interceptado, nunca corre de verdad) es quien lo resetearía al
        # terminar-, para que un segundo sondeo casi simultáneo no lo pise.
        self.assertTrue(fake._sm_levelup_announcement_cache_running)

    def test_xy_si_lanza_el_hilo_cuando_no_hay_ninguno_en_curso_y_marca_el_candado(self) -> None:
        fake = _fake_manager(engine_key="xy", running=False)
        game = SimpleNamespace(party=[SimpleNamespace(species_id=1)])
        with (
            patch(
                "app.ui.xy_levelup_moves_mod.parse_levelup_garc",
                return_value={1: ((1, 1, "a"),)},
            ),
            patch("app.ui.threading.Thread") as thread_cls,
        ):
            fake._sync_xy_levelup_announcement_cache(game, {1: "Mago"}, b"blob")
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs.get("daemon"), True)
        self.assertTrue(fake._xy_levelup_announcement_cache_running)


if __name__ == "__main__":
    unittest.main()
