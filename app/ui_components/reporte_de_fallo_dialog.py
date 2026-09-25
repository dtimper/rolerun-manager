"""Ventana REPORTAR FALLO: describir el fallo, adjuntar capturas y enviarlo.

Es una ventana propia del sistema, no una capa dentro de RoleRun: se abre desde
el menú flotante, con la ventana principal escondida detrás del emulador. Tiene
barra de título y entrada en Alt+Tab a propósito: quien quiera hacer una
captura con otra herramienta y volver para pegarla tiene que poder encontrarla.

Ctrl+V dentro del mensaje adjunta la imagen del portapapeles (una captura
copiada sin guardar) o los archivos de imagen copiados en el Explorador. Si lo
que hay es texto, pega el texto como siempre.
"""

from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from ..config import BG, DANGER, GOLD, MUTED, PANEL, PANEL_ALT, SUCCESS, TEXT
from .window_focus import (
    foreground_belongs_to_this_process,
    guard_topmost_on_focus_loss,
    release_focus_guard,
)

_EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
_MINIATURA = (132, 76)


def _imagen_del_portapapeles() -> list[Any] | None:
    """Imágenes del portapapeles, o ``None`` si lo que hay no es una imagen."""
    try:
        from PIL import Image, ImageGrab

        contenido = ImageGrab.grabclipboard()
    except Exception:
        return None
    if contenido is None:
        return None
    if isinstance(contenido, list):
        imagenes = []
        for ruta in contenido:
            if Path(str(ruta)).suffix.lower() not in _EXTENSIONES_IMAGEN:
                continue
            try:
                with Image.open(ruta) as abierta:
                    imagenes.append(abierta.copy())
            except Exception:
                continue
        return imagenes or None
    try:
        contenido.load()
    except Exception:
        return None
    return [contenido.copy()]


