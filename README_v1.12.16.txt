RoleRun Manager 1.12.16
=======================

- Nuevo render sin parpadeos en Windows mediante suspensión nativa de repintado (WM_SETREDRAW).
- Los cambios de rol, Equipo↔PC y demás refrescos ya no muestran el estado intermedio vacío de CustomTkinter.
- ENVIAR AL PC conserva el scroll antes de volver a activar el repintado: desaparece el salto visible al principio de la página.
- Se elimina la restauración diferida del scroll del flujo normal de render; la posición queda resuelta de forma síncrona durante el relayout.
- El motor C#/PKHeX no cambia respecto a 1.12.15.
