RoleRun Manager v0.2.2-alpha.94 — navegación compuesta sin reconstrucción visible

Cambios principales:
- Elegir la pestaña ya visible solo cierra el menú; no reconstruye la pantalla.
- Los cambios reales conservan el último frame completo en una superficie DWM
  independiente hasta que la página nueva está totalmente compuesta.
- El fundido mezcla únicamente dos páginas completas y nunca expone widgets o
  paneles a medio crear.
- El menú lateral está precalculado a ancho fijo y se desliza cambiando solo su
  posición; deja de redimensionar todo su contenido en cada frame.
- La cadencia del drawer se mide desde la herramienta de preview y se ha
  verificado a escala 100 % y 125 %.

No se añade ninguna dirección RAM, reader, writer ni regla funcional.

Verificación automatizada: 637 tests superados.
