RoleRun Manager v0.2.2-alpha.41 — Sol/Luna · muertes en tiempo real dentro del combate

OBJETIVO DE ESTA BUILD
Alpha.40 ya descontaba la vida y abría la sustitución, pero lo hacía cuando la party normal de Sol/Luna volcaba el resultado al terminar el combate. Alpha.41 añade un carril de lectura INTRA-COMBATE específico de Sol/Luna para que la baja se refleje mientras el combate sigue abierto.

QUÉ DEBE OCURRIR AHORA
1. Entra en un combate con RoleRun conectado antes de comenzar.
2. Mientras tu Pokémon recibe daño normal, RoleRun no debe provocar cambios de equipo ni falsos positivos.
3. Cuando la barra de PS visible del juego llegue realmente a 0:
   - VIDAS debe bajar exactamente en 1;
   - el Pokémon debilitado debe desaparecer inmediatamente de Dashboard/barra/OBS como miembro activo;
   - NO debe abrirse todavía el selector de sustitución mientras continúe el combate.
4. Continúa/termina el combate.
5. Tras confirmar dos muestras fuera de combate, debe abrirse una sola ventana «ELIGE AL SUSTITUTO DE…».
6. El flujo Cementerio / sustituto / herencia de rol debe seguir comportándose igual que en alpha.40.

PRUEBAS DE SEGURIDAD IMPORTANTES
- Conecta RoleRun estando YA dentro de un combate con un Pokémon previamente debilitado: no debe descontar una muerte anterior a la conexión.
- Un Pokémon que ya estaba a 0 al abrir la Run tampoco debe descontar otra vida.
- La misma baja no debe cobrar más de una vida aunque haya muchos ticks a 0.
- Si la sonda intra-combate no supera su validación, RoleRun debe conservar el fallback de alpha.40 y detectar la baja al terminar el combate; nunca debe inventar HP.

EVIDENCIA TÉCNICA USADA
La causa raíz de alpha.40 era que Sol/Luna no tenía sonda de batalla: el monitor alimentaba el detector únicamente con la party PK7 normal y la etiquetaba como overworld.

Alpha.41 usa direcciones publicadas en el código abierto sumoCheatMenu para Pokémon Sun/Moon:
- estado de combate: 0x30000158 == 0x00040001;
- Max HP player:      0x30002776;
- Displayed HP player:0x30002778;
- Actual HP player:   0x30009760;
- stride por miembro: 0x330.

Ese proyecto declara soporte para Sun/Moon 1.0, 1.1 y 1.2 y utiliza esas mismas direcciones en su función de invencibilidad del equipo.

RoleRun NO confía en ellas solo por estar documentadas. En cada lectura activa exige además:
- flag de combate activo antes y después de leer HP;
- Max HP de cada miembro == Max HP de la party PK7 live ya demostrada;
- Displayed HP y Actual HP dentro de rangos físicamente válidos.
Si falla cualquier prueba, no publica health_game y conserva el fallback post-combate.

TIMING
- Fuera de combate: monitor normal ~950 ms.
- Dentro de combate: monitor ~250 ms.
- La muerte se dispara con Displayed HP == 0, es decir, cuando la barra visible del propio juego llega a cero.
- El selector sigue esperando al final del combate.

NO TOCADO
- writer ENVIAR AL PC de alpha.39;
- writer Equipo↔PC / Cementerio de alpha.40;
- ORAS;
- X/Y;
- inventario, MT, movimientos y roles.

REGRESIÓN
- 4/4 tests nuevos de la sonda SM alpha.41.
- 117/117 tests de Sol/Luna.
- 358/358 tests de la suite completa.
