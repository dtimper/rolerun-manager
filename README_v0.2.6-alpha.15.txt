RoleRun Manager v0.2.6-alpha.15 — instrumentación de rendimiento

Qué cambia para ti: nada. Esta versión no corrige ni acelera todavía nada.
Añade la capacidad de medir con exactitud dónde se va el tiempo, que es el paso
previo obligatorio para poder acelerar de verdad y no a ciegas.

Con el programa arrancado de la forma habitual, la medición está apagada y no
cuesta absolutamente nada.

Si algún día quieres generar un informe de tiempos, se arranca así:

    ROLERUN_PERF=1 py -3 main.py

y RoleRun deja un archivo por día en:

    Documentos\RoleRun Manager\Logs\perf_<fecha>.jsonl

Ya hay dos cifras medidas en tu propio PC:

- Cada vez que RoleRun llama a su motor de guardados, se pagan unos 72
  milisegundos solo por arrancar el proceso, antes incluso de abrir la partida.
  Cargar una run encadena cuatro de esas llamadas.
- Guardar un evento en el historial cuesta entre 2,5 y 8 milisegundos y ese
  coste crece con el tamaño del historial.

Qué probar ahora: nada específico. Basta con usar RoleRun con normalidad y
comprobar que todo sigue funcionando exactamente igual que en alpha.14.
