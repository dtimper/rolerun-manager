RoleRun Manager v0.2.2-alpha.64 — auditoría común 3DS y prueba de Kahunas

La prueba física de alpha.63 confirmó que dos muertes consecutivas se detectan,
se comprometen y abren sus dos selectores sin minimizar RoleRun. Alpha.64 no
cambia ese carril USUM ya validado.

Esta versión corrige tres divergencias demostradas durante la auditoría de los
cuatro backends 3DS:

- un valor del main usado como fallback ya no puede reducir progreso realtime
  más nuevo; solo una fuente RAM validada puede representar una carga de state;
- los writers de utilidades SM/USUM registran el intento antes de escribir y
  verifican cualquier rollback antes de afirmar que la RAM fue restaurada;
- el PC de USUM usa personal_uu de PKHeX, no personal_sm, para derivar nivel y
  formas de especies exclusivas de UltraSol/UltraLuna.

También se guarda automáticamente una traza mínima del progreso USUM cuando
cambia el número de Kahunas o la procedencia de la lectura.

PRUEBA FÍSICA MÍNIMA

1. Reinicia RoleRun antes del combate contra el siguiente Kahuna.
2. Comprueba que el contador muestra el número actual de Grandes Pruebas.
3. Derrota al Kahuna y continúa hasta recibir el cristal Z y recuperar el control.
4. Sin guardar ni reiniciar primero, comprueba que el contador aumenta en uno.

Si no aumenta, no hagas ninguna tarea técnica. RoleRun habrá conservado la
evidencia en:

Documentos\RoleRun Manager\Logs\usum_kahuna_progress_trace_latest.jsonl
