RoleRun Manager 1.13.0-alpha.41

OBJETIVO DE ESTA BUILD
- Corregir el caso real observado en alpha.40: una partida con 8 medallas se quedaba en 7.
- Mantener el detector por premios de gimnasio, porque alpha.40 ya demostró que está leyendo progreso real de la partida.
- Garantizar el cambio automático 7 -> 8 en RAM al recibir la octava medalla.
- NO se implementa Prisma; los roles siguen exactamente como estaban.

FALLO RAÍZ DE ALPHA.40
Alpha.40 validaba el bolsillo MT/MO suponiendo que las siete MO de ORAS eran
IDs consecutivos 420..426. Esa suposición era incorrecta.

En ORAS los IDs de máquinas válidos incluyen:
- 420..424
- 425
- 737 (Buceo / máquina adicional de ORAS)

Por tanto, una partida avanzada que ya tuviera Buceo (#737) hacía que alpha.40
rechazara su bolsillo MT/MO REAL. La búsqueda podía entonces localizar una copia
histórica/stale de RAM anterior que todavía contenía los siete premios de los
primeros gimnasios, y RoleRun terminaba mostrando 7 aunque el juego enseñara 8.

CORRECCIÓN
- El validador de MT/MO acepta ahora el conjunto real de máquinas de ORAS.
- Se elimina el ID inventado 426 y se admite correctamente el ID 737.
- Con 7 medallas + Buceo, el bolsillo vivo se reconoce como válido y muestra 7.
- Cuando Wallace entrega MO05 (#424), la misma dirección cacheada pasa 7 -> 8
  en el siguiente ciclo de sincronización, sin guardar dentro del juego.
- Cargar un state anterior puede volver a bajar el contador porque se sigue
  leyendo la misma mochila viva, no el último main.

PREPARAR_MOTOR.BAT
NO necesitas ejecutar preparar_motor.bat para esta build si RoleRun ya abre y
lee tu partida normalmente. Alpha.41 no modifica RoleRun.SaveEngine ni el motor
.NET. La detección de medallas en tiempo real se hace por RPC directamente sobre
la RAM de Azahar.

PRUEBA MANUAL PRIORITARIA (TU PARTIDA ACTUAL)
1. NO abras preparar_motor.bat.
2. Abre Azahar y Zafiro Alfa con tu partida de 8 medallas.
3. Abre RoleRun Manager y confirma abajo: 1.13.0-alpha.41.
4. Entra en la Run y espera 2-5 segundos en el overworld.
5. MEDALLAS debe mostrar 8.
6. Arriba debe aparecer una fuente equivalente a: medallas Premios:8.

PRUEBA 7 -> 8 EN TIEMPO REAL
Cuando podamos probar desde antes de Wallace:
1. Carga un state con 7 medallas.
2. RoleRun debe mostrar 7 sin tocar ningún botón.
3. Derrota a Wallace y avanza hasta recibir la medalla/MO05.
4. Sin guardar la partida y sin reiniciar RoleRun, MEDALLAS debe pasar a 8 en
   el siguiente ciclo de sincronización.
5. Si cargas de nuevo el state de 7, el contador debe volver a 7.

VERIFICACIÓN AUTOMÁTICA
- Regresión específica: bolsillo real con Buceo (#737) es aceptado.
- Regresión específica: 7 medallas + Buceo -> 8 medallas + Buceo en la misma
  dirección viva actualiza correctamente 7 -> 8.
- Suite específica ORAS live-write/medallas: 51/51 superada antes del empaquetado.
- Suite completa no-UI: 100/100 pruebas superadas.
- compileall de app/tests/main correcto.
