RoleRun Manager v0.2.1-alpha.15
================================

OBJETIVO
--------
Corregir la lectura de medallas de Pokémon X/Y tras la prueba real de alpha.14
con Pokémon X en AzaharPlus sin update instalado.

CAUSA AISLADA
-------------
Alpha.14 conocía como candidata barata del bloque Misc únicamente 0x08C6A6A4,
correspondiente al layout en el que Money está en 0x08C6A6AC. Sin embargo, las
referencias de RAM de Pokémon X base sitúan Money en 0x08C6A69C: el bloque Misc
queda exactamente 0x10 bytes antes, en 0x08C6A694.

Ese corrimiento era especialmente peligroso porque leer un bloque desde +0x10
puede seguir pareciendo estructuralmente plausible y dejar el byte leído como
"medallas" en 0.

CAMBIOS
-------
1. Se soportan explícitamente las dos bases documentadas de Misc X/Y:
   - v1.0: 0x08C6A694 (badges 0x08C6A6A0)
   - v1.5: 0x08C6A6A4 (badges 0x08C6A6B0)
2. La validación del bloque exige ahora coincidencia exacta del ancla de alta
   entropía usada por el descubridor dinámico. Esto impide aceptar como Misc una
   ventana desplazada 0x10 bytes.
3. El byte de medallas se interpreta como bitmask y se cuenta por bits activos.
   Ejemplo: 0x03 = 2 medallas, no 3.
4. SUBE de alpha.14 se conserva como fuente/fallback independiente.
5. No se han tocado PC, muertes, sustituciones, roles, movimientos ni batalla.

PRUEBA MANUAL
-------------
No hace falta volver a ganar una medalla.

1. Deja Pokémon X abierto en AzaharPlus con RPC activo y con la medalla que ya
   acabas de conseguir.
2. Abre RoleRun Manager v0.2.1-alpha.15.
3. Entra en X/Y.
4. Comprueba el contador MEDALLAS y el texto superior "medallas ...".

Resultado esperado para una partida con 1 medalla: MEDALLAS = 1.
Si sigue en 0, no ganes otra medalla ni cambies configuración: anota el texto
completo de estado superior y conserva el log para la siguiente diagnosis.

VALIDACIÓN AUTOMÁTICA EN EL ENTORNO DE BUILD
---------------------------------------------
- 212 tests no-GUI: OK
- 21 tests focalizados X/Y (alpha.3/7/14/15): OK
- compileall app + tests: OK
- La única prueba GUI excluida de la suite completa requiere customtkinter, que
  no está instalado en el entorno de build; el código UI no fue modificado.
