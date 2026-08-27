RoleRun Manager v0.2.2-alpha.69 — KO BDSP sincronizado con la barra visible

CAUSA RAÍZ DEMOSTRADA

La captura alpha.68 demuestra que BDSP resolvió el HP lógico de Shuppet de
12 a 0 al inicio del turno, pero su ventana visible continuó mostrando 12/58.
La animación hacia cero no empezó hasta 6,167 segundos después y terminó a los
6,690 segundos. RoleRun publicaba directamente el cero lógico y por eso se
adelantaba al juego.

CORRECCIÓN ALPHA.69

Solo para BDSP, RoleRun conserva el último HP positivo cuando llega ese cero
anticipado. Publica la muerte después de observar en la ventana del mismo
Pokémon que la barra está animando hacia cero y que la animación ha terminado.

No se ha añadido ningún retraso fijo. La comprobación exige una ventana jugador
única, el mismo PokeID y el mismo HP máximo. Si la presentación no está
disponible o es ambigua, RoleRun no cobra una muerte anticipada y conserva la
convergencia segura posterior de la party.

No se han modificado otros juegos ni se ha habilitado ninguna escritura BDSP.

VALIDACIÓN AUTOMATIZADA: 503 tests superados.

VALIDACIÓN FÍSICA COMPLETADA

El usuario confirmó en Perla Reluciente 1.3.0/Ryujinx 1.3.3 que RoleRun ya no
se adelanta: la vida y el icono cambian cuando la barra llega a cero y termina
su animación, una sola vez. El selector postcombate continúa funcionando. Una
segunda prueba reordenó dos Pokémon desde el juego y RoleRun conservó
correctamente identidad, icono y rol.

PRUEBA FÍSICA UTILIZADA

1. Cierra la versión anterior de RoleRun y abre de nuevo el programa; debe
   mostrar alpha.69.
2. Mantén desactivado el GDB Stub y espera a «Perla Reluciente en vivo».
3. Entra en un combate salvaje simple con un Pokémon que tenga PS.
4. Deja que reciba un golpe letal y observa el juego y RoleRun.
5. RoleRun no debe restar la vida ni retirar el icono al inicio del turno. Debe
   hacerlo una sola vez cuando la barra del juego haya llegado a cero y haya
   terminado su animación.
6. Termina el combate y confirma que el selector de sustituto sigue apareciendo.
