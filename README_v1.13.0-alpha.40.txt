RoleRun Manager 1.13.0-alpha.40

OBJETIVO DE ESTA BUILD
- Cambiar de nuevo la fuente primaria de medallas ORAS.
- Dejar de depender para la vía principal de Misc, EventWork y SUBE.
- Reutilizar una estructura que RoleRun ya sabe leer en tiempo real: la mochila de MT/MO.
- NO se implementa Prisma; los roles siguen exactamente como estaban.

NUEVO MÉTODO: PREMIOS DE LOS LÍDERES
ORAS entrega junto con cada medalla un objeto permanente y único:
1. Petra/Roxanne      -> MT39
2. Marcial/Brawly     -> MT08
3. Erico/Wattson      -> MT72
4. Candela/Flannery   -> MT50
5. Norman             -> MT67
6. Alana/Winona       -> MT19
7. Vito y Leti/Tate+Liza -> MT04
8. Plubio/Wallace     -> MO05

Las MT/MO no se consumen al usarlas en ORAS. Por tanto, la secuencia de premios
funciona como una huella persistente del progreso de gimnasios. Si el randomizer
cambia qué MOVIMIENTO enseña cada MT pero conserva el objeto MTxx, el método
sigue siendo válido.

VALIDACIÓN ANTIFALSOS POSITIVOS
- RoleRun exige una progresión consecutiva desde la primera medalla.
- Si encuentra MT39 y MT72 pero falta MT08, rechaza esa lectura en vez de inventar 3 medallas.
- Una región completamente a cero no se interpreta como 0 medallas: se considera una lectura no válida y se prueban los fallbacks.
- El bloque candidato debe contener exclusivamente IDs reales de MT/MO de ORAS.

LOCALIZACIÓN EN RAM
1. Se prueba primero la dirección de MT/MO que ya usa RoleRun.
2. Si el sistema de mochila ya había calibrado un desplazamiento, se prueba esa copia.
3. Si no sirve, se busca dinámicamente una mochila MT/MO válida dentro de la zona de datos conocida de ORAS.
4. La dirección encontrada se cachea.
5. Si cargas un state anterior, la MISMA mochila puede bajar 8 -> 5 y RoleRun lo reflejará.

FALLBACKS
1. Premios de líderes en mochila MT/MO viva (alpha.40).
2. SUBE / historial de equipos de gimnasio (alpha.39).
3. EventWork / Received Badge (alpha.38).
4. Misc / contador.
5. Mejor dato disponible del main.

DIAGNÓSTICO
La línea verde superior mostrará, si funciona el método nuevo:
  medallas Premios:8

PRUEBA MANUAL PRIORITARIA
1. Abre Azahar con la misma partida que ya tiene las 8 medallas.
2. Abre RoleRun Manager y comprueba abajo: 1.13.0-alpha.40.
3. Entra en la Run y quédate en overworld unos segundos.
4. MEDALLAS debe pasar automáticamente a 8.
5. La línea verde debería mostrar: medallas Premios:8.

PRUEBA DE TIEMPO REAL
Si la prueba anterior funciona:
1. Carga un state anterior a un gimnasio.
2. Espera a que RoleRun muestre N medallas.
3. Gana el gimnasio y recibe su MT/MO junto con la medalla.
4. Sin guardar dentro del juego, RoleRun debe pasar N -> N+1.
5. Carga otra vez el state anterior y debe volver N+1 -> N.

COMPATIBILIDAD / LIMITACIÓN CON RANDOMIZERS
- Compatible con randomizadores que cambian el contenido/movimiento de las MT.
- Si un randomizer cambia específicamente qué OBJETO MT/MO entrega cada líder o reparte esos objetos de gimnasio por otras ubicaciones, este detector puede rechazarse y RoleRun caerá a SUBE/EventWork/Misc en lugar de forzar un dato dudoso.

VERIFICACIÓN AUTOMÁTICA EN ESTE ENTORNO
- 49/49 pruebas de ORAS live-write/medallas superadas.
- 98 pruebas no-UI de la suite completa superadas.
- El único test no ejecutable importa customtkinter, dependencia gráfica no instalada en este contenedor.
- compileall de app/tests/main correcto.
