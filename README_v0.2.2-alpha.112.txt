RoleRun Manager v0.2.2-alpha.112

- Atrás conserva el cursor de origen en Equipo/PC y MT; en los pasos
  posteriores de Drafteos vuelve al paso 1.
- Desde el extremo izquierdo se puede seleccionar y abrir el menú lateral.
- La ficha muestra stat final, stat base, IV y EV para cada característica.
- La navegación procesa ráfagas rápidas sin reconstruir la ficha en cada tecla,
  y el mando repite el D-pad de forma controlada al mantenerlo pulsado.
- El selector visual utiliza el marco y fondo dorados propios de RoleRun.

Validación visual real: cinco entradas separadas 10 ms sin pérdidas y stats
base BDSP visibles desde la tabla Personal validada.

Baseline: 713 tests superados con `python -m pytest -q`.
