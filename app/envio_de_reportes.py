"""Mandar un reporte de fallo por correo desde el menú flotante.

El reporte se escribe primero en disco, con el mismo formato que F8 (ver
``reporte_de_bugs``), y solo después se envía. Así, si no hay Internet o Gmail
rechaza el envío, el fallo no se pierde: queda en ``Documentos\\RoleRun
Manager\\Bugs`` y el botón puede reintentar sobre la misma carpeta sin
duplicarla.

El envío va por el SMTP de Gmail con una cuenta **dedicada solo a esto**,
distinta de la que recibe los reportes. Sus credenciales viven en
``data/reporte_correo.dat``, que se genera con
``tools/configurar_correo_de_reportes.py``. El archivo solo está ofuscado, no
cifrado: cualquiera con el programa puede sacar la contraseña. Por eso la
cuenta de envío tiene que ser desechable y nunca la personal. Lo único que la
ofuscación evita es que un rastreador automático la encuentre buscando texto
plano en el repositorio.
"""

from __future__ import annotations

import base64
import io
import json
import smtplib
import ssl
import zipfile
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import APP_VERSION, DATA_DIR
from .reporte_de_bugs import guardar_reporte

DESTINATARIO = "timpertwitchtv@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PUERTO = 465
SMTP_TIMEOUT = 30

CREDENCIALES = DATA_DIR / "reporte_correo.dat"
_CLAVE_OFUSCACION = b"RoleRun-Reportes"

#: Gmail acepta 25 MB por correo, y el base64 de los adjuntos los infla un
#: tercio. Por encima de esto se dejan fuera los registros, no las capturas.
LIMITE_ADJUNTOS = 17 * 1024 * 1024

#: Una captura PNG de pantalla completa ronda los 2-4 MB. Por encima de esto se
#: guarda en JPEG, que para ver qué pasaba en pantalla basta de sobra.
LIMITE_PNG = 2_500_000

MAX_CAPTURAS = 8

#: Registros que ``guardar_reporte`` copia y que viajan juntos en un zip.
_REGISTROS = ("bdsp_trace.jsonl", "usum_battle_health.jsonl", "tiempos.jsonl")


class EnvioNoDisponible(RuntimeError):
    """El reporte está guardado pero no se pudo mandar. El texto es para el usuario."""


@dataclass(frozen=True, slots=True)
class Credenciales:
    remitente: str
    contrasena: str


def _xor(datos: bytes) -> bytes:
    return bytes(b ^ _CLAVE_OFUSCACION[i % len(_CLAVE_OFUSCACION)] for i, b in enumerate(datos))


def guardar_credenciales(remitente: str, contrasena: str, ruta: Path | None = None) -> Path:
    destino = Path(ruta) if ruta is not None else CREDENCIALES
    # Google muestra la contraseña de aplicación en grupos de cuatro con
    # espacios; SMTP la quiere sin ellos.
    cuerpo = json.dumps(
        {"remitente": remitente.strip(), "contrasena": "".join(contrasena.split())},
    ).encode("utf-8")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(base64.b64encode(_xor(cuerpo)).decode("ascii") + "\n", encoding="ascii")
    return destino


def cargar_credenciales(ruta: Path | None = None) -> Credenciales | None:
    origen = Path(ruta) if ruta is not None else CREDENCIALES
    try:
        crudo = base64.b64decode(origen.read_text(encoding="ascii").strip())
        datos = json.loads(_xor(crudo).decode("utf-8"))
        remitente = str(datos.get("remitente", "")).strip()
        contrasena = str(datos.get("contrasena", "")).strip()
    except Exception:
        return None
    if not remitente or not contrasena:
        return None
    return Credenciales(remitente, contrasena)


def _imagen_a_bytes(imagen) -> tuple[bytes, str]:
    """PNG si cabe; si no, JPEG. Devuelve los bytes y la extensión."""
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG", optimize=True)
    if buffer.tell() <= LIMITE_PNG:
        return buffer.getvalue(), "png"
    buffer = io.BytesIO()
    imagen.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "jpg"


