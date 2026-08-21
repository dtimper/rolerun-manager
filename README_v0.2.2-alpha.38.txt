RoleRun Manager v0.2.2-alpha.38 — Sol/Luna · semántica única de hueco PC vacío

Corrección raíz de ENVIAR AL PC:
- CAJAS PC y el writer usan ahora la misma matriz PK7 live demostrada para decidir ocupación.
- Un slot PK7 vacío puede tener bytes cifrados no-cero; species=0 con sanity/checksum válidos sigue siendo vacío.
- Se elimina la comprobación incorrecta any(raw) que hacía que la UI mostrase 2 Pokémon pero el writer rechazase el hueco 3.
- No se relajan las pruebas host==guest, identidad, preflight, verificación final ni rollback.
