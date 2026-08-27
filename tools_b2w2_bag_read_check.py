from __future__ import annotations

"""Comprueba el lector de mochila de B2/W2 contra el juego, en solo lectura.

Usa exactamente el mismo lector y el mismo validador que usara RoleRun, no una
copia simplificada: si aqui sale algo distinto de lo que enseña el juego, es que
el lector de produccion esta mal.
"""

import json
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2LiveError, B2W2MelonDSReader
from app.boxed_metadata import item_name

SALIDA = Path("diagnostics/manual/b2w2_bag_read_latest.json")
ETIQUETAS = {
    "Items": "OBJETOS",
    "KeyItems": "OBJETOS CLAVE",
    "TMHMs": "MT y MO",
    "Medicine": "MEDICINAS",
    "Berries": "BAYAS",
}


def _texto(valor: str) -> str:
    import sys

    try:
        valor.encode(sys.stdout.encoding or "utf-8")
        return valor
    except Exception:
        return valor.encode("ascii", "replace").decode("ascii")


def main() -> None:
    lector = B2W2MelonDSReader()
    party = lector.read_party()
    mochila = lector.read_bag(party)

    print(f"melonDS PID {mochila.process_id} - mochila en 0x{mochila.guest_base:08X}")
    print()
    print("Esto es lo que RoleRun lee de tu mochila:")
    print()
    entradas = []
    for tipo, etiqueta in ETIQUETAS.items():
        propias = mochila.by_pocket(tipo)
        print(f"  --- {etiqueta} ---")
        if not propias:
            print("      (vacio)")
        for entrada in propias:
            nombre = _texto(item_name(entrada.item_id))
            print(f"      {nombre} x{entrada.quantity}")
            entradas.append({
                "bolsillo": tipo,
                "hueco": entrada.slot,
                "item_id": entrada.item_id,
                "nombre": nombre,
                "cantidad": entrada.quantity,
            })
        print()

    payload = {
        "format": "rolerun-b2w2-bag-read-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Negro 2 Espana - melonDS 1.1",
        "guest_base": f"0x{mochila.guest_base:08X}",
        "entradas": entradas,
        "note": "Lectura con el lector y el validador de produccion. Solo lectura.",
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado en: {SALIDA.resolve()}")
    print()
    print("COMPARA esta lista con la mochila del juego, bolsillo por bolsillo.")
    print("Si algo no cuadra, dime que sobra o que falta.")
    input()


if __name__ == "__main__":
    try:
        main()
    except B2W2LiveError as exc:
        print(f"\nEl lector RECHAZO la mochila: {exc}")
        print("Copiame este mensaje entero: significa que algo no cuadra.")
        input()
