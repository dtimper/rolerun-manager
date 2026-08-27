# Rediseño integral de RoleRun Manager — índice

Esta carpeta contiene exclusivamente análisis y propuesta. No implementa la
nueva interfaz ni cambia readers, writers, memoria, reglas, realtime, saves o
comportamiento.

1. [Auditoría del estado actual](01_current_state_audit.md)
2. [Propuesta maestra](02_redesign_master_proposal.md)
3. [Matriz de paridad funcional](03_functional_parity_matrix.md)
4. [Hoja de ruta segura](04_safe_implementation_roadmap.md)
5. [Cuestiones abiertas de producto](05_open_questions.md)
6. [Registro priorizado de riesgos y decisiones](06_risk_register.md)

## Resultado recomendado

Modernizar de forma incremental dentro de CustomTkinter, comenzando por tokens,
view models y una shell de solo lectura. Conservar la UI clásica tras un feature
flag. Migrar Equipo/PC por capacidades y comandos semánticos; medir rendimiento y
accesibilidad antes de plantear Qt. Los backends existentes permanecen intactos.

