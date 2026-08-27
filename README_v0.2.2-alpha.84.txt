RoleRun Manager v0.2.2-alpha.84 — sustitución por baja BDSP

- Habilita ELIGE AL SUSTITUTO DE para completar una baja directamente en
  Perla Reluciente 1.3.0 / Ryujinx.
- Revalida identidad, slot y HP=0 del debilitado; no actúa si el juego cambió.
- Vacía el origen PC con el PB8 canónico, conserva el debilitado exacto en la
  Caja 4 (Cementerio) e incorpora el sustituto al mismo slot de party.
- Hereda el rol observado en RAM y no confía en una selección UI desfasada.
- Comprueba las seis posiciones de party y las 1.200 posiciones PC.
- Ante cualquier fallo restaura y verifica los cuatro bloques originales.
- No añade offsets ni modifica ningún backend distinto de BDSP.

Verificación: 121 pruebas BDSP y 572 pruebas completas superadas.

Validación física: un KO + sustitución funcionó correctamente en SP 1.3.0 /
Ryujinx; el sustituto entró, el debilitado pasó a Caja 4 y se descontó una vida.

Validación física adicional: dos KO en un combate generaron exactamente dos
descuentos, dos selectores consecutivos sin minimizar, dos sustitutos en party
y dos debilitados en Caja 4.

Validación del rol: el marcador del sustituto dentro del juego coincidió con el
rol heredado mostrado por RoleRun.

Pendientes separados: OBS, historial y reconexión.
