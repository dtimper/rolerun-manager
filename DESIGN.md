# Principios de diseño

1. La Run es el centro del producto; el archivo de guardado y el emulador son implementaciones internas.
2. El usuario nunca debe temer perder su partida: backup, validación y escrituras vivas verificadas siempre.
3. El Real-Time Core no conoce offsets ni particularidades de juegos: consume adaptadores con un contrato común.
4. Juego y emulador se desacoplan: `Game Adapter` interpreta el estado y `Emulator Bridge` transporta memoria.
5. Toda lectura viva importante debe poder validarse, cachearse, invalidarse y diagnosticarse sin contaminar otros carriles.
6. Un fallo opcional (batalla, medallas, inventario...) no debe tumbar el equipo ni el sincronizador completo.
7. Snapshots y eventos son la fuente común para UI, OBS, automatismos, recorder y replay.
8. Ninguna función nueva debe reutilizar una dirección de otro juego por intuición; primero se calibra y prueba.
9. Cada bug reproducible debe convertirse en una regresión del Core o del adaptador correspondiente.
10. Menos clics gana, siempre que no reduzca la seguridad ni la trazabilidad.
11. Las compatibilidades vanilla de especie no son una regla de RoleRun: para enseñar una MT mandan la validez del movimiento en el juego actual, la disponibilidad de la MT y las restricciones del rol.
