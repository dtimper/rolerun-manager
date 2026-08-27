RoleRun Manager v0.2.2-alpha.68 — diagnóstico de la barra visible BDSP

ALPHA.67 VALIDADA

La última prueba confirma que guardar ya no detiene el monitor: RoleRun detectó
una única muerte, restó una vida, retiró el icono y abrió correctamente el
selector después del combate.

La misma prueba mostró que RoleRun se adelanta a la pantalla del juego. El HP
lógico de BDSP pasa a cero al inicio del turno, antes de que termine la
animación del golpe. No se ha añadido un retardo arbitrario.

ALPHA.68

Esta versión lee, solo para diagnóstico, la propia presentación de BDSP:

- HP que mantiene la ventana visible;
- Pokémon al que pertenece la ventana;
- si la barra está animándose;
- si queda una aplicación visual pendiente.

La estructura completa se valida por identidad IL2CPP y geometría antes de
registrarse. Esta información no cambia todavía cuándo se resta la vida; la
siguiente captura demostrará qué señal coincide realmente con el KO visible.

BDSP continúa estrictamente en modo de solo lectura.

VALIDACIÓN AUTOMATIZADA: 500 tests superados.

PRUEBA FÍSICA MÍNIMA

1. Cierra RoleRun y ábrelo de nuevo; debe mostrar alpha.68.
2. Mantén desactivado el GDB Stub y espera a «Perla Reluciente en vivo».
3. Entra en un combate salvaje simple con un Pokémon que tenga PS.
4. Deja que reciba un golpe letal y espera a que termine la animación y aparezca
   la pantalla para elegir al siguiente Pokémon.
5. Indica únicamente si RoleRun volvió a restar la vida antes de que el KO se
   viera en el juego. La traza recogerá automáticamente todo lo demás.
