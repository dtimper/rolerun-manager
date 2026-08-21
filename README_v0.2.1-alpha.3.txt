RoleRun Manager 0.2.1-alpha.3
================================

OBJETIVO DE ESTA ALPHA
----------------------
Esta es la primera prueba real de reutilización del Real-Time Core: Pokémon X/Y
se incorpora como segundo juego sobre Azahar sin duplicar la infraestructura de
snapshots, eventos, diagnóstico, replay, reconexión y publicación de la UI.

X/Y EN TIEMPO REAL — DISPONIBLE EN ALPHA.3
-------------------------------------------
- Enlace automático con Pokémon X o Pokémon Y abiertos en Azahar RPC.
- Lectura viva y estable del equipo.
- Niveles y PS de la party overworld.
- Lectura/escritura de los seis marcadores de rol.
- Escritura verificada de movimientos del equipo.
- Monitor juego -> RoleRun para roles, movimientos, niveles y composición visible.
- Primer detector automático de medallas X/Y mediante el bloque Misc vivo, con
  fallback al main si la RAM todavía no puede localizarse.
- Mismo RealTimeSnapshot, Event Engine, diagnóstico y replay que ORAS.
- Integración visual/OBS a través del mismo flujo común.

TODAVÍA PENDIENTE EN X/Y
------------------------
La alpha.3 NO pretende fingir que todo X/Y está calibrado. Permanecen fuera de
la escritura/lectura RPC específica de X/Y hasta disponer de bloques validados:
- PC vivo y reconciliación completa Equipo <-> PC.
- Mochila MT/MO viva y selector de MT en tiempo real.
- Escritura viva de inventario.
- Sonda específica de batalla (la party overworld sigue siendo observable).
- Sustituciones estructurales y flujo completo de bajas con PC vivo.

Estas capacidades siguen funcionando en ORAS como antes. En X/Y las rutas no
calibradas se rechazan de forma explícita: no se adivinan direcciones ni se
mezclan silenciosamente con las de ORAS.

CÓMO PROBAR X/Y
---------------
1. Abre Pokémon X o Pokémon Y en Azahar y asegúrate de tener RPC activado.
2. Abre RoleRun Manager y entra en una Run X/Y con su main configurado.
3. Espera unos segundos. Arriba debería aparecer "X/Y en vivo".
4. Comprueba que los seis Pokémon/niveles/roles coinciden con el juego.
5. Cambia un rol desde RoleRun. Debe cambiar el marcador correspondiente en X/Y.
6. Haz un drafteo normal y sustituye un movimiento del equipo. Debe aplicarse en
   la RAM viva y confirmarse sin modificar main.
7. Cambia un marcador/rol desde el juego y comprueba que RoleRun lo recoge.
8. Comprueba el contador de medallas. En la línea de estado puede aparecer
   "medallas MiscXY:N" si se localizó la copia viva, o "mainXY:N" como fallback.
9. En CONFIGURACIÓN -> REAL-TIME CORE, inicia una grabación, realiza uno o dos
   cambios y genera un paquete. ABRIR REPLAY debe reconocer `xy-azahar-rpc`.

SI ALGO FALLA EN X/Y
--------------------
No hace falta repetir pruebas a ciegas. Ve a CONFIGURACIÓN -> REAL-TIME CORE,
inicia una grabación, reproduce el problema durante unos segundos y usa
"DETENER Y GENERAR PAQUETE". Ese ZIP contiene snapshots, eventos, diagnóstico y
los bloques RAM pequeños que el adaptador ya haya validado.

ORAS
----
ORAS permanece sobre su adaptador propio y conserva el comportamiento validado
de 0.2.1-alpha.2: medallas, MT, PC, bajas, sustituciones, inventario y demás
funciones vivas no se han migrado a offsets X/Y ni se han degradado.

No necesitas ejecutar preparar_motor.bat por el Real-Time Core si ya tenías el
motor de la versión anterior preparado. El motor .NET sigue siendo necesario
para abrir/interpretar los archivos de guardado como hasta ahora.
