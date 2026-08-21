RoleRun Manager 1.12.23
========================

Novedad principal:
- Nuevo render de doble buffer real para evitar el parpadeo al cambiar roles y ejecutar otras acciones que refrescan la página.
- RoleRun Manager construye la vista nueva detrás de la actual y las intercambia solo cuando geometría y scroll están listos.
- Ya no se usa una captura de pantalla ni se congela el HWND principal.
- La barra flotante permanece independiente y conserva su flujo de withdraw/deiconify.
- Si el render nuevo falla, la vista anterior permanece visible.

Comprobación recomendada:
1. Abre Equipo y desplázate hasta una posición intermedia o inferior.
2. Cambia un rol y prueba también un intercambio mediante arrastrar y soltar.
3. Comprueba que no hay flash y que el scroll permanece en el mismo punto.
4. Abre la barra flotante, reorganiza roles y vuelve al Dashboard.
5. Regresa a Equipo y repite un cambio de rol para comprobar que el render sigue estable.

Motor C#/PKHeX: sin cambios respecto a 1.12.22.
