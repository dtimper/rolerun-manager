RoleRun Manager 1.12.13
========================

Barra flotante inteligente
--------------------------
- Minimizar RoleRun Manager abre siempre la barra flotante.
- Al hacer Alt+Tab, la barra solo se abre automáticamente cuando la ventana activa pertenece a un emulador reconocido. La vigilancia también detecta navegador/Discord → emulador aunque RoleRun Manager ya estuviera en segundo plano.
- Se reconocen de serie Ryujinx, Azahar, Citra, Lime3DS, DeSmuME, melonDS, Yuzu, Suyu, Sudachi, RetroArch, BizHawk y otros nombres compatibles.
- La detección usa el proceso/ventana activa de Windows; no depende del nombre concreto del juego.
- `floating_bar.json` admite una lista opcional `emulator_processes` para añadir ejecutables nuevos sin recompilar el programa.

Casillas de rol fijas
---------------------
- El orden visual de los roles ya no cambia: LÍBERO, TANQUE, ASESINO, MAGO, SUPPORT y PALADÍN.
- Al intercambiar dos Pokémon cambian sus sprites/contenido de casilla, no los rótulos de los roles.
- Dashboard, Equipo y barra flotante usan la misma lógica de casillas.
- Los Pokémon SIN ROL o procedentes de conflictos permanecen visibles en una zona de preparación aparte.

Arrastre visual
---------------
- Al pulsar y coger un Pokémon, su casilla queda vacía desde ese mismo instante.
- El sprite aparece flotando junto al cursor durante el arrastre.
- Al soltar sobre otra casilla de rol, el Pokémon destino pasa a la casilla que acaba de quedar libre.
- Si el destino está vacío, únicamente se mueve el Pokémon arrastrado.
- Los movimientos incompatibles con el nuevo rol se recalculan inmediatamente.

Volver al programa completo
---------------------------
- Si únicamente has reorganizado roles desde la barra flotante, pulsar el logo de RoleRun vuelve al Dashboard sin pedir guardar en ese momento.
- Los cambios permanecen pendientes y pueden guardarse o descartarse después desde la aplicación completa.
- Si existen otros tipos de cambios pendientes, se mantiene la confirmación de seguridad.

Motor
-----
- Esta versión no modifica el motor C#/PKHeX respecto a la 1.12.12.
