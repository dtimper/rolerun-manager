"""``project_stats``/``project_current_hp`` — vista previa de un cambio de rol.

2026-09-04: el usuario grabó un vídeo mostrando que, tras arrastrar un
Pokémon a otra casilla de rol, el ROL/icono cambia al instante pero las
STATS numéricas se quedan con los valores viejos ~2s más, hasta que la
escritura en vivo confirma contra el propio juego (ver
``app/ui.py::_projected_party``). Estas pruebas fijan la fórmula de
proyección (idéntica a la que ya usa cada escritor en vivo para verificar
bytes, p. ej. ``sm_live.py::_calculate_party_stats``) contra el caso real
del vídeo: Yungoos, base 48/70/30/30/30/45, nivel 40, naturaleza Rara
(neutral), pasado a Tanque (EV 252 PS + 252 Defensa) — el juego confirmó
125/73/60/36/38/45.
"""

from __future__ import annotations

import unittest

from app.pokemon_stats import project_current_hp, project_stats

YUNGOOS_BASE = {"hp": 48, "attack": 70, "defense": 30, "sp_attack": 30, "sp_defense": 30, "speed": 45}
YUNGOOS_IVS = {"hp": 30, "attack": 30, "defense": 15, "sp_attack": 19, "sp_defense": 24, "speed": 11}
TANQUE_EVS = {"hp": 252, "attack": 0, "defense": 252, "sp_attack": 0, "sp_defense": 0, "speed": 0}
RARA_NATURE_ID = 24  # neutral, PKHeX.Core GameInfo.Strings.natures


class ProjectStatsTests(unittest.TestCase):
    def test_reproduce_el_yungoos_tanque_confirmado_por_el_juego_en_el_video(self) -> None:
        stats = project_stats(YUNGOOS_BASE, YUNGOOS_IVS, TANQUE_EVS, 40, RARA_NATURE_ID)
        self.assertEqual(
            stats,
            {"hp": 125, "attack": 73, "defense": 60, "sp_attack": 36, "sp_defense": 38, "speed": 45},
        )

    def test_naturaleza_sube_y_baja_la_stat_correcta(self) -> None:
        # Audaz (id 2, Brave en PKHeX.Core): sube Ataque, baja Velocidad.
        neutral = project_stats(YUNGOOS_BASE, YUNGOOS_IVS, {}, 40, RARA_NATURE_ID)
        audaz = project_stats(YUNGOOS_BASE, YUNGOOS_IVS, {}, 40, 2)
        self.assertGreater(audaz["attack"], neutral["attack"])
        self.assertLess(audaz["speed"], neutral["speed"])
        self.assertEqual(audaz["hp"], neutral["hp"])  # la naturaleza nunca toca PS

    def test_base_1_es_el_caso_especial_shedinja(self) -> None:
        base = dict(YUNGOOS_BASE, hp=1)
        stats = project_stats(base, YUNGOOS_IVS, TANQUE_EVS, 40, RARA_NATURE_ID)
        self.assertEqual(stats["hp"], 1)

    def test_sin_base_stats_no_proyecta_nada(self) -> None:
        self.assertEqual(project_stats({}, YUNGOOS_IVS, TANQUE_EVS, 40, RARA_NATURE_ID), {})
        self.assertEqual(project_stats(None, YUNGOOS_IVS, TANQUE_EVS, 40, RARA_NATURE_ID), {})

    def test_sin_ivs_no_proyecta_nada(self) -> None:
        self.assertEqual(project_stats(YUNGOOS_BASE, {}, TANQUE_EVS, 40, RARA_NATURE_ID), {})

    def test_falta_una_sola_clave_no_proyecta_nada(self) -> None:
        """Ni siquiera parcialmente: mejor conservar lo que ya había."""
        ivs_incompletos = dict(YUNGOOS_IVS)
        del ivs_incompletos["speed"]
        self.assertEqual(project_stats(YUNGOOS_BASE, ivs_incompletos, TANQUE_EVS, 40, RARA_NATURE_ID), {})

    def test_nivel_fuera_de_rango_no_proyecta_nada(self) -> None:
        self.assertEqual(project_stats(YUNGOOS_BASE, YUNGOOS_IVS, TANQUE_EVS, 0, RARA_NATURE_ID), {})
        self.assertEqual(project_stats(YUNGOOS_BASE, YUNGOOS_IVS, TANQUE_EVS, 101, RARA_NATURE_ID), {})

    def test_naturaleza_desconocida_no_rompe_solo_deja_de_aplicar_el_ajuste(self) -> None:
        stats = project_stats(YUNGOOS_BASE, YUNGOOS_IVS, TANQUE_EVS, 40, None)
        neutral = project_stats(YUNGOOS_BASE, YUNGOOS_IVS, TANQUE_EVS, 40, RARA_NATURE_ID)
        self.assertEqual(stats, neutral)


class ProjectCurrentHpTests(unittest.TestCase):
    def test_conserva_el_dano_ya_sufrido_en_vez_de_curar(self) -> None:
        # 100 PS máximos, 60 actuales (40 de daño) -> al subir el máximo a 125,
        # se mantienen los mismos 40 de daño, no se rellena la barra entera.
        self.assertEqual(project_current_hp(60, 100, 125), 85)

    def test_pokemon_debilitado_sigue_debilitado(self) -> None:
        self.assertEqual(project_current_hp(0, 100, 125), 0)

    def test_nunca_baja_de_uno_si_no_estaba_debilitado(self) -> None:
        # Daño mayor que el nuevo máximo: se queda vivo con 1 PS, no en negativo.
        self.assertEqual(project_current_hp(1, 200, 50), 1)

    def test_a_maxima_vida_sigue_a_maxima_vida(self) -> None:
        self.assertEqual(project_current_hp(100, 100, 125), 125)


if __name__ == "__main__":
    unittest.main()