def preparar_reporte(
    contexto: dict[str, Any] | Callable[[], dict[str, Any]] | None,
    texto: str,
    capturas: Iterable[Any] = (),
    *,
    carpeta: Path | None = None,
    carpeta_base: Path | None = None,
) -> Path:
    """Escribe el reporte en disco y devuelve su carpeta.

    ``capturas`` son imágenes de PIL. Se codifican aquí, no en la interfaz: una
    captura de pantalla completa tarda en comprimirse y esto corre en un hilo.

    Con ``carpeta`` (un reintento) no se crea otra: se reescriben el texto y las
    capturas, que el usuario puede haber cambiado, y se conserva el contexto del
    momento del fallo, que es el que importa.
    """
    if carpeta is None or not Path(carpeta).is_dir():
        carpeta = guardar_reporte(
            contexto, nota=texto, carpeta_base=carpeta_base, con_pantalla=False,
        )
    else:
        carpeta = Path(carpeta)
        ruta = carpeta / "contexto.json"
        try:
            cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            cuerpo = {"version": APP_VERSION}
        cuerpo["nota"] = texto
        ruta.write_text(
            json.dumps(cuerpo, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        for vieja in carpeta.glob("captura_*"):
            vieja.unlink(missing_ok=True)
    (carpeta / "nota.txt").write_text(texto + "\n", encoding="utf-8")
    for numero, imagen in enumerate(list(capturas)[:MAX_CAPTURAS], start=1):
        datos, extension = _imagen_a_bytes(imagen)
        (carpeta / f"captura_{numero}.{extension}").write_bytes(datos)
    return carpeta


def preparar_y_enviar(
    contexto: dict[str, Any] | Callable[[], dict[str, Any]] | None,
    texto: str,
    capturas: Iterable[Any] = (),
    carpeta: Path | None = None,
    **opciones: Any,
) -> Path:
    """Guarda y envía. Si el envío falla, la excepción lleva ``.carpeta``."""
    carpeta = preparar_reporte(contexto, texto, capturas, carpeta=carpeta)
    try:
        enviar_reporte(carpeta, **opciones)
    except Exception as error:
        error.carpeta = carpeta  # type: ignore[attr-defined]
        raise
    return carpeta


def _asunto(texto: str) -> str:
    primera = next((linea.strip() for linea in texto.splitlines() if linea.strip()), "")
    if len(primera) > 70:
        primera = primera[:67].rstrip() + "…"
    return f"[RoleRun {APP_VERSION}] Fallo: {primera or 'sin descripción'}"


def construir_correo(carpeta: Path, remitente: str) -> EmailMessage:
    """El correo tal cual llega. Todo sale de la carpeta, así reintentar es releerla."""
    carpeta = Path(carpeta)
    try:
        contexto = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    except Exception:
        contexto = {}
    texto = str(contexto.get("nota", "") or "").strip()

    resumen = [
        ("Versión", contexto.get("version")),
        ("Cuándo", contexto.get("cuando")),
        ("Juego", contexto.get("juego")),
        ("Run", contexto.get("run")),
        ("Página", contexto.get("pagina")),
        ("Estado", contexto.get("estado_sync")),
        ("Carpeta local", carpeta.name),
    ]
    cuerpo = (
        f"{texto or '(sin descripción)'}\n\n"
        "— Datos de RoleRun —\n"
        + "\n".join(f"{nombre}: {valor}" for nombre, valor in resumen if valor not in (None, ""))
        + "\n\nEl equipo, los registros y lo que no se pudo recoger van en los adjuntos.\n"
    )

    correo = EmailMessage()
    correo["Subject"] = _asunto(texto)
    correo["From"] = remitente
    correo["To"] = DESTINATARIO
    correo.set_content(cuerpo)

    total = 0
    for captura in sorted(carpeta.glob("captura_*")):
        datos = captura.read_bytes()
        total += len(datos)
        subtipo = "jpeg" if captura.suffix.lower() in {".jpg", ".jpeg"} else "png"
        correo.add_attachment(datos, maintype="image", subtype=subtipo, filename=captura.name)

    contexto_bytes = (carpeta / "contexto.json").read_bytes() if (carpeta / "contexto.json").is_file() else b""
    if contexto_bytes:
        total += len(contexto_bytes)
        correo.add_attachment(
            contexto_bytes, maintype="application", subtype="json", filename="contexto.json",
        )

    registros = io.BytesIO()
    with zipfile.ZipFile(registros, "w", zipfile.ZIP_DEFLATED) as zip_:
        for nombre in _REGISTROS:
            ruta = carpeta / nombre
            if ruta.is_file():
                zip_.write(ruta, nombre)
    if registros.tell() > 22 and total + registros.tell() <= LIMITE_ADJUNTOS:
        correo.add_attachment(
            registros.getvalue(), maintype="application", subtype="zip", filename="registros.zip",
        )
    return correo


def enviar_reporte(
    carpeta: Path,
    *,
    credenciales: Credenciales | None = None,
    smtp_factory: Callable[..., Any] | None = None,
) -> None:
    """Manda la carpeta por correo. Lanza ``EnvioNoDisponible`` con un texto para el usuario."""
    datos = credenciales or cargar_credenciales()
    if datos is None:
        raise EnvioNoDisponible(
            "El envío por correo todavía no está configurado en esta copia de RoleRun."
        )
    correo = construir_correo(carpeta, datos.remitente)
    fabrica = smtp_factory or (
        lambda: smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PUERTO, timeout=SMTP_TIMEOUT,
            context=ssl.create_default_context(),
        )
    )
    try:
        with fabrica() as servidor:
            servidor.login(datos.remitente, datos.contrasena)
            servidor.send_message(correo)
    except smtplib.SMTPAuthenticationError as error:
        raise EnvioNoDisponible(
            "Gmail rechazó la cuenta de envío de RoleRun. Avisa al creador de la app."
        ) from error
    except smtplib.SMTPDataError as error:
        raise EnvioNoDisponible(
            "Gmail rechazó el correo (quizá las capturas pesan demasiado). Prueba con menos."
        ) from error
    except smtplib.SMTPException as error:
        # Va antes que OSError porque SMTPException hereda de él: esto es Gmail
        # contestando algo raro, no un problema de red.
        raise EnvioNoDisponible(
            f"No se pudo enviar ({type(error).__name__})."
        ) from error
    except OSError as error:
        # Sin red, Windows no da siempre el mismo error: nombre sin resolver
        # (gaierror), red inalcanzable (WinError 10051), tiempo agotado… Para
        # el usuario todo es lo mismo.
        raise EnvioNoDisponible(
            "No hay conexión a Internet o Gmail no responde."
        ) from error
