"""El menú de una tarjeta de juego aparece y desaparece con un fundido.

Los banners nuevos llevan el título dibujado dentro, así que en reposo la
tarjeta es solo el banner. El menú —estado del archivo, ARCHIVOS y ABRIR— sale
al pasar el ratón por encima.

Dos decisiones que costó llegar a ellas y que se fijan aquí:

1. **Se oscurece la tarjeta entera, no la mitad de abajo.** El primer intento
   copiaba la franja fija de antes, y esa franja cae justo sobre el título que
   el banner lleva dibujado: a media transición se leían dos superpuestos.

2. **El texto se revela tarde y con curva.** Un texto de Tk no tiene opacidad;
   lo que se hace es moverlo desde el color del fondo que tiene debajo, y ese
   color se estima con la media de la zona. Mientras el banner se siga viendo,
   su textura no coincide con esa media y el rótulo asoma como un rectángulo
   plano. El botón ABRIR, que va relleno, era el que más cantaba.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_components import fundido_de_tarjeta as fundido  # noqa: E402

JUEGOS_CON_BANNER = (
    "bw", "b2w2", "xy", "oras", "sm", "usum", "bdsp", "dp", "pt", "hgss",
)


def test_los_diez_juegos_tienen_su_banner_aunque_tres_esten_ocultos() -> None:
    """dp/pt/hgss vuelven a estar ocultos desde el 07-09-2026 (a petición

    explícita del usuario, tras diez rondas de validación física del carril
    de combate de HGSS sin estabilizar), pero sus banners no se borran: se
    ocultan y se recuperan por `GAMES_OCULTOS`, no por perder el asset.
    """
    from app.config import RESOURCES_DIR

    visibles = [
        clave for clave, _label, _activo in RoleRunManager.GAME_OPTIONS
        if clave not in RoleRunManager.GAMES_OCULTOS
    ]
    assert sorted(visibles) == sorted(set(JUEGOS_CON_BANNER) - RoleRunManager.GAMES_OCULTOS)
    for clave in JUEGOS_CON_BANNER:
        assert (Path(RESOURCES_DIR) / "game_cards" / f"{clave}.png").exists(), clave


def test_hay_una_capa_por_paso_mas_la_del_reposo() -> None:
    """`pintar_menu` indexa por paso: una capa de menos y revienta al final."""
    from PIL import Image

    base = Image.new("RGBA", RoleRunManager.WELCOME_TARJETA, (40, 80, 120, 255))
    capas = fundido.capas_de_la_franja(base, RoleRunManager.WELCOME_FRANJA)

    assert len(capas) == fundido.PASOS + 1


def test_en_reposo_la_tarjeta_es_el_banner_intacto() -> None:
    from PIL import Image

    base = Image.new("RGBA", (60, 40), (200, 30, 90, 255))
    capas = fundido.capas_de_la_franja(base, (0, 0, 60, 40), radio=0)

    assert capas[0].tobytes() == base.tobytes()


def test_el_ultimo_paso_no_borra_del_todo_el_banner() -> None:
    """Sin dejar pasar algo, la tarjeta se queda en un rectángulo plano."""
    from PIL import Image

    base = Image.new("RGBA", (60, 40), (255, 255, 255, 255))
    capas = fundido.capas_de_la_franja(base, (0, 0, 60, 40), radio=0)
    centro = capas[-1].getpixel((30, 20))

    assert centro[:3] != fundido.NEGRO_DE_LA_FRANJA, "el banner desaparecio del todo"
    assert max(centro[:3]) < 60, "no llego a oscurecerse lo suficiente"


def test_la_capa_cubre_la_tarjeta_entera_y_no_solo_la_mitad_de_abajo() -> None:
    """Tapar media tarjeta cruzaba el titulo que el banner lleva dentro."""
    izquierda, arriba, derecha, abajo = RoleRunManager.WELCOME_FRANJA
    ancho, alto = RoleRunManager.WELCOME_TARJETA

    assert arriba <= 4, "la capa empieza a media tarjeta"
    assert alto - abajo <= 4
    assert (derecha - izquierda) >= ancho - 8


def test_el_texto_no_empieza_hasta_que_el_banner_esta_apagado() -> None:
    assert fundido.avance_del_texto(0.0) == 0.0
    assert fundido.avance_del_texto(0.5) == 0.0
    assert fundido.avance_del_texto(1.0) == 1.0

    # Cuando arranca, el fondo ya tiene que estar mayormente negro.
    apagado = fundido.TEXTO_EMPIEZA_EN * fundido.MAXIMA_OPACIDAD
    assert apagado >= 0.5, "el texto asomaria como un rectangulo plano"


def test_el_revelado_carga_hacia_el_final() -> None:
    """Con reparto igual, el boton relleno se veia antes que los rotulos."""
    mitad = (1.0 + fundido.TEXTO_EMPIEZA_EN) / 2

    assert fundido.avance_del_texto(mitad) < 0.5


def test_el_texto_nace_del_color_que_tiene_debajo() -> None:
    """Si naciera de otro color, se encenderia de golpe en vez de aparecer."""
    fondo = "#C08040"
    debajo = fundido.color_bajo_la_franja(fondo, 0.0)

    assert debajo.upper() == fondo.upper()
    assert fundido.mezclar(debajo, "#FFFFFF", 0.0).upper() == fondo.upper()


def test_oscurecer_acerca_el_fondo_al_negro_de_la_capa() -> None:
    claro = fundido.color_bajo_la_franja("#FFFFFF", 0.0)
    oscuro = fundido.color_bajo_la_franja("#FFFFFF", 1.0)

    assert claro == "#FFFFFF"
    assert max(fundido.a_rgb(oscuro)) < 40


def test_cada_banner_se_mide_por_su_cuenta() -> None:
    """Sol/Luna es clarisimo y Blanca/Negra casi negro."""
    from app.config import RESOURCES_DIR

    medidos = {
        clave: RoleRunManager._colores_bajo_el_menu(
            RoleRunManager, Path(RESOURCES_DIR) / "game_cards" / f"{clave}.png",
        )
        for clave in JUEGOS_CON_BANNER
    }
    for clave, colores in medidos.items():
        assert len(colores) == len(RoleRunManager.WELCOME_SITIOS), clave
    assert len({tuple(c) for c in medidos.values()}) == len(medidos), (
        "dos juegos comparten color de partida: no se estan midiendo"
    )


def test_sin_imagen_se_devuelve_un_color_neutro_y_no_se_rompe() -> None:
    colores = RoleRunManager._colores_bajo_el_menu(
        RoleRunManager, Path("no/existe/este/banner.png"),
    )

    assert colores == tuple("#111111" for _ in RoleRunManager.WELCOME_SITIOS)


def test_el_fundido_avanza_de_uno_en_uno_en_los_dos_sentidos() -> None:
    assert fundido.siguiente_paso(0, fundido.PASOS) == 1
    assert fundido.siguiente_paso(fundido.PASOS, 0) == fundido.PASOS - 1
    assert fundido.siguiente_paso(4, 4) == 4


def test_el_fundido_no_se_pasa_de_los_extremos() -> None:
    assert fundido.siguiente_paso(0, -5) == 0
    assert fundido.siguiente_paso(fundido.PASOS, 99) == fundido.PASOS


def test_dura_lo_que_dura_un_fundido_y_no_una_espera() -> None:
    duracion = fundido.PASOS * fundido.FOTOGRAMA_MS
    assert 120 <= duracion <= 260, f"{duracion} ms"


def test_el_menu_no_se_coloca_hasta_que_empieza_a_verse() -> None:
    fuente = inspect.getsource(RoleRunManager._render_welcome)

    assert "if revelado <= 0.0:" in fuente
    assert "widget.place_forget()" in fuente


def test_los_fotogramas_del_fundido_no_engordan_la_lista_de_animaciones() -> None:
    """Se vacia solo al repintar la pantalla: un fotograma por hover la llenaria."""
    fuente = inspect.getsource(RoleRunManager._programar_fotograma)
    codigo = chr(10).join(
        linea for linea in fuente.splitlines() if not linea.strip().startswith("#")
    )

    assert "_welcome_animation_ids.append" not in codigo
    assert "self.after(" in codigo


def test_pasar_el_raton_arranca_el_fundido_en_los_dos_sentidos() -> None:
    fuente = inspect.getsource(RoleRunManager._render_welcome)
    trozo = fuente[fuente.index("def set_hover"):]

    assert "fundido.ir(fundido_de_tarjeta.PASOS if active else 0)" in trozo


def test_cada_tarjeta_recibe_su_animacion_como_valor() -> None:
    """El fallo real: el menu solo salia en Perla Reluciente.

    El animador se llamaba a si mismo por su nombre y quien lo arrancaba
    tambien lo nombraba. Python resuelve esos nombres al ejecutar la linea, no
    al definir la funcion, asi que al acabar el bucle los siete apuntaban al
    ultimo. Pasandolo como valor por defecto, cada `set_hover` se queda con el
    suyo.
    """
    fuente = inspect.getsource(RoleRunManager._render_welcome)
    firma = fuente[fuente.index("def set_hover"):]
    firma = firma[:firma.index(")")]

    assert "fundido=animacion" in firma
    assert "def animar_fundido" not in fuente, (
        "vuelve a haber un animador anidado que puede resolverse tarde"
    )


def _fundido_de_prueba(pintados: list, agenda: list):
    return fundido.Fundido(
        pintados.append,
        lambda ms, funcion: (agenda.append(funcion), True)[1],
    )


def test_siete_tarjetas_animan_cada_una_la_suya() -> None:
    """Es exactamente lo que fallaba, montado como lo monta el selector."""
    pintados = [[] for _ in JUEGOS_CON_BANNER]
    agenda: list = []
    fundidos = [_fundido_de_prueba(destino, agenda) for destino in pintados]

    fundidos[0].ir(fundido.PASOS)
    while agenda:
        agenda.pop(0)()

    assert pintados[0] == list(range(1, fundido.PASOS + 1))
    assert all(not otros for otros in pintados[1:]), (
        "una tarjeta ha animado la de otra"
    )


def test_salir_a_mitad_de_camino_vuelve_desde_donde_estaba() -> None:
    pintados: list[int] = []
    agenda: list = []
    animacion = _fundido_de_prueba(pintados, agenda)

    animacion.ir(fundido.PASOS)
    for _dos_fotogramas in range(2):
        agenda.pop(0)()
    a_la_ida = animacion.paso

    animacion.ir(0)
    while agenda:
        agenda.pop(0)()

    assert a_la_ida == 3
    assert animacion.paso == 0
    assert pintados[-1] == 0
    assert pintados == [1, 2, 3, 2, 1, 0], "el regreso no continua desde donde iba"


def test_entrar_y_salir_deprisa_no_deja_dos_animaciones_peleandose() -> None:
    pintados: list[int] = []
    agenda: list = []
    animacion = _fundido_de_prueba(pintados, agenda)

    animacion.ir(fundido.PASOS)
    animacion.ir(0)
    animacion.ir(fundido.PASOS)

    assert len(agenda) == 1, "hay mas de un fotograma agendado a la vez"


def test_si_no_se_puede_agendar_el_fundido_no_se_queda_colgado() -> None:
    """Sin esto, `en_marcha` se quedaria en cierto y no arrancaria nunca mas."""
    pintados: list[int] = []
    animacion = fundido.Fundido(pintados.append, lambda _ms, _funcion: False)

    animacion.ir(fundido.PASOS)
    assert animacion.en_marcha is False

    animacion.ir(fundido.PASOS)
    assert pintados == [1, 2]
