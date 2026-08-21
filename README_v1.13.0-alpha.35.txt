RoleRun Manager 1.13.0-alpha.35
==================================

CAMBIOS PRINCIPALES

1. BAJAS SIN SPOILER
- La detección de PS=0 sigue ocurriendo en cuanto ORAS la expone.
- La consecuencia visible (VIDAS -1 + ocultar el Pokémon) se retrasa 1 segundo.
- El objetivo es que la animación de debilitado se vea antes de que RoleRun revele el resultado.
- El selector de sustituto sigue esperando al final del combate.

2. MEDALLAS AUTOMÁTICAS EN ORAS
- Ya no se lee una dirección fija de medallas.
- RoleRun localiza primero la copia viva de mochila/Misc con los mismos testigos seguros que usa el escritor de inventario.
- Después lee las medallas desde esa copia calibrada y mantiene MEDALLAS sincronizado con ORAS.
- Se eliminan los botones +/− de MEDALLAS en Dashboard y Barra Flotante para ORAS.
- También se ocultan los atajos manuales de sumar/restar medalla en ORAS.
- Otros motores que todavía no tengan lectura automática conservan el control manual.

PRUEBAS RECOMENDADAS

A) Con una partida que tenga 8 medallas, abre ORAS y espera a la sincronización automática. MEDALLAS debe pasar a 8 y mostrar AUTOMÁTICO/AUTO, sin +/−.
B) Deja que un Pokémon llegue a 0 PS. RoleRun no debe adelantarse visualmente a la animación; aproximadamente 1 segundo después debe bajar una vida y ocultarlo.
C) Termina el combate. Debe abrirse una única ventana ELIGE AL SUSTITUTO DE... como en alpha.33.

Base conservada: alpha.33 (PC vivo, Caja 4 Cementerio, barra flotante estable, niveles vivos y sustitución post-combate).


Alpha.35: MEDALLAS se calibra desde el bloque Misc de ORAS de forma independiente de la mochila y usa main como fallback automático.
