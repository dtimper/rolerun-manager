RoleRun Manager 1.13.0-alpha.28
================================

Estabilidad prioritaria de Barra Flotante + Cementerio fijo en Caja 4.

CAMBIOS
- Mientras la Barra Flotante está visible, las actualizaciones juego → RoleRun ya no reconstruyen Dashboard/Equipo en la ventana principal retirada. Esto evita que Windows emita un <Map> espurio y cierre la barra al cambiar de Pokémon o subir de nivel.
- Un <Map> de la ventana principal solo se interpreta como retorno real a RoleRun si la propia aplicación está en primer plano; si Azahar sigue activo, RoleRun vuelve a retirar la raíz y conserva la barra.
- Los snapshots recibidos mientras se juega quedan en memoria; OBS y la barra se actualizan al momento y la pestaña normal se reconstruye al regresar a RoleRun.
- Los cambios de nivel siguen leyéndose directamente desde la RAM viva de ORAS, pero ya no tocan el árbol gráfico de la ventana principal mientras se usa la barra.
- El Cementerio pasa a ser fijo: Caja 4. El debilitado se deposita en el primer hueco libre de esa caja.
- La Caja 4 queda excluida del selector de sustitutos para no mezclar Pokémon disponibles con el Cementerio.
- No se modifica en esta versión la detección automática de medallas ni la futura detección de combates importantes; se prioriza aislar la Barra Flotante.

PRUEBAS RECOMENDADAS
1. Con Barra Flotante activa, cambia un Pokémon por otro desde el PC del juego: la barra debe permanecer abierta y actualizar sus sprites/roles.
2. Con Barra Flotante activa, sube un nivel: la barra debe permanecer abierta; al volver a Equipo/Dashboard debe verse el nuevo nivel.
3. Provoca una baja, elige sustituto y comprueba que el debilitado aparece en la Caja 4.

VALIDACIÓN
- 84 pruebas automatizadas superadas.
