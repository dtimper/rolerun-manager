"""REPORTAR FALLO: el reporte se guarda siempre y luego se manda por correo.

Lo que se fija aquí:

- **guardar antes de enviar**: sin Internet, o con la cuenta mal, el reporte
  sigue en disco y el error dice dónde;
- **reintentar no duplica**: se reutiliza la carpeta y se reescriben el texto
  y las capturas, que el usuario puede haber cambiado;
- **el correo lleva lo que hace falta**: texto, capturas, contexto y registros;
- **los atajos no se comen lo que se escribe**: con el reporte abierto, un 7
  del teclado numérico va al mensaje, no suma una vida.
"""

from __future__ import annotations

import json
import smtplib
import socket
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.envio_de_reportes import (  # noqa: E402
    DESTINATARIO,
    Credenciales,
    EnvioNoDisponible,
    cargar_credenciales,
    construir_correo,
    enviar_reporte,
    guardar_credenciales,
    preparar_reporte,
    preparar_y_enviar,
)

CREDS = Credenciales("envio@example.com", "abcdabcdabcdabcd")


class _SmtpFalso:
    def __init__(self, fallo: Exception | None = None) -> None:
        self.fallo = fallo
        self.login_con: tuple[str, str] | None = None
        self.enviados: list = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def login(self, usuario, contrasena):
        self.login_con = (usuario, contrasena)
        if isinstance(self.fallo, smtplib.SMTPAuthenticationError):
            raise self.fallo

    def send_message(self, correo):
        if self.fallo is not None:
            raise self.fallo
        self.enviados.append(correo)


def _imagen(ancho=40, alto=30, color=(200, 30, 30)):
    return Image.new("RGB", (ancho, alto), color)


def test_las_credenciales_no_quedan_en_texto_plano(tmp_path) -> None:
    ruta = guardar_credenciales("envio@example.com", "abcd efgh ijkl mnop", tmp_path / "c.dat")

    crudo = ruta.read_text(encoding="ascii")
    assert "envio@example.com" not in crudo
    assert "abcdefghijklmnop" not in crudo
    assert cargar_credenciales(ruta) == Credenciales("envio@example.com", "abcdefghijklmnop")


def test_sin_credenciales_no_hay_envio_pero_si_mensaje(tmp_path, monkeypatch) -> None:
    import app.envio_de_reportes as modulo

    monkeypatch.setattr(modulo, "CREDENCIALES", tmp_path / "no_existe.dat")
    assert cargar_credenciales() is None
    carpeta = preparar_reporte({}, "algo", carpeta_base=tmp_path)
    smtp = _SmtpFalso()

    with pytest.raises(EnvioNoDisponible, match="no está configurado"):
        enviar_reporte(carpeta, smtp_factory=smtp)
    assert smtp.login_con is None


def test_el_reporte_se_guarda_con_texto_y_capturas(tmp_path) -> None:
    carpeta = preparar_reporte(
        {"juego": "Perla Reluciente", "pagina": "team"},
        "Se congeló al dar la MT",
        [_imagen(), _imagen(color=(0, 0, 255))],
        carpeta_base=tmp_path,
    )

    contexto = json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))
    assert contexto["nota"] == "Se congeló al dar la MT"
    assert contexto["juego"] == "Perla Reluciente"
    assert (carpeta / "nota.txt").read_text(encoding="utf-8").strip() == "Se congeló al dar la MT"
    assert sorted(p.name for p in carpeta.glob("captura_*")) == ["captura_1.png", "captura_2.png"]
    # Las capturas de F8 son otra cosa: aquí no se hace una de toda la pantalla.
    assert not (carpeta / "pantalla.png").exists()


def test_una_captura_enorme_viaja_en_jpeg(tmp_path, monkeypatch) -> None:
    import app.envio_de_reportes as modulo

    monkeypatch.setattr(modulo, "LIMITE_PNG", 10)
    carpeta = preparar_reporte({}, "x", [_imagen(200, 200)], carpeta_base=tmp_path)

    assert [p.name for p in carpeta.glob("captura_*")] == ["captura_1.jpg"]


def test_reintentar_reutiliza_la_carpeta_y_reescribe_lo_cambiado(tmp_path) -> None:
    primera = preparar_reporte(
        {"juego": "Rubí Omega"}, "texto viejo", [_imagen(), _imagen()], carpeta_base=tmp_path,
    )
    segunda = preparar_reporte(
        {"juego": "OTRO"}, "texto nuevo", [_imagen()], carpeta=primera, carpeta_base=tmp_path,
    )

    assert segunda == primera
    assert len([p for p in tmp_path.iterdir() if p.name.startswith("bug_")]) == 1
    contexto = json.loads((segunda / "contexto.json").read_text(encoding="utf-8"))
    assert contexto["nota"] == "texto nuevo"
    # El contexto es el del instante del fallo, no el del reintento.
    assert contexto["juego"] == "Rubí Omega"
    assert [p.name for p in segunda.glob("captura_*")] == ["captura_1.png"]