class ReporteDeFalloDialog(ctk.CTkToplevel):
    """``enviar(texto, capturas, carpeta_previa) -> carpeta`` corre en un hilo.

    Debe lanzar una excepción con un mensaje legible si no pudo enviar, pero
    devolviendo antes la carpeta en ``error.carpeta`` si llegó a guardarla:
    reintentar reutiliza esa carpeta en vez de crear otra.
    """

    def __init__(
        self,
        master,
        *,
        enviar: Callable[[str, list[Any], Path | None], Path],
        captura_inicial: Any | None = None,
        al_cerrar: Callable[[Path | None, bool], None] | None = None,
        centro: tuple[int, int] | None = None,
        max_capturas: int = 8,
    ) -> None:
        super().__init__(master)
        self._enviar = enviar
        self._al_cerrar = al_cerrar
        self._max_capturas = max_capturas
        self._capturas: list[Any] = []
        self._miniaturas: list[ctk.CTkImage] = []
        self._enviando = False
        self._carpeta: Path | None = None
        self._cerrado = False
        self._resultado: dict[str, Any] | None = None
        self._guardia = None
        self._espera_foco_id: str | None = None

        self.title("Reportar fallo · RoleRun Manager")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

        cuerpo = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=16, border_width=2,
                              border_color=GOLD)
        cuerpo.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(cuerpo, text="REPORTAR FALLO", text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 22, "bold")).pack(
                         anchor="w", padx=24, pady=(20, 2))
        ctk.CTkLabel(
            cuerpo,
            text="¿Qué estabas haciendo, qué esperabas que pasara y qué pasó?",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 13),
        ).pack(anchor="w", padx=24, pady=(0, 10))

        self.mensaje = ctk.CTkTextbox(
            cuerpo, width=560, height=170, wrap="word", fg_color=PANEL_ALT, text_color=TEXT,
            border_width=1, border_color="#4A3D25", corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 14),
        )
        self.mensaje.pack(fill="x", padx=24)
        texto = self.mensaje._textbox
        texto.bind("<<Paste>>", self._pegar, add="+")
        texto.bind("<KeyRelease>", lambda _e: self._actualizar_boton(), add="+")
        texto.bind("<Control-Return>", self._enviar_desde_teclado)

        cabecera = ctk.CTkFrame(cuerpo, fg_color="transparent")
        cabecera.pack(fill="x", padx=24, pady=(16, 0))
        self._titulo_capturas = ctk.CTkLabel(
            cabecera, text="", text_color=GOLD, font=ctk.CTkFont("Segoe UI", 13, "bold"),
        )
        self._titulo_capturas.pack(side="left")
        self._boton_anadir = ctk.CTkButton(
            cabecera, text="+  AÑADIR CAPTURA", width=150, height=30, corner_radius=8,
            fg_color="transparent", hover_color="#34302A", border_width=1,
            border_color="#4A3D25", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 12, "bold"), command=self._elegir_archivos,
        )
        self._boton_anadir.pack(side="right")
        ctk.CTkLabel(
            cuerpo,
            text="Ctrl+V dentro del mensaje pega una captura que tengas copiada.",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12),
        ).pack(anchor="w", padx=24, pady=(2, 6))

        self._tira = ctk.CTkFrame(cuerpo, fg_color=BG, corner_radius=10, height=_MINIATURA[1] + 20)
        self._tira.pack(fill="x", padx=24)
        self._tira.pack_propagate(False)

        self._estado = ctk.CTkLabel(
            cuerpo, text="Se adjunta también la versión, el juego, el equipo y los registros de RoleRun.",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12), wraplength=560, justify="left",
        )
        self._estado.pack(anchor="w", padx=24, pady=(12, 10))

        botones = ctk.CTkFrame(cuerpo, fg_color="transparent")
        botones.pack(fill="x", padx=24, pady=(0, 20))
        self._boton_cancelar = ctk.CTkButton(
            botones, text="CANCELAR", height=40, fg_color="transparent", border_width=1,
            border_color="#4A4A4A", hover_color=PANEL_ALT, text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 13, "bold"), command=self._cancelar,
        )
        self._boton_cancelar.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._boton_enviar = ctk.CTkButton(
            botones, text="ENVIAR", height=40, fg_color=GOLD, hover_color="#A8864A",
            text_color="#151515", text_color_disabled="#5A4D35",
            font=ctk.CTkFont("Segoe UI", 13, "bold"), command=self._pulsar_enviar,
        )
        self._boton_enviar.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # Fuera del mensaje (con el foco en un botón) Ctrl+V también adjunta.
        self.bind("<Control-v>", self._pegar_fuera_del_mensaje)
        self.bind("<Control-V>", self._pegar_fuera_del_mensaje)
        self.bind("<Escape>", self._escape)

        if captura_inicial is not None:
            self._capturas.append(captura_inicial)
        self._repintar_capturas()
        self._actualizar_boton()

        # El tamaño lo da el contenido; solo se coloca. CTk escala el ancho y
        # el alto que se le pasan, pero no la posición, que va en píxeles reales.
        self.update_idletasks()
        ancho, alto = self.winfo_reqwidth(), self.winfo_reqheight()
        if centro is None:
            centro = (self.winfo_screenwidth() // 2, self.winfo_screenheight() // 2)
        x = max(0, centro[0] - ancho // 2)
        y = max(0, centro[1] - alto // 2)
        self.geometry(f"+{x}+{y}")

        # Se abre encima del emulador, que tiene el foco: sin -topmost Windows
        # lo dejaría detrás. El guardia lo suelta al cambiar de aplicación
        # (p. ej. para hacer una captura) y lo recupera al volver, pero solo
        # desde que la ventana consigue el foco: arrancarlo antes lo veía «sin
        # foco» y la mandaba detrás del juego nada más abrirse (visto en vivo).
        self.attributes("-topmost", True)
        self.lift()
        self.after(60, self._enfocar)
        self._espera_foco_id = self.after(150, lambda: self._esperar_foco(20))

    # --- capturas -----------------------------------------------------------

    def _enfocar(self) -> None:
        self._forzar_primer_plano()
        try:
            self.focus_force()
            self.mensaje.focus_set()
        except Exception:
            pass

    def _esperar_foco(self, intentos: int) -> None:
        self._espera_foco_id = None
        if self._cerrado:
            return
        if foreground_belongs_to_this_process():
            self._guardia = guard_topmost_on_focus_loss(self, self)
            return
        if intentos > 0:
            self._enfocar()
        # Sin foco se queda encima (-topmost) hasta que el usuario la pulse.
        self._espera_foco_id = self.after(150, lambda: self._esperar_foco(max(0, intentos - 1)))

    def _forzar_primer_plano(self) -> None:
        """Pide el primer plano aunque lo tenga el emulador.

        Windows rechaza ``SetForegroundWindow`` de un proceso que no está en
        primer plano. Enlazar un momento la entrada con el hilo que sí lo está
        es lo mismo que hace ``RoleRunManager._force_native_main_foreground``.
        """
        if os.name != "nt":
            return
        enlazados: list[tuple[int, int]] = []
        user32 = ctypes.windll.user32
        try:
            kernel32 = ctypes.windll.kernel32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
            user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
            user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            hwnd = int(self.winfo_id())
            ventana = int(user32.GetParent(ctypes.c_void_p(hwnd)) or 0) or hwnd
            delante = int(user32.GetForegroundWindow() or 0)
            propio = int(kernel32.GetCurrentThreadId())
            ajeno = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(delante), None) or 0) if delante else 0
            if ajeno and ajeno != propio and user32.AttachThreadInput(propio, ajeno, 1):
                enlazados.append((propio, ajeno))
            user32.BringWindowToTop(ctypes.c_void_p(ventana))
            user32.SetForegroundWindow(ctypes.c_void_p(ventana))
        except Exception:
            pass
        finally:
            for propio, ajeno in enlazados:
                try:
                    user32.AttachThreadInput(propio, ajeno, 0)
                except Exception:
                    pass

    def anadir_capturas(self, imagenes: list[Any]) -> int:
        """Añade las que quepan. Devuelve cuántas entraron."""
        hueco = self._max_capturas - len(self._capturas)
        nuevas = list(imagenes)[:max(0, hueco)]
        self._capturas.extend(nuevas)
        self._repintar_capturas()
        if len(nuevas) < len(imagenes):
            self._aviso(f"Máximo {self._max_capturas} capturas por reporte.", DANGER)
        elif nuevas:
            self._aviso(
                "Captura añadida." if len(nuevas) == 1 else f"{len(nuevas)} capturas añadidas.",
                SUCCESS,
            )
        return len(nuevas)

    def _quitar_captura(self, indice: int) -> None:
        if self._enviando:
            return
        if 0 <= indice < len(self._capturas):
            del self._capturas[indice]
            self._repintar_capturas()

    def _repintar_capturas(self) -> None:
        for hijo in self._tira.winfo_children():
            hijo.destroy()
        self._miniaturas = []
        cuantas = len(self._capturas)
        self._titulo_capturas.configure(text=f"CAPTURAS ({cuantas})" if cuantas else "CAPTURAS")
        if not cuantas:
            ctk.CTkLabel(
                self._tira, text="Sin capturas. Son opcionales, pero ayudan mucho.",
                text_color="#6A6A6A", font=ctk.CTkFont("Segoe UI", 12),
            ).pack(expand=True)
            return
        for indice, imagen in enumerate(self._capturas):
            miniatura = imagen.copy()
            miniatura.thumbnail(_MINIATURA)
            ctk_imagen = ctk.CTkImage(miniatura, size=miniatura.size)
            self._miniaturas.append(ctk_imagen)
            marco = ctk.CTkFrame(self._tira, fg_color="transparent",
                                 width=_MINIATURA[0], height=_MINIATURA[1])
            marco.pack(side="left", padx=(10, 0), pady=10)
            marco.pack_propagate(False)
            ctk.CTkLabel(marco, text="", image=ctk_imagen).pack(expand=True)
            ctk.CTkButton(
                marco, text="×", width=22, height=22, corner_radius=11,
                fg_color="#2A1D1D", hover_color=DANGER, text_color=TEXT,
                border_width=1, border_color=DANGER,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
                command=lambda i=indice: self._quitar_captura(i),
            ).place(relx=1.0, x=-2, y=2, anchor="ne")
        lleno = cuantas >= self._max_capturas
        self._boton_anadir.configure(state="disabled" if lleno else "normal")

    def _pegar(self, _event=None):
        if self._enviando:
            return "break"
        imagenes = _imagen_del_portapapeles()
        if not imagenes:
            return None  # Texto normal: que lo pegue el propio cuadro.
        self.anadir_capturas(imagenes)
        return "break"

    def _pegar_fuera_del_mensaje(self, event=None):
        if getattr(event, "widget", None) is self.mensaje._textbox:
            return None  # Ya lo trató <<Paste>>.
        return self._pegar(event)

    def _elegir_archivos(self) -> None:
        if self._enviando:
            return
        rutas = filedialog.askopenfilenames(
            parent=self, title="Elige una o varias capturas",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("Todos", "*.*")],
        )
        self._enfocar()
        if not rutas:
            return
        from PIL import Image

        imagenes, fallidas = [], 0
        for ruta in rutas:
            try:
                with Image.open(ruta) as abierta:
                    imagenes.append(abierta.copy())
            except Exception:
                fallidas += 1
        if imagenes:
            self.anadir_capturas(imagenes)
        if fallidas:
            self._aviso(
                f"{fallidas} archivo{'s' if fallidas != 1 else ''} no se pudo abrir como imagen.",
                DANGER,
            )

    # --- envío --------------------------------------------------------------

    def texto(self) -> str:
        return self.mensaje.get("1.0", "end").strip()

    def _aviso(self, texto: str, color: str = MUTED) -> None:
        self._estado.configure(text=texto, text_color=color)

    def _actualizar_boton(self) -> None:
        listo = bool(self.texto()) and not self._enviando
        self._boton_enviar.configure(
            state="normal" if listo else "disabled",
            fg_color=GOLD if listo else "#3A3326",
        )

    def _enviar_desde_teclado(self, _event=None):
        self._pulsar_enviar()
        return "break"

    def _escape(self, _event=None):
        # Con algo escrito, un Esc sin querer no puede tirar el mensaje.
        if not self._enviando and not self.texto():
            self._cancelar()
        return "break"

    def _pulsar_enviar(self) -> None:
        texto = self.texto()
        if self._enviando or not texto:
            return
        self._enviando = True
        self._actualizar_boton()
        self.mensaje.configure(state="disabled")
        for boton in (self._boton_anadir, self._boton_cancelar):
            boton.configure(state="disabled")
        self._boton_enviar.configure(text="ENVIANDO…")
        self._aviso("Enviando el reporte…", GOLD)
        capturas = list(self._capturas)
        carpeta_previa = self._carpeta
        self._resultado = None

        def trabajo() -> None:
            try:
                carpeta = self._enviar(texto, capturas, carpeta_previa)
                self._resultado = {"ok": True, "carpeta": carpeta}
            except Exception as error:
                self._resultado = {
                    "ok": False,
                    "carpeta": getattr(error, "carpeta", None),
                    "mensaje": str(error) or type(error).__name__,
                }

        threading.Thread(target=trabajo, name="RoleRunEnvioReporte", daemon=True).start()
        self.after(150, self._esperar_resultado)

    def _esperar_resultado(self) -> None:
        if self._cerrado:
            return
        resultado = self._resultado
        if resultado is None:
            self.after(150, self._esperar_resultado)
            return
        self._enviando = False
        if resultado.get("carpeta") is not None:
            self._carpeta = resultado["carpeta"]
        if resultado["ok"]:
            self._cerrar(self._carpeta, enviado=True)
            return
        self.mensaje.configure(state="normal")
        self._boton_cancelar.configure(state="normal", text="CERRAR")
        self._boton_enviar.configure(text="REINTENTAR")
        self._repintar_capturas()
        self._actualizar_boton()
        guardado = (
            f" El reporte queda guardado en Documentos\\RoleRun Manager\\Bugs\\{self._carpeta.name}."
            if self._carpeta is not None else ""
        )
        self._aviso(f"No se pudo enviar: {resultado['mensaje']}{guardado}", DANGER)

    def _cancelar(self) -> None:
        if self._enviando:
            return
        # Tras un envío fallido la carpeta ya existe: el aviso lo dice.
        self._cerrar(self._carpeta, enviado=False)

    def _cerrar(self, carpeta: Path | None, *, enviado: bool) -> None:
        if self._cerrado:
            return
        self._cerrado = True
        release_focus_guard(self._guardia)
        if self._espera_foco_id is not None:
            try:
                self.after_cancel(self._espera_foco_id)
            except Exception:
                pass
        callback = self._al_cerrar
        try:
            self.destroy()
        finally:
            if callback is not None:
                callback(carpeta, enviado)
