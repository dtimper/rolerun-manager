RoleRun Manager v0.2.2-alpha.21

OBJETIVO DE ESTA BUILD
- Corregir la dependencia de alpha.20 respecto al último main para leer el PC vivo de Pokémon Sol/Luna.
- Poder descubrir las cajas actuales aunque el main guardado no contuviera ningún Pokémon en PC y los depósitos/capturas hayan ocurrido después.
- Mantener esta fase deliberadamente SOLO LECTURA hasta validar la nueva localización en una ejecución real de Azahar.

QUÉ CAMBIA RESPECTO A ALPHA.20
- Los Pokémon posicionados en las cajas del main siguen siendo testigos útiles cuando existen, pero dejan de ser un requisito.
- Si el main no aporta PK7 de caja, RoleRun intenta demostrar una imagen SAV7SM viva completa.
- Los offsets de Items/Misc/BoxLayout/BoxPokemon usados en esta prueba son offsets de ARCHIVO obtenidos de la estructura SAV7SM; nunca se tratan directamente como direcciones RAM.

CADENA DE DEMOSTRACIÓN SIN POKÉMON EN EL PC DEL MAIN
1. Se localiza la party guest ya validada y todas sus copias host exactas dentro de Azahar.
2. Para cada copia de party, RoleRun demuestra el bloque Items vivo por contenido real, igual que en las utilidades/MT ya validadas.
3. Items debe coincidir también con su dirección guest derivada y leída por RPC.
4. Desde esa base ya demostrada se comprueba que Misc aparece al MISMO delta que en SAV7SM y que host == guest.
5. Misc debe conservar suficientes ventanas estructurales exactas distribuidas respecto al main; Money puede divergir legítimamente.
6. Se comprueba BoxLayout en su delta SAV7SM, también host == guest y con evidencia estructural distribuida respecto al main.
7. Solo después se prueba BoxPokemon en su delta SAV7SM.
8. La matriz BoxPokemon completa (0x36600 bytes = 32 cajas × 30 huecos × 0xE8) se lee dos veces en host y dos veces por RPC.
9. Las cuatro lecturas deben ser idénticas y estables.
10. Cada hueco no vacío debe superar sanity/checksum/especie PK7 y poder parsearse; los huecos vacíos deben ser realmente cero.
11. Ningún Pokémon del PC puede solaparse por identidad fuerte con la party viva.
12. Si existe un Pokémon que acaba de salir de la party hacia el PC, se usa como evidencia adicional: debe aparecer en la matriz ya localizada, pero nunca se usa para inventar su posición.
13. Solo se publica el PC si queda exactamente una base guest completa demostrada.

IMPORTANTE
- Esta cadena demuestra primero la relación relativa real de varios bloques independientes en la RAM de ESA sesión. RoleRun no suma 0x4E00 a una dirección arbitraria y la da por buena.
- Si Items/Misc/BoxLayout no prueban que estamos sobre una imagen SAV7SM viva, BoxPokemon ni siquiera se acepta.
- Si hay cero o varias imágenes completas válidas, RoleRun aborta y conserva la última vista conocida.

RENDIMIENTO
- La primera calibración sigue ejecutándose fuera del hilo principal de la UI.
- Una matriz demostrada queda cacheada por sesión.
- Las siguientes sincronizaciones vuelven a leer y validar directamente la matriz completa host+guest sin repetir la localización mientras la prueba siga vigente.

SEGURIDAD DE ALPHA.21
- PC Sol/Luna continúa SOLO LECTURA.
- ENVIAR AL PC, Equipo ↔ PC y cambio de rol de Pokémon en caja siguen bloqueados en live SM.
- ORAS/X/Y no cambian de writer ni reader.

DIAGNÓSTICO
- Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json
- Si falla la nueva cadena, incluye cada ancla de party evaluada y el punto concreto que no superó: Items, Misc, BoxLayout o BoxPokemon.

PRUEBA MANUAL CLAVE
1. NO guardes ahora el PC nuevo en el main: usa precisamente el main anterior que tenía el PC vacío.
2. Abre Pokémon Sol en overworld y pulsa F5.
3. Entra en CAJAS PC de RoleRun.
4. Deben aparecer los Pokémon que existen AHORA en el PC del juego aunque no existan en el main.
5. Mueve un Pokémon entre dos huecos desde el PC del juego y comprueba que RoleRun lo refleja.
6. Deposita uno del equipo en el PC desde el juego y comprueba party + caja.
7. Saca uno del PC al equipo y comprueba ambos lados.
8. Reinicia RoleRun (sin guardar el PC nuevo en el main) y comprueba que vuelve a descubrir el estado live.
9. Si falla, adjunta sm_pc_diagnostic_latest.json.

REGRESIÓN AUTOMÁTICA
- 301/301 tests.
