RoleRun Manager 0.2.1-alpha.7
=================================

Objetivo de esta build
----------------------
Cerrar dos automatismos X/Y en tiempo real sobre Azahar y Citra:
- medallas vivas (incluido el cambio 0 -> 1 sin guardar),
- detección de debilitados durante combate y sustitución posterior.

Cambios principales
-------------------
1. Medallas X/Y live
   - Citra deja de usar el main como fuente temporal.
   - Se prueba primero el bloque Misc vivo conocido de X/Y, pero solo se acepta
     si valida contra la huella del main de esta Run.
   - Si no valida, LiveBlockResolver conserva el descubrimiento dinámico y el
     fallback seguro al guardado.

2. Sonda de batalla X/Y
   - Lee los pares redundantes de PS del jugador/rival.
   - Solo publica PS del Pokémon activo cuando puede atribuirlo sin ambigüedad.
   - Una bajada PS>0 -> 0 entra en el flujo común: delay visual, -1 vida y
     selector de sustituto al terminar el combate.
   - Si no puede atribuir PS dentro del combate, el fallback overworld sigue
     detectando la baja al terminar sin falsos positivos.

3. Sustitución de debilitados X/Y
   - X/Y permite ahora replace-fainted en la misma ruta transaccional Gen6 ya
     usada por ORAS: sustituto al equipo, debilitado al Cementerio (Caja 4).
   - Requiere la ROM X/Y configurada para reconstruir las estadísticas de party.

4. Mochila MT/MO X/Y
   - Tamaño corregido a 0x1A8 (106 registros).
   - Dirección conocida X/Y se usa como candidata validada antes del barrido.

Prueba recomendada delante del primer gimnasio
----------------------------------------------
A) Antes de combatir: MEDALLAS debe marcar 0 y X/Y debe seguir en vivo.
B) Durante el gimnasio: deja debilitarse un Pokémon si quieres probar bajas.
   RoleRun debe restar la vida tras el pequeño delay y NO abrir el selector
   hasta detectar que el combate ha terminado.
C) Al salir del combate elige sustituto. El debilitado debe ir a Caja 4 y el
   sustituto heredar el rol.
D) Tras recibir la medalla, sin guardar, el contador debe pasar 0 -> 1.
E) Abre después el selector MT: la MT recibida debería aparecer si el Pokémon
   seleccionado puede aprenderla y sus reglas de rol la permiten.

No es necesario ejecutar preparar_motor.bat.
