"""Configura la cuenta Gmail que envía los reportes de REPORTAR FALLO.

Uso (desde la carpeta de RoleRun):

    python tools/configurar_correo_de_reportes.py

Pide el correo de la cuenta de envío y su contraseña de aplicación, manda un
correo de prueba a ``DESTINATARIO`` y, solo si llega a enviarse, guarda
``data/reporte_correo.dat``. Esa cuenta tiene que ser una creada solo para
esto: el archivo está ofuscado, no cifrado. Es solo el respaldo local (está en
``.gitignore`` y no se publica); el programa publicado envía por el buzón de
``tools/buzon_de_reportes.gs``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.envio_de_reportes import (  # noqa: E402
    CREDENCIALES,
    DESTINATARIO,
    Credenciales,
    EnvioNoDisponible,
    enviar_reporte,
    guardar_credenciales,
    preparar_reporte,
)


def main() -> int:
    print("Cuenta Gmail que ENVÍA los reportes (no la tuya personal).")
    remitente = input("Correo de envío: ").strip()
    # Visible a propósito: `getpass` no muestra nada y, en algunas terminales
    # de Windows, tampoco recoge lo pegado con Ctrl+V. Parecía que no escribía.
    contrasena = "".join(
        input("Contraseña de aplicación (16 letras, con o sin espacios): ").split()
    )
    if not remitente or len(contrasena) != 16:
        print(
            f"Hace falta el correo y la contraseña de aplicación de 16 letras "
            f"(se han recibido {len(contrasena)})."
        )
        return 1

    print(f"Enviando un correo de prueba a {DESTINATARIO}…")
    with tempfile.TemporaryDirectory() as temporal:
        carpeta = preparar_reporte(
            {"pagina": "configuración"},
            "Correo de prueba: el envío de reportes de RoleRun ya funciona.",
            carpeta_base=Path(temporal),
        )
        try:
            enviar_reporte(carpeta, credenciales=Credenciales(remitente, contrasena))
        except EnvioNoDisponible as error:
            print(f"No se pudo: {error}")
            causa = error.__cause__
            if causa is not None:
                print(f"Detalle técnico: {type(causa).__name__}: {causa}")
            return 1

    ruta = guardar_credenciales(remitente, contrasena)
    print(f"Listo. Credenciales guardadas en {ruta.relative_to(CREDENCIALES.parent.parent)}.")
    return 0


if __name__ == "__main__":
    codigo = main()
    # Abierto con doble clic, la consola se cerraba al acabar y no daba tiempo
    # a leer si había funcionado.
    input("\nPulsa Enter para cerrar.")
    raise SystemExit(codigo)
