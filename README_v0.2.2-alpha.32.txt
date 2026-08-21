RoleRun Manager v0.2.2-alpha.32

OBJETIVO DE ESTA BUILD
Mantener el diagnóstico seguro del slot runtime completo de alpha.31 y corregir la regresión que impedía entrar en CAJAS PC cuando el último main ya contenía Pokémon en cajas pero estaba desfasado respecto al PC vivo.

QUÉ CAMBIA
- CAJAS PC de Sol/Luna intenta primero la matriz live que ya fue validada físicamente en Azahar desde alpha.25.
- La dirección live sigue tratándose solo como candidata: RoleRun exige matriz completa 32×30, doble lectura estable y coincidencia byte a byte host == guest antes de publicar nada.
- El main ya no puede bloquear el PC vivo por contener PK7 antiguos. Se usa únicamente como evidencia adicional/fallback.
- No se vuelve a habilitar el swap Equipo ↔ PC desde RoleRun. Sigue bloqueado hasta demostrar qué bytes runtime adicionales necesita Pokémon Sol.
- Se conserva el diagnóstico de los 6 slots completos de party (6 × 0x1E4).

PRUEBA RECOMENDADA
1. Abre alpha.32 con Pokémon Sol en overworld y pulsa F5.
2. Entra en CAJAS PC. Deben aparecer los Pokémon reales sin el error de “matriz de cajas dentro del main”.
3. Desde el PC DEL PROPIO JUEGO, haz una sustitución 1↔1 (por ejemplo Decidueye ↔ Ledyba).
4. Espera a que RoleRun refleje el cambio.
5. Haz el cambio inverso o una segunda sustitución.
6. Envía los dos archivos timestamped más recientes:
   Documentos\RoleRun Manager\Logs\sm-party-runtime-*.json
   Si solo existe uno, envía también:
   Documentos\RoleRun Manager\Logs\sm_party_runtime_transition_latest.json

IMPORTANTE
No guardes ningún estado falso procedente de alpha.30. Alpha.32 no escribe Equipo↔PC desde RoleRun; solo observa sustituciones reales hechas por Pokémon Sol para construir el writer correcto sobre evidencia byte a byte.
