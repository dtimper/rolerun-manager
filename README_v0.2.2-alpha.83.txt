RoleRun Manager v0.2.2-alpha.83 — compactación intermedia BDSP

- Permite enviar al PC cualquier miembro activo, no solo el último.
- Reproduce la compactación física demostrada: cada PB8 posterior ocupa el
  objeto fijo anterior y el último queda con el vacío canónico.
- Deposita exactamente los 344 bytes del Pokémon elegido y escribe el contador
  únicamente después de completar y verificar los datos.
- Verifica identidad, seis slots de party, 1.200 slots PC, direcciones y sesión.
- Ante cualquier fallo restaura y comprueba todos los bloques en orden inverso.
- No modifica el contrato de ningún backend distinto de BDSP.

Evidencia física nativa:
diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_224902.json
SHA-256 B65F6B7812314955CD090DB2AA6B68748402DDF17D4ADEA858D2A896254AEFCE

Verificación: 117 pruebas BDSP y 568 pruebas completas superadas.

Validación física: la retirada intermedia iniciada desde RoleRun se reflejó
correctamente en SP 1.3.0 / Ryujinx y en la aplicación.
