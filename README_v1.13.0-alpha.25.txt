RoleRun Manager 1.13.0-alpha.25
=================================

MECÁNICA DE DEBILITADOS EN ORAS

- El monitor de Azahar observa PS sin usarlos para redibujar la interfaz.
- Una transición real PS > 0 -> PS = 0 registra automáticamente la baja y resta 1 vida.
- La misma baja no puede descontar dos vidas aunque el Pokémon sea revivido antes de sustituirlo.
- La baja queda persistida si se cierra RoleRun antes de elegir sustituto.
- Al volver a RoleRun se abre: "ELIGE AL SUSTITUTO DE <Pokémon>".
- La Caja 31 (última caja) queda reservada como cementerio y no aparece como fuente de sustitutos.
- El sustituto hereda el rol del Pokémon debilitado.
- La sustitución viva es atómica: sustituto -> equipo, debilitado -> primer hueco libre de Caja 31 y hueco original del sustituto -> vacío.
- Antes de escribir, RoleRun vuelve a comprobar identidades y que el hueco del cementerio siga libre. Si algo no coincide, no escribe y permite elegir otra vez.
- RoleRun no modifica main: guarda dentro de Pokémon para hacer definitivo el cambio.

NOTA DE SEGURIDAD
El selector no roba el foco mientras juegas. La muerte se registra en el momento, pero el cambio Equipo/PC se prepara cuando vuelves a RoleRun; úsalo al terminar el combate.

VALIDACIÓN
69 pruebas automáticas superadas.
