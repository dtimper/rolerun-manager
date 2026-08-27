RoleRun Manager v0.2.2-alpha.77 — medallas BDSP en tiempo real

- Lee el array vivo PlayerWork.SaveData.systemFlags de Perla Reluciente 1.3.0.
- Cuenta exclusivamente los ocho flags que usa FlagWork.BadgeCount en el juego.
- Valida raíz, longitud 1000, booleanos y doble lectura antes de publicar 0–8.
- El carril de progreso es opcional: un fallo no invalida equipo, PC ni batalla.
- La UI compromete el valor absoluto antes de cualquier retorno por cambios de party.
- MEDALLAS pasa a ser automático para BDSP y mantiene Run, UI y OBS sincronizados.

Evidencia física: el Ryujinx activo publicó 2 medallas y coincidió con los ocho
flags y el contador redundante del guardado. El usuario confirmó que alpha.77
sincronizó correctamente esas dos medallas al arrancar. La transición de una
nueva medalla 2→3 y OBS quedan pendientes de validación física.

Verificación: 107 pruebas dirigidas y 552 pruebas completas superadas.
