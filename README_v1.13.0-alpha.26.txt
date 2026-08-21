RoleRun Manager 1.13.0-alpha.26
================================

Corrección de estabilidad para bajas automáticas + Barra Flotante.

CAMBIOS
- Cada baja pendiente puede abrir como máximo un selector de sustituto.
- La lectura de las cajas se prepara en segundo plano para evitar el congelado/blanqueo de la ventana al volver de Azahar.
- El selector de una baja no puede ser suspendido por la conmutación automática a Barra Flotante.
- Cerrar/destruir el selector no provoca reaperturas infinitas.
- La detección PS > 0 -> 0, -1 vida, sustituto y envío a la última caja se conservan.

PRUEBA RECOMENDADA
1. Abre ORAS y deja visible la Barra Flotante.
2. Haz que un Pokémon pase de PS > 0 a 0.
3. Termina el combate y vuelve a RoleRun Manager.
4. Debe aparecer una sola ventana de sustitución, con el Manager correctamente pintado.
5. Elige un sustituto y confirma que el debilitado va a la última caja y el sustituto entra con su rol.
