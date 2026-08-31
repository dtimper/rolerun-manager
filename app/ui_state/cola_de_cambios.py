"""Cola serializada de cambios en vuelo hacia el juego.

RoleRun escribe sobre la RAM de un juego en marcha. Dos escrituras simultáneas
se pisan, así que la cola es estrictamente de un solo trabajo en vuelo. Lo que
esta pieza aporta no es concurrencia, sino ORDEN y VISIBILIDAD: antes, un
cambio nuevo mientras había otro en curso se rechazaba (``return False``) o se
reprogramaba a ciegas cada 220 ms sin garantía de llegar en el orden en que el
usuario lo pidió, y una superficie opaca tapaba la aplicación mientras tanto.

Deliberadamente NO tiene hilos. El despacho real sigue siendo el hilo que ya
existía (``RoleRunRealtimeWrite``) y la interfaz lo bombea desde el hilo de
Tk: ``siguiente()`` antes de lanzarlo, ``terminar()`` al recibir el resultado.
Así toda la máquina de estados es comprobable sin sincronización y el camino
más delicado de la aplicación no cambia de modelo de hilos.

Política ante un fallo: la cola SE PAUSA. Un trabajo que no llegó al juego deja
el estado real en un punto que los trabajos siguientes ya no pueden dar por
supuesto; seguir escribiendo a ciegas sobre una partida viva es peor que parar
y preguntar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Literal


EstadoTrabajo = Literal["encolado", "aplicando", "hecho", "fallido", "cancelado"]


@dataclass(slots=True)
class Trabajo:
    """Un lote de cambios que se aplicará al juego como una sola operación."""

    id: int
    cambios: list
    etiqueta: str = ""
    automatico: bool = False
    estado: EstadoTrabajo = "encolado"
    error: str | None = None
    resultado: object | None = None

    @property
    def en_vuelo(self) -> bool:
        return self.estado == "aplicando"

    @property
    def termino_bien(self) -> bool:
        return self.estado == "hecho"


@dataclass(frozen=True, slots=True)
class EstadoCola:
    """Foto de la cola para pintar la barra inferior sin recorrerla."""

    aplicando: Trabajo | None = None
    en_cola: int = 0
    pausada: bool = False
    motivo_pausa: str = ""

    @property
    def total_en_curso(self) -> int:
        return self.en_cola + (1 if self.aplicando is not None else 0)

    @property
    def hay_trabajo(self) -> bool:
        return self.total_en_curso > 0

    def resumen(self) -> str:
        """Texto corto para la barra: nunca afirma que algo ya se aplicó."""
        if self.aplicando is None and not self.en_cola:
            return ""
        partes: list[str] = []
        if self.aplicando is not None:
            partes.append("1 aplicándose")
        if self.en_cola:
            partes.append(
                f"{self.en_cola} en cola" if self.en_cola > 1 else "1 en cola"
            )
        texto = " · ".join(partes)
        return f"{texto} (en pausa)" if self.pausada else texto


class ColaDeCambios:
    """Máquina de estados FIFO con un único trabajo en vuelo.

    El uso previsto desde la interfaz es siempre el mismo par:

        trabajo_id = cola.encolar(cambios, etiqueta="Enseñar Rayo")
        self._bombear_cola_de_cambios()   # siguiente() y, si lo hay, hilo

    y, al volver el resultado al hilo de Tk:

        cola.terminar(trabajo_id, resultado=result, error=error)
        self._bombear_cola_de_cambios()
    """

    def __init__(
        self,
        *,
        al_cambiar: Callable[[EstadoCola], None] | None = None,
    ) -> None:
        self._al_cambiar = al_cambiar
        self._pendientes: list[Trabajo] = []
        self._en_vuelo: Trabajo | None = None
        self._historial: list[Trabajo] = []
        self._siguiente_id = 1
        self._pausada = False
        self._motivo_pausa = ""

    # ---------- consulta ----------

    @property
    def pausada(self) -> bool:
        return self._pausada

    @property
    def motivo_pausa(self) -> str:
        return self._motivo_pausa

    @property
    def en_vuelo(self) -> Trabajo | None:
        return self._en_vuelo

    @property
    def pendientes(self) -> tuple[Trabajo, ...]:
        return tuple(self._pendientes)

    @property
    def historial(self) -> tuple[Trabajo, ...]:
        return tuple(self._historial)

    def estado(self) -> EstadoCola:
        return EstadoCola(
            aplicando=self._en_vuelo,
            en_cola=len(self._pendientes),
            pausada=self._pausada,
            motivo_pausa=self._motivo_pausa,
        )

    def buscar(self, trabajo_id: int) -> Trabajo | None:
        if self._en_vuelo is not None and self._en_vuelo.id == trabajo_id:
            return self._en_vuelo
        for trabajo in (*self._pendientes, *self._historial):
            if trabajo.id == trabajo_id:
                return trabajo
        return None

    def contiene_cambio(self, cambio) -> bool:
        """¿Hay ya algún trabajo vivo ocupándose de este cambio concreto?

        La interfaz identifica los cambios por ``id()`` del dataclass, igual que
        ``_oras_live_auto_apply_ids``. Sin esta comprobación, el mismo cambio
        podría encolarse dos veces —el flujo automático y el botón manual— y
        escribirse dos veces al juego.
        """
        objetivo = id(cambio)
        vivos = ([self._en_vuelo] if self._en_vuelo is not None else []) + self._pendientes
        return any(
            any(id(c) == objetivo for c in trabajo.cambios) for trabajo in vivos
        )

    def ids_de_cambios_vivos(self) -> set[int]:
        """``id()`` de todo cambio encolado o en vuelo, para la proyección."""
        vivos = ([self._en_vuelo] if self._en_vuelo is not None else []) + self._pendientes
        return {id(cambio) for trabajo in vivos for cambio in trabajo.cambios}

    # ---------- escritura ----------

    def encolar(
        self,
        cambios: Iterable,
        *,
        etiqueta: str = "",
        automatico: bool = False,
    ) -> int:
        """Añade un trabajo al final. NUNCA rechaza: ese es todo el objetivo.

        Devuelve el identificador del trabajo, que es lo único que hace falta
        para cancelarlo o para cerrarlo con ``terminar``.
        """
        lote = list(cambios)
        if not lote:
            raise ValueError("un trabajo sin cambios no llega a escribir nada")
        trabajo = Trabajo(
            id=self._siguiente_id,
            cambios=lote,
            etiqueta=str(etiqueta),
            automatico=bool(automatico),
        )
        self._siguiente_id += 1
        self._pendientes.append(trabajo)
        self._notificar()
        return trabajo.id

    def siguiente(self) -> Trabajo | None:
        """Saca el próximo trabajo si se puede escribir ahora mismo.

        Devuelve ``None`` —sin efecto alguno— si ya hay uno en vuelo o si la
        cola está en pausa tras un fallo. Quien despacha decide qué hacer con
        ese ``None``: normalmente, nada.
        """
        if self._en_vuelo is not None or self._pausada or not self._pendientes:
            return None
        trabajo = self._pendientes.pop(0)
        trabajo.estado = "aplicando"
        self._en_vuelo = trabajo
        self._notificar()
        return trabajo

    def terminar(
        self,
        trabajo_id: int,
        *,
        resultado: object | None = None,
        error: str | None = None,
    ) -> Trabajo | None:
        """Cierra el trabajo en vuelo. Un error deja la cola en pausa.

        Ignora un identificador que ya no está en vuelo: un resultado tardío de
        una sesión anterior no debe reabrir ni desordenar la cola actual.
        """
        trabajo = self._en_vuelo
        if trabajo is None or trabajo.id != int(trabajo_id):
            return None
        self._en_vuelo = None
        trabajo.resultado = resultado
        if error:
            trabajo.estado = "fallido"
            trabajo.error = str(error)
            self._pausada = True
            self._motivo_pausa = str(error)
        else:
            trabajo.estado = "hecho"
        self._historial.append(trabajo)
        self._notificar()
        return trabajo

    def cancelar(self, trabajo_id: int) -> bool:
        """Retira un trabajo que todavía no ha salido hacia el juego.

        Un trabajo en vuelo no se cancela: sus bytes ya pueden estar escritos y
        fingir lo contrario es exactamente la mentira que RoleRun no cuenta.
        """
        for indice, trabajo in enumerate(self._pendientes):
            if trabajo.id == int(trabajo_id):
                trabajo.estado = "cancelado"
                self._pendientes.pop(indice)
                self._historial.append(trabajo)
                self._notificar()
                return True
        return False

    def reanudar(self) -> None:
        """Levanta la pausa dejando la cola intacta y en orden."""
        if not self._pausada:
            return
        self._pausada = False
        self._motivo_pausa = ""
        self._notificar()

    def descartar_pendientes(self) -> list[Trabajo]:
        """Vacía la espera (por ejemplo, tras decidir no reintentar un fallo)."""
        descartados = self._pendientes
        self._pendientes = []
        for trabajo in descartados:
            trabajo.estado = "cancelado"
            self._historial.append(trabajo)
        self._pausada = False
        self._motivo_pausa = ""
        if descartados:
            self._notificar()
        return descartados

    def olvidar_todo(self) -> None:
        """Reinicio total: cambio de partida, de proyecto o cierre de sesión.

        Un trabajo en vuelo se marca como cancelado y su ``terminar`` posterior
        no encontrará nada que cerrar, que es justo lo que debe ocurrir cuando
        el resultado ya no pertenece a la sesión visible.
        """
        if self._en_vuelo is not None:
            self._en_vuelo.estado = "cancelado"
            self._historial.append(self._en_vuelo)
            self._en_vuelo = None
        self.descartar_pendientes()
        self._pausada = False
        self._motivo_pausa = ""
        self._notificar()

    # ---------- interno ----------

    def _notificar(self) -> None:
        if self._al_cambiar is None:
            return
        self._al_cambiar(self.estado())
