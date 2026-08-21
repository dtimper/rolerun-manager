RoleRun Manager v0.2.2-alpha.19

OBJETIVO DE ESTA BUILD
- Corregir la enseñanza de MT en Sol/Luna cuando Azahar mantiene varias copias host idénticas de la party.

CAMBIO CLAVE
- Al abrir el selector de MT, RoleRun ya demuestra una única cadena party host -> mochila host -> mochila guest.
- Alpha.19 conserva la party host exacta de esa cadena y la reutiliza al escribir el PK7.
- Antes de escribir vuelve a verificar todos los PK7 no vacíos + stats sparse contra la party guest actual.
- Si la ancla deja de coincidir o cambia la sesión/proceso, se aborta sin tocar memoria.
- No se elige ninguna de las copias host por orden, PID o dirección.

RENDIMIENTO
- La enseñanza de MT evita un segundo escaneo global de FCRAM después de haber demostrado la mochila.

PRUEBA MANUAL RECOMENDADA
1. Abrir Pokémon Sol/Luna en overworld y pulsar F5.
2. Pulsar + en un hueco de movimiento.
3. Elegir una MT y enseñarla.
4. Verificar inmediatamente el movimiento dentro del juego.
5. Repetir con otra MT para comprobar que el segundo acceso reutiliza la calibración.
6. Guardar dentro del juego, reiniciar la emulación y confirmar persistencia.

REGRESIÓN AUTOMÁTICA
- 290/290 tests.
