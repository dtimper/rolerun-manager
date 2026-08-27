RoleRun Manager v0.2.2-alpha.78 — intercambio Equipo ↔ PC BDSP 1↔1

- CAMBIAR CON PC aplica al instante el intercambio en Perla Reluciente 1.3.0.
- Comprueba dos capturas completas, coordenadas e identidades antes de escribir.
- Intercambia el PB8 completo: 328 bytes de núcleo + 16 de datos calculados.
- El Pokémon entrante hereda el rol de la plaza saliente antes del cifrado.
- Verifica ambas identidades, HP/nivel y rol después de escribir.
- Si falla cualquier fase, restaura y verifica party core, party calc y caja.
- Añadir o retirar Pokémon continúa bloqueado hasta demostrar los contratos de
  tamaño de party y vacío runtime; no existe fallback a un cambio diferido.

Pendiente de validación física en SP 1.3.0 / Ryujinx.

Verificación: 60 pruebas BDSP dirigidas y 555 pruebas completas superadas.
