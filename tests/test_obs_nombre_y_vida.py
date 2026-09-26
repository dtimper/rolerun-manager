"""OBS: nombre y barra de vida por rol como piezas sueltas (26-09-2026).

El usuario pidió ver en OBS el nombre de cada Pokémon y su vida en tiempo
real, en fuentes separadas del sprite para colocarlas donde quiera y sin
romper las escenas que ya apuntan a ``libero.html``, ``asesino.html``…
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.obs_sync import ROLE_KEYS, ObsSyncService
from app.run_service import RunProjectService
from app.save_engine_client import SaveGameData, SavePokemon
from app.ui import RoleRunManager


def _pokemon(slot: int, species_id: int, nickname: str, role: str, *, hp: int = 0, max_hp: int = 0) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species_id, species=f"Especie{species_id}", nickname=nickname,
        level=30, held_item="Ninguno", ability="", moves=["A"], move_ids=[1],
        is_egg=False, markings=[False] * 6, role=role, role_symbol="",
        pid=100 + slot, tid=1, sid=2, current_hp=hp, max_hp=max_hp,
    )


def _entorno(tmp_path: Path):
    save = tmp_path / "main"
    save.write_bytes(b"save")
    service = RunProjectService(tmp_path / "Runs", tmp_path / "OBS")
    project = service.open_or_create("B2W2", "Timper", save)
    sprites = tmp_path / "sprites_src"
    sprites.mkdir()
    for species_id in (497, 506):
        (sprites / f"{species_id}.png").write_bytes(b"png")
    obs = ObsSyncService(service, sprites)
    return service, project, obs, tmp_path / "OBS"


def _game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData(game="B2W2", save_type="", generation=5, trainer="Timper", party=list(party), raw={})


def _state(obs_dir: Path) -> dict:
    return json.loads((obs_dir / "state.json").read_text(encoding="utf-8"))


def test_crea_nombre_y_vida_para_los_seis_roles_sin_tocar_el_sprite(tmp_path: Path) -> None:
    _service, project, obs, obs_dir = _entorno(tmp_path)
    obs.sync(project, _game(_pokemon(0, 497, "Serpi", "Asesino", hp=40, max_hp=120)))

    for role in ROLE_KEYS.values():
        assert (obs_dir / f"{role}.html").is_file()
        nombre = (obs_dir / f"{role}_nombre.html").read_text(encoding="utf-8")
        vida = (obs_dir / f"{role}_vida.html").read_text(encoding="utf-8")
        assert f'data-role="{role}"' in nombre and "nombre.js" in nombre
        assert f'data-role="{role}"' in vida and "vida.js" in vida
    for asset in ("pieza.css", "nombre.js", "vida.js"):
        assert (obs_dir / asset).is_file()
    # La fuente del sprite sigue siendo solo el sprite: las escenas existentes no cambian.
    assert "nombre" not in (obs_dir / "asesino.html").read_text(encoding="utf-8")
    assert "asesino_vida.html" in (obs_dir / "INSTRUCCIONES_OBS.txt").read_text(encoding="utf-8")


def test_el_estado_lleva_nombre_y_vida_de_la_misma_autoridad_que_la_barra(tmp_path: Path) -> None:
    _service, project, obs, obs_dir = _entorno(tmp_path)
    serpi = _pokemon(0, 497, "Serpi", "Asesino", hp=120, max_hp=120)
    # La autoridad (la sonda viva) dice otra cosa que el objeto: manda ella.
    obs.sync(project, _game(serpi), health=lambda p: (30, 120, 0, False))

    asesino = _state(obs_dir)["roles"]["asesino"]
    assert asesino["nickname"] == "Serpi"
    assert (asesino["hp"], asesino["max_hp"], asesino["hp_live"]) == (30, 120, False)


def test_sin_lectura_viva_la_barra_se_oculta_en_vez_de_marcar_cero(tmp_path: Path) -> None:
    _service, project, obs, obs_dir = _entorno(tmp_path)
    obs.sync(project, _game(_pokemon(0, 497, "Serpi", "Asesino")))

    asesino = _state(obs_dir)["roles"]["asesino"]
    assert asesino["max_hp"] == 0  # vida.js oculta la barra con max_hp == 0
    assert "if(!p||!p.max_hp)" in (obs_dir / "vida.js").read_text(encoding="utf-8")


def test_un_tick_de_vida_solo_reescribe_state_json(tmp_path: Path, monkeypatch) -> None:
    _service, project, obs, obs_dir = _entorno(tmp_path)
    serpi = _pokemon(0, 497, "Serpi", "Asesino", hp=120, max_hp=120)
    obs.sync(project, _game(serpi))
    sprite_rev = _state(obs_dir)["roles"]["asesino"]["sprite_rev"]

    escritos: list[str] = []
    original = Path.write_text

    def espia(self: Path, *args, **kwargs):
        escritos.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", espia)
    serpi.current_hp = 80
    obs.sync(project, _game(serpi))

    assert escritos and set(escritos) == {"state.json"}
    estado = _state(obs_dir)["roles"]["asesino"]
    assert estado["hp"] == 80
    # El sprite no debe recargarse en OBS por un cambio de vida.
    assert estado["sprite_rev"] == sprite_rev

    escritos.clear()
    obs.sync(project, _game(serpi))
    assert escritos == [], "sin cambios reales no se toca ningún archivo"


def test_un_cambio_de_ps_programa_una_sola_sincronizacion_de_obs() -> None:
    programados: list[tuple[int, object]] = []
    banco = SimpleNamespace(
        _obs_health_after_id=None,
        after=lambda ms, fn: programados.append((ms, fn)) or f"after#{len(programados)}",
    )
    banco._flush_obs_health_refresh = lambda: None
    RoleRunManager._schedule_obs_health_refresh(banco)
    RoleRunManager._schedule_obs_health_refresh(banco)
    RoleRunManager._schedule_obs_health_refresh(banco)
    assert len(programados) == 1, "varios PS seguidos se agrupan en una sola escritura"

    sincronizados: list[object] = []
    proyecciones = iter(["equipo de ahora", "equipo tras recargar"])
    banco.project = object()
    banco._projected_game_for_live_layout = lambda: next(proyecciones)
    banco._sync_obs_state = sincronizados.append
    RoleRunManager._flush_obs_health_refresh(banco)
    assert sincronizados == ["equipo de ahora"]
    assert banco._obs_health_after_id is None


def test_cada_tick_de_ps_usa_el_equipo_de_ahora_no_el_ultimo_mandado() -> None:
    """USUM, 26-09-2026: Porygon cae, la baja pendiente lo saca de OBS, el
    usuario recarga sin guardar y Porygon vuelve vivo. RoleRun lo volvía a
    mostrar, pero cada tick de PS reescribía en OBS el último equipo mandado:
    el de la baja, sin Porygon.
    """
    proyecciones = iter(["sin Porygon (baja pendiente)", "con Porygon (recargado)"])
    sincronizados: list[object] = []
    banco = SimpleNamespace(
        _obs_health_after_id=None,
        project=object(),
        _projected_game_for_live_layout=lambda: next(proyecciones),
        _sync_obs_state=sincronizados.append,
    )
    RoleRunManager._flush_obs_health_refresh(banco)
    RoleRunManager._flush_obs_health_refresh(banco)
    assert sincronizados == ["sin Porygon (baja pendiente)", "con Porygon (recargado)"]


def test_sin_run_ni_partida_no_se_escribe_nada() -> None:
    sincronizados: list[object] = []
    banco = SimpleNamespace(
        _obs_health_after_id=None, project=None,
        _projected_game_for_live_layout=lambda: None,
        _sync_obs_state=sincronizados.append,
    )
    RoleRunManager._flush_obs_health_refresh(banco)
    banco.project = object()
    RoleRunManager._flush_obs_health_refresh(banco)
    assert sincronizados == []


def test_retirar_una_baja_porque_el_pokemon_vuelve_vivo_refresca_obs() -> None:
    """La baja retirada al recargar sin guardar debe llegar también a OBS."""
    porygon = _pokemon(3, 137, "Porygon", "Support", hp=16, max_hp=19)
    retiradas: list[str] = []
    refrescos: list[str] = []
    banco = SimpleNamespace(
        _oras_live_health_snapshot=None,
        project=SimpleNamespace(slug="US-Timper"),
        project_service=SimpleNamespace(
            clear_stale_detected_faint_for_alive_party=lambda _p, ident: (
                retiradas.append(ident) or True
            ),
        ),
        _publish_live_health=lambda _g: False,
        _pokemon_identity=lambda p: f"{p.species_id}:{p.pid}",
        _close_faint_picker_for_identity=lambda _i: None,
        _sync_live_layout=lambda: refrescos.append("obs+barra"),
    )
    RoleRunManager._process_oras_health_snapshot(banco, _game(porygon), source="overworld")
    assert retiradas == ["137:103"]
    assert refrescos == ["obs+barra"]

    # Sin baja que retirar no hay escritura extra.
    refrescos.clear()
    banco.project_service.clear_stale_detected_faint_for_alive_party = lambda *_a: False
    RoleRunManager._process_oras_health_snapshot(banco, _game(porygon), source="overworld")
    assert refrescos == []
