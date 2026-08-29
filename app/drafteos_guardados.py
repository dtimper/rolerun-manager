"""Drafteos tirados y todavía no enseñados.

Antes, un drafteo solo tenía un final: elegías el movimiento y a continuación el
hueco que sustituía, en la misma sentada. Ahora hay dos, y este módulo guarda el
segundo: **quedárselo para después**.

## Guardar cuesta un drafteo

Esto no es una decisión estética. La tirada se puede repetir gratis tantas veces
como quieras —eso ya era así— y lo que cuesta el drafteo es **quedarse con un
resultado**. Si guardar fuera gratis, la jugada obvia sería tirar, guardarse las
cuatro opciones y volver a tirar: el contador dejaría de significar nada. Se
paga al guardar, y por eso enseñarlo más tarde ya no vuelve a cobrar.

## A quién se le puede enseñar después

Al rol, no a la especie. Un drafteo sale del conjunto de un rol, así que
cualquier Pokémon que tenga ese rol puede aprenderlo; el Pokémon para el que se
tiró se recuerda solo para poder decir de dónde salió.

Este módulo no toca la interfaz ni el guardado: son las reglas y nada más, para
poder probarlas enteras.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Versión del formato guardado en `config.json`. Si algún día cambia la forma
#: de un drafteo, esto permite migrarlo sin adivinar.
FORMATO = 1


def nuevo_drafteo(
    *,
    move_id: int,
    move: str,
    role: str,
    pool_key: str,
    categoria: str = "",
    origen_identidad: str = "",
    origen_nombre: str = "",
    cuando: str = "",
) -> dict[str, Any]:
    """Un drafteo guardado, listo para escribirse en `config.json`."""
    return {
        "formato": FORMATO,
        "move_id": int(move_id),
        "move": str(move),
        "role": str(role),
        "pool_key": str(pool_key),
        "categoria": str(categoria),
        "origen_identidad": str(origen_identidad),
        "origen_nombre": str(origen_nombre),
        "cuando": str(cuando),
    }


def clave(drafteo: dict[str, Any]) -> tuple[int, str, str]:
    """Identifica un guardado sin depender de un contador propio.

    Dos tiradas del mismo movimiento para el mismo rol son intercambiables: da
    igual cuál de las dos se enseñe.
    """
    return (
        int(drafteo.get("move_id", 0) or 0),
        str(drafteo.get("role", "")),
        str(drafteo.get("pool_key", "")),
    )


def normalizar(crudos: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Se queda solo con lo que tiene forma de drafteo.

    `config.json` lo puede haber escrito una versión anterior o una mano ajena.
    Un guardado corrupto no puede impedir abrir la Run.
    """
    limpios: list[dict[str, Any]] = []
    for crudo in tuple(crudos or ()):
        if not isinstance(crudo, dict):
            continue
        try:
            move_id = int(crudo.get("move_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if move_id <= 0 or not str(crudo.get("move", "")).strip():
            continue
        limpios.append(nuevo_drafteo(
            move_id=move_id,
            move=str(crudo.get("move", "")),
            role=str(crudo.get("role", "")),
            pool_key=str(crudo.get("pool_key", "")),
            categoria=str(crudo.get("categoria", "")),
            origen_identidad=str(crudo.get("origen_identidad", "")),
            origen_nombre=str(crudo.get("origen_nombre", "")),
            cuando=str(crudo.get("cuando", "")),
        ))
    return limpios


def anadir(guardados: Iterable[Any] | None, drafteo: dict[str, Any]) -> list[dict[str, Any]]:
    """Añade uno. Se permiten repetidos: cada tirada costó su drafteo."""
    return [*normalizar(guardados), dict(drafteo)]


def quitar_uno(
    guardados: Iterable[Any] | None, drafteo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Retira **una** copia. Con dos tiradas iguales, enseñar una deja la otra."""
    objetivo = clave(drafteo)
    restantes: list[dict[str, Any]] = []
    quitado = False
    for guardado in normalizar(guardados):
        if not quitado and clave(guardado) == objetivo:
            quitado = True
            continue
        restantes.append(guardado)
    return restantes


def puede_aprenderlo(drafteo: dict[str, Any], rol_del_pokemon: str) -> bool:
    """Al rol, no a la especie: es la regla del formato."""
    rol = str(drafteo.get("role", "")).strip().casefold()
    if not rol:
        # Un guardado antiguo sin rol no puede reclamar ninguno. Antes que
        # inventárselo, se ofrece a todos y decide quien enseña.
        return True
    return rol == str(rol_del_pokemon or "").strip().casefold()


def ordenados(guardados: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Por rol y por nombre, que es como se buscan en una lista."""
    return sorted(
        normalizar(guardados),
        key=lambda item: (str(item.get("role", "")), str(item.get("move", ""))),
    )


def cuantos(guardados: Iterable[Any] | None) -> int:
    return len(normalizar(guardados))