def test_el_correo_lleva_texto_capturas_contexto_y_registros(tmp_path) -> None:
    carpeta = preparar_reporte(
        {"juego": "Luna", "run": "Mi run"},
        "Primera línea del fallo\nY más detalle debajo",
        [_imagen()],
        carpeta_base=tmp_path,
    )
    (carpeta / "tiempos.jsonl").write_text('{"t": 1}\n', encoding="utf-8")

    correo = construir_correo(carpeta, "envio@example.com")

    assert correo["To"] == DESTINATARIO
    assert correo["From"] == "envio@example.com"
    assert "Primera línea del fallo" in correo["Subject"]
    cuerpo = correo.get_body(("plain",)).get_content()
    assert "Y más detalle debajo" in cuerpo
    assert "Juego: Luna" in cuerpo and "Run: Mi run" in cuerpo
    adjuntos = [parte.get_filename() for parte in correo.iter_attachments()]
    assert adjuntos == ["captura_1.png", "contexto.json", "registros.zip"]


def test_sin_registros_no_se_adjunta_un_zip_vacio(tmp_path, monkeypatch) -> None:
    import app.reporte_de_bugs as bugs

    monkeypatch.setattr(bugs, "LOG_DIR", tmp_path / "sin_logs")
    carpeta = preparar_reporte({}, "x", carpeta_base=tmp_path / "bugs")

    adjuntos = [p.get_filename() for p in construir_correo(carpeta, "a@b.c").iter_attachments()]
    assert "registros.zip" not in adjuntos


def test_enviar_hace_login_y_manda(tmp_path) -> None:
    smtp = _SmtpFalso()
    carpeta = preparar_reporte({}, "hola", [_imagen()], carpeta_base=tmp_path)
    enviar_reporte(carpeta, credenciales=CREDS, smtp_factory=smtp)

    assert smtp.login_con == (CREDS.remitente, CREDS.contrasena)
    assert len(smtp.enviados) == 1


@pytest.mark.parametrize(
    "fallo, texto",
    [
        (smtplib.SMTPAuthenticationError(535, b"no"), "rechazó la cuenta"),
        (socket.gaierror("sin red"), "conexión a Internet"),
        (TimeoutError(), "conexión a Internet"),
        # Red caída con el nombre ya resuelto: Windows da un OSError genérico.
        (OSError(10051, "red inalcanzable"), "conexión a Internet"),
        (ConnectionRefusedError(), "conexión a Internet"),
        (smtplib.SMTPServerDisconnected("se cortó"), "SMTPServerDisconnected"),
        (smtplib.SMTPDataError(552, b"grande"), "pesan demasiado"),
    ],
)
def test_los_fallos_de_envio_se_explican_y_dicen_la_carpeta(tmp_path, monkeypatch, fallo, texto) -> None:
    import app.reporte_de_bugs as bugs

    monkeypatch.setattr(bugs, "BUGS_DIR", tmp_path)
    with pytest.raises(EnvioNoDisponible, match=texto) as error:
        preparar_y_enviar({}, "hola", [], credenciales=CREDS, smtp_factory=_SmtpFalso(fallo))

    carpeta = error.value.carpeta
    assert carpeta.is_dir() and carpeta.parent == tmp_path
    assert json.loads((carpeta / "contexto.json").read_text(encoding="utf-8"))["nota"] == "hola"


def test_con_el_reporte_abierto_los_atajos_globales_se_apagan() -> None:
    from app.ui import RoleRunManager

    falso = type("Falso", (), {})()
    falso._reporte_de_fallo = object()
    falso._foreground_is_supported_emulator = lambda: True
    falso._foreground_belongs_to_this_process = lambda: True
    assert RoleRunManager._foreground_allows_global_hotkeys(falso) is False

    falso._reporte_de_fallo = None
    assert RoleRunManager._foreground_allows_global_hotkeys(falso) is True


def test_el_boton_se_llama_reportar_fallo() -> None:
    import inspect

    from app import ui

    fuente = inspect.getsource(ui.RoleRunManager._show_floating_menu_home)
    assert "REPORTAR FALLO" in fuente
    assert "GUARDAR FALLO" not in fuente
