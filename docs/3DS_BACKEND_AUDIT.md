# Auditoría transversal de backends 3DS — alpha.64

Fecha: 2026-08-22. Alcance: ORAS, X/Y, Sol/Luna y UltraSol/UltraLuna sobre el
árbol de trabajo actual. Esta auditoría distingue código común de conocimiento
RAM específico; no traslada direcciones ni estructuras entre juegos.

## Resultado ejecutivo

| Hallazgo reciente | Frontera real | Alcance demostrado | Acción |
|---|---|---|---|
| El segundo selector dependía de minimizar/restaurar | Cola común de UI después del compromiso de muerte | ORAS, X/Y, SM y USUM consumen el mismo selector y `pending_faints` | Corregido una vez en `app/ui.py`; no se duplicó en backends |
| Un fallback del `main` podía reducir medallas/Kahunas más nuevas | Autoridad común UI del valor absoluto de progreso | Los cuatro adapters pueden publicar tanto RAM validada como fallback del save | Solo una procedencia RAM declarada puede reducir; el save aún puede recuperar hacia arriba |
| Un readback de utilidad fallido podía afirmar rollback sin comprobarlo | Writers Windows host de Gen 7 | Bloque duplicado y equivalente en SM y USUM | Ambos registran el intento antes del write y verifican rollback host+guest |
| El PC USUM calculaba metadatos con `personal_sm` | Parser de cajas exclusivo de USUM | Solo USUM; PKHeX distribuye `personal_uu` distinto | USUM usa el recurso correcto; SM conserva `personal_sm` |
| Base, orden de filas y ciclo de batalla de alpha.59–62 | `USUMLiveReader` antes del adapter | Solo existe evidencia física/técnica para USUM | No propagado a SM, ORAS ni X/Y |

## Evidencia de los cambios comunes

### Progreso absoluto

Los writers de los cuatro juegos declaran la procedencia del valor:

- ORAS: `Premios líderes`, `SUBE vivo`, `EventWork vivo` o `Misc vivo` frente
  a un valor recuperado del `main`;
- X/Y: `SUBE vivo X/Y` o `Misc vivo X/Y` frente a `main X/Y`;
- SM/USUM: `Z-Crystals vivos` frente a `main · Z-Crystals (fallback)`.

Antes de alpha.64, `_process_oras_badge_value()` ignoraba esa procedencia. Por
ello, tras observar progreso 1 en RAM, un fallo temporal del carril podía aplicar
el valor 0 de un save aún no guardado. La regresión reproduce exactamente
`1 → fallback main=0` y falló antes de la corrección. El contrato actual queda
cerrado por defecto: una procedencia nueva no puede reducir hasta declararse y
probarse como live. Se conserva el descenso desde RAM validada para una carga de
state o partida anterior, y el save puede elevar el contador para recuperación.

### Rollback de utilidades Gen 7

SM y USUM compartían el mismo orden defectuoso: escribían, hacían readback y
solo añadían el campo a la lista transaccional después de confirmar. Si el
readback fallaba, un rollback local atrapaba y descartaba cualquier excepción y
el mensaje afirmaba restauración. Las regresiones dejan a propósito un byte ni
original ni deseado y hacen que el segundo write sea ignorado. Antes del cambio
se afirmaba restauración; ahora ambos backends informan que el rollback no pudo
confirmarse. Una escritura confirmada conserva el flujo anterior.

### Tabla Personal de USUM

El `PKHeX.Core.dll` distribuido contiene dos recursos distintos:

- `personal_sm`: 80.724 bytes, 961 registros de 0x54;
- `personal_uu`: 81.984 bytes, 976 registros de 0x54, SHA-256
  `78A0D3BA8DE87A9D36900D88B6F56A62BC48C86D1D555573FBC25160AF7484A8`.

El parser USUM llamaba literalmente a `boxed_level("sm", ...)`. En el índice
806, `personal_sm` contiene un registro de forma de SM con crecimiento Medium
Fast, mientras `personal_uu` contiene a Blacephalon con crecimiento Slow. Para
10.000 EXP la implementación anterior devolvía nivel 21 y la tabla correcta
devuelve nivel 20. El recurso se extrae de forma reproducible mediante
`tools_extract_pkhex_personal.ps1`.

## Cambios que no deben generalizarse

Las correcciones USUM alpha.59–62 dependen de evidencia de UltraSol concreta:
base HP que cambia entre ciclos, tabla de filas permutada, PK7 de identidad por
fila y estados `0x00040001/3` y `0x00040005/6`. Ninguna de esas observaciones
demuestra el layout de SM, ORAS o X/Y.

- SM mantiene su lector propio. Exige flag activo antes/después y coincidencia
  exacta de Max HP; una permutación o discrepancia se rechaza y queda el fallback
  postcombate. No se ha demostrado físicamente que SM necesite el mapeo USUM.
- X/Y observa solo el battler activo mediante dos punteros redundantes y conserva
  identidad entre muestras. No usa la tabla USUM.
- ORAS usa sus regiones y stride Gen 6 específicos. No usa flags, PK7 ni bases
  de Gen 7.

Modificar esos backends por semejanza violaría el contrato de evidencia y podría
convertir un rechazo seguro en una muerte falsa.

## Estado por backend después de la auditoría

| Backend | Lectura/escritura y automatismos | Riesgo o validación pendiente |
|---|---|---|
| ORAS/Azahar | Party, roles, movimientos, PC, inventario/MT, batalla, muertes y medallas; recibe las correcciones comunes de UI/progreso | Mantener pruebas físicas de regresión al cambiar Azahar |
| X/Y/Azahar+Citra | Paridad realtime y correcciones comunes de UI/progreso | Operaciones RoleRun que cambian tamaño de party y ciclo de reconexión Citra siguen protegidos/pendientes |
| SM/Azahar | Party, PC, writers, batalla, muertes y Kahunas; rollback Gen 7 endurecido | No trasladar el mapeo USUM sin una reproducción SM que lo demuestre |
| USUM/Azahar | Carril de muertes y cola de selectores físicamente validados; progreso instrumentado; metadata PC corregida | Falta validar físicamente los cuatro hitos de Kahuna |

BDSP no comparte estos layouts ni dispone todavía de bridge RAM. Su fase debe
empezar desde su arquitectura Unity/PKHeX y evidencia propia, no heredando
offsets o comportamientos de 3DS.

## Addendum alpha.65 — unión interna del progreso USUM

La prueba del primer Kahuna no reveló un fallo común: SM y USUM comparten el
formato conceptual de Z-Crystals, pero las cachés y rutas ItemsOffset son propias
de cada writer. En USUM, la ruta de solo lectura demostraba
`_tm_guest_inventory_anchor` y el consumidor consultaba una caché de escritura
distinta. La corrección queda limitada a `USUMLiveWriter`; el contrato común de
autoridad alpha.64 no era la primera divergencia y no se modifica.

## Verificación automatizada

- Fronteras auditadas de UI, progreso, PC, battle baseline y writers Gen 7:
  **123 passed**.
- Suite completa del proyecto: **446 passed** en 20,46 s con
  `python -m pytest -q` sobre Windows.
- La única verificación que no puede sustituirse con esta suite es la entrega
  física del cristal Z del Kahuna en UltraSol/UltraLuna; permanece pendiente.
