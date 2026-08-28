"""Los adornos no pueden estorbar a lo que el usuario estaba haciendo.

Un sonido que no suena o un sprite que no vuela son un defecto estético. Un
sonido que bloquea el hilo de Tk, o un vuelo que deja un sprite pegado en mitad
de la pantalla, son un defecto de verdad. Aquí se fija la diferencia.

Y hay dos frenos que no son opcionales:

- **el ratón**: una caja del PC son treinta casillas y se recorren en menos de un
  segundo, así que sin un mínimo entre sonidos eso es una ametralladora;
- **los avisos**: un solo movimiento pasa por «confirmado» tres veces —al
  preparar, al escribir y al releer el PC—, y sonarían tres campanitas.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.animacion import (  # noqa: E402
    FOTOGRAMA_MS,
    Vuelo,
    altura_del_arco,
    centro_en_la_raiz,
    suavizar,
)
from app.sonido import CATALOGO, Sonidos, preparar  # noqa: E402


# --------------------------------------------------------------- los sonidos

def test_se_sintetizan_los_seis_y_son_wav_de_verdad(tmp_path) -> None:
    rutas = preparar(tmp_path)

    assert set(rutas) == set(CATALOGO)
    for nombre, ruta in rutas.items():
        with wave.open(str(ruta)) as archivo:
            assert archivo.getnchannels() == 1
            assert archivo.getsampwidth() == 2
            duracion = archivo.getnframes() / archivo.getframerate()
        assert 0.02 <= duracion <= 1.0, f"{nombre} dura {duracion:.2f}s"


def test_un_wav_puesto_por_el_usuario_no_se_pisa(tmp_path) -> None:
    """Es la vía para traer sonidos propios sin tocar el programa."""
    preparar(tmp_path)
    propio = tmp_path / "confirmacion.wav"
    propio.write_bytes(b"esto lo puse yo")

    preparar(tmp_path)

    assert propio.read_bytes() == b"esto lo puse yo"


def test_el_raton_tiene_freno(tmp_path) -> None:
    sonados: list[str] = []
    sonidos = Sonidos(tmp_path, reproductor=lambda ruta: sonados.append(ruta.stem))

    for _ in range(20):
        sonidos.reproducir("raton")
    time.sleep(0.05)

    assert len(sonados) == 1, "una caja recorrida sonaria veinte veces"


def test_el_freno_del_raton_no_frena_a_los_demas(tmp_path) -> None:
    sonados: list[str] = []
    sonidos = Sonidos(tmp_path, reproductor=lambda ruta: sonados.append(ruta.stem))

    sonidos.reproducir("raton")
    sonidos.reproducir("confirmacion")
    sonidos.reproducir("seleccion")
    time.sleep(0.08)

    assert sorted(sonados) == ["confirmacion", "raton", "seleccion"]


def test_apagado_no_toca_ni_el_disco(tmp_path) -> None:
    sonidos = Sonidos(tmp_path, activo=False, reproductor=lambda ruta: None)

    assert sonidos.reproducir("confirmacion") is False
    assert not list(tmp_path.glob("*.wav")), "no deberia haber sintetizado nada"


def test_un_sonido_que_no_existe_no_revienta(tmp_path) -> None:
    sonidos = Sonidos(tmp_path, reproductor=lambda ruta: None)
    assert sonidos.reproducir("no_existe") is False


def test_un_reproductor_que_falla_no_sube(tmp_path) -> None:
    """Perder la partida por un pitido seria absurdo."""

    def _revienta(_ruta):
        raise RuntimeError("no hay tarjeta de sonido")

    sonidos = Sonidos(tmp_path, reproductor=_revienta)

    assert sonidos.reproducir("confirmacion") is True
    time.sleep(0.05)


def test_suena_en_otro_hilo(tmp_path) -> None:
    """`winsound` bloquea al llamante, y el llamante es el hilo de Tk."""
    import threading

    hilos: list[str] = []
    sonidos = Sonidos(
        tmp_path, reproductor=lambda _r: hilos.append(threading.current_thread().name),
    )

    sonidos.reproducir("confirmacion")
    time.sleep(0.08)

    assert hilos and hilos[0] != threading.current_thread().name


# ------------------------------------------------------------- la animación

def test_el_suavizado_empieza_y_acaba_donde_debe() -> None:
    assert suavizar(0.0) == 0.0
    assert suavizar(1.0) == 1.0
    assert abs(suavizar(0.5) - 0.5) < 1e-9


def test_el_suavizado_arranca_despacio_y_frena() -> None:
    """A velocidad constante se lee como una animacion de programa."""
    assert suavizar(0.1) < 0.1
    assert suavizar(0.9) > 0.9


def test_el_suavizado_aguanta_valores_fuera_de_rango() -> None:
    assert suavizar(-3.0) == 0.0
    assert suavizar(7.5) == 1.0


def test_el_arco_sube_a_mitad_de_camino_y_no_en_los_extremos() -> None:
    assert altura_del_arco(0.0, 80) == 0.0
    assert abs(altura_del_arco(1.0, 80)) < 1e-9
    assert altura_del_arco(0.5, 80) == -80


class _Widget:
    def __init__(self, x: int, y: int, ancho: int = 40, alto: int = 40) -> None:
        self._x, self._y, self._ancho, self._alto = x, y, ancho, alto
        self.destruido = False
        self.posiciones: list[tuple[int, int]] = []

    def winfo_exists(self) -> bool:
        return not self.destruido

    def winfo_rootx(self) -> int:
        return self._x

    def winfo_rooty(self) -> int:
        return self._y

    def winfo_width(self) -> int:
        return self._ancho

    def winfo_height(self) -> int:
        return self._alto

    def place(self, x: int, y: int, anchor: str = "center") -> None:
        self.posiciones.append((x, y))

    def destroy(self) -> None:
        self.destruido = True


class _Raiz(_Widget):
    """Una ventana falsa que ejecuta los `after` en cuanto se piden."""

    def __init__(self) -> None:
        super().__init__(0, 0)
        self.cancelados: list[int] = []
        self._siguiente = 0
        self.pendientes: dict[int, object] = {}

    def after(self, _ms: int, funcion):
        self._siguiente += 1
        self.pendientes[self._siguiente] = funcion
        return self._siguiente

    def after_cancel(self, identificador) -> None:
        self.cancelados.append(identificador)
        self.pendientes.pop(identificador, None)

    def correr(self, veces: int = 200) -> None:
        for _ in range(veces):
            if not self.pendientes:
                return
            clave = next(iter(self.pendientes))
            funcion = self.pendientes.pop(clave)
            funcion()


def test_el_centro_es_relativo_a_la_ventana() -> None:
    """Los paneles tienen scroll: sus coordenadas propias no sirven."""
    raiz = _Widget(100, 50)
    dentro = _Widget(300, 250, ancho=60, alto=20)

    assert centro_en_la_raiz(dentro, raiz) == (230, 210)


def test_de_un_widget_destruido_no_se_saca_posicion() -> None:
    raiz = _Widget(0, 0)
    ido = _Widget(10, 10)
    ido.destroy()

    assert centro_en_la_raiz(ido, raiz) is None


def test_el_vuelo_llega_al_destino_y_se_retira() -> None:
    raiz = _Raiz()
    movil = _Widget(0, 0)

    Vuelo(raiz, movil, (0, 0), (400, 200), duracion_ms=5 * FOTOGRAMA_MS).empezar()
    raiz.correr()

    assert movil.posiciones[0] == (0, 0)
    assert movil.posiciones[-1] == (400, 200)
    assert movil.destruido, "un sprite huerfano se queda pegado en la pantalla"


def test_el_vuelo_avisa_al_terminar() -> None:
    raiz = _Raiz()
    avisos: list[str] = []

    Vuelo(
        raiz, _Widget(0, 0), (0, 0), (10, 10),
        duracion_ms=2 * FOTOGRAMA_MS, al_terminar=lambda: avisos.append("fin"),
    ).empezar()
    raiz.correr()

    assert avisos == ["fin"]


def test_pararlo_a_media_animacion_limpia_y_avisa_una_sola_vez() -> None:
    """La pagina puede repintarse o la ventana cerrarse en pleno vuelo."""
    raiz = _Raiz()
    movil = _Widget(0, 0)
    avisos: list[str] = []
    vuelo = Vuelo(
        raiz, movil, (0, 0), (400, 0),
        duracion_ms=40 * FOTOGRAMA_MS, al_terminar=lambda: avisos.append("fin"),
    )
    vuelo.empezar()

    vuelo.parar()
    vuelo.parar()

    assert movil.destruido
    assert avisos == ["fin"]
    assert raiz.cancelados, "quedaba un fotograma programado"


def test_si_el_movil_muere_en_pleno_vuelo_se_recoge() -> None:
    raiz = _Raiz()

    class _Fragil(_Widget):
        def place(self, x, y, anchor="center"):
            raise RuntimeError("widget destruido por debajo")

    movil = _Fragil(0, 0)
    Vuelo(raiz, movil, (0, 0), (400, 0), duracion_ms=10 * FOTOGRAMA_MS).empezar()
    raiz.correr()

    assert movil.destruido


def test_el_programa_no_trae_sonido() -> None:
    """Los sintetizados sonaban a Windows y se apagaron.

    Un adorno que molesta es peor que no tenerlo. La maquinaria se queda para
    cuando haya sonidos propios, pero no puede volver a encenderse sola.
    """
    import inspect

    from app.ui import RoleRunManager

    fuente = inspect.getsource(RoleRunManager.__init__)
    assert "Sonidos(activo=False)" in fuente
