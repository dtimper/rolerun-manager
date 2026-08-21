RoleRun Manager v0.2.2-alpha.12

Objetivo de esta build:
- Mantener intacta la lectura SM ya validada.
- Resolver la limitación de WriteMemory de Azahar sobre NEW_LINEAR_HEAP sin GDB ni offsets host supuestos.
- Si el alias LINEAR_HEAP no coincide (hecho demostrado en alpha.11), localizar en Windows la copia viva de la party dentro del proceso Azahar por coincidencia exacta de todos los PK7, stats y stride.
- Escribir únicamente tras obtener una única coincidencia; releer por host y por RPC canonical; rollback por la misma ruta si falla.
- Movimientos/MT/PC/inventario continúan bloqueados hasta validar roles.
