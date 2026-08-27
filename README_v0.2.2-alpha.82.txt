RoleRun Manager v0.2.2-alpha.82 — tamaño de party BDSP 5↔6

- Habilita enviar al PC únicamente el último miembro de la party BDSP.
- Habilita recuperar un Pokémon del PC únicamente en el siguiente slot libre.
- Usa el contador, los seis objetos fijos y el PB8 vacío demostrados físicamente.
- Revalida party y 1.200 slots PC, hace readback y rollback de cuatro bloques.
- Rechaza miembros intermedios: no supone el algoritmo de compactación.
- Al incorporar un miembro, le asigna el primer rol RoleRun libre.

Evidencia nativa preservada:
- 6→5: 718373E0D7061BECBB804EB1DC84E3CF765D830DD258BD47DA03BEB4F070F248
- 5→6: C2AEF1C40D2D4A8C3F8BE94FCABC13A5B79EEC89A82F3B1D6DA5380B58BF0BFE

Verificación: 116 pruebas BDSP dirigidas y 567 pruebas completas superadas.

Validación física completada en SP 1.3.0 / Ryujinx: sexto→PC→sexto funciona.
Retirar un miembro intermedio permanece bloqueado hasta demostrar compactación.
