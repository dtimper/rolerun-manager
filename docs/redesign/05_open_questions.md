# Cuestiones abiertas de producto

## Estado

No queda ninguna pregunta técnica bloqueante para iniciar las fases 0–2 de la
hoja de ruta. El repositorio permite decidir arquitectura, fuentes de datos,
seguridad, capabilities, estrategia de migración y pruebas sin pedir al usuario
offsets, archivos o soluciones.

Las únicas cuestiones que no tienen una respuesta objetiva en código son
preferencias de producto. No es necesario responderlas durante esta auditoría;
cada una incluye un valor recomendado para poder avanzar sin bloquearse.

## Preguntas para Diego

### P1. Densidad predeterminada

**Pregunta:** ¿prefieres que Equipo y PC use por defecto una densidad compacta
(más Pokémon visibles) o cómoda (más texto y espacio)?

**Recomendación inicial:** compacta en 1360×860, con selector “Compacta/Cómoda” y
preferencia recordada. El inspector conserva los datos completos.

**Por qué requiere preferencia:** ambas opciones son técnicamente viables y el
repositorio no expresa una prioridad estética del usuario entre comparación y
tamaño de lectura.

### P2. Nombres de las secciones principales

**Pregunta:** ¿te resultan naturales los nombres propuestos “Inicio”, “Equipo y
PC”, “MT”, “Progreso”, “Registro”, “Emisión”, “Ajustes” y “Diagnóstico”?

**Recomendación inicial:** usar esos nombres en español; “Registro” contiene las
tabs “Actividad” y “Cementerio”. Son directos y evitan jerga técnica.

**Por qué requiere preferencia:** la taxonomía puede validarse con flujos, pero el
tono verbal forma parte de la identidad del producto.

### P3. Confirmación de swaps reversibles

**Pregunta:** cuando el preview deja claro qué dos Pokémon se intercambian y la
operación tiene verificación/rollback, ¿quieres confirmación adicional o ejecución
inmediata?

**Recomendación inicial:** inmediata para swaps 1↔1; confirmación para bajas,
eliminaciones, sobrescrituras y operaciones sin inversa automática. Siempre se
muestra pendiente hasta readback.

**Por qué requiere preferencia:** seguridad técnica y rollback están definidos;
el número de confirmaciones tolerable es una decisión de experiencia.

### P4. Prioridad visual de la identidad Pokémon

**Pregunta:** ¿prefieres sprites grandes y expresivos o una vista más analítica
con sprites pequeños y más datos comparables?

**Recomendación inicial:** sprites medianos en Equipo, pequeños en PC y grandes
solo en el inspector. Mantiene el carácter Pokémon sin recuperar las tarjetas
altas actuales.

**Por qué requiere preferencia:** no cambia capacidad ni seguridad; define el
equilibrio visual de RoleRun.

### P5. Atajos avanzados y command palette

**Pregunta:** ¿quieres que una futura paleta `Ctrl+K` exponga navegación y acciones
seguras, o prefieres limitar los atajos a los que ya usas mientras juegas?

**Recomendación inicial:** no incluirla en el primer piloto. Añadir primero
búsqueda local, teclado de rejilla y atajos actuales; evaluar `Ctrl+K` después de
que la navegación nueva sea estable.

**Por qué requiere preferencia:** el patrón acelera usuarios expertos, pero puede
añadir complejidad que no aporta valor al uso real del propietario.

### P6. Juego piloto de la nueva interfaz

**Pregunta:** cuando la shell y las vistas de solo lectura estén preparadas,
¿prefieres pilotarlas primero con BDSP —último backend físicamente cerrado— o con
el siguiente juego que esté en desarrollo en ese momento?

**Recomendación inicial:** BDSP para lectura/Equipo-PC porque tiene evidencia
reciente y una matriz amplia de capacidades; mantener cualquier trabajo del
siguiente juego separado.

**Por qué requiere preferencia:** técnicamente BDSP minimiza incertidumbre, pero
la prioridad de juego futura pertenece a la planificación del usuario.

## Decisiones que no deben trasladarse al usuario

Estas cuestiones quedan resueltas por evidencia y no se preguntarán a Diego:

- qué archivos, servicios, readers o writers usar;
- si una dirección RAM o estructura puede reutilizarse entre juegos;
- cómo implementar readback, precondiciones o rollback;
- cómo evitar el séptimo miembro de party;
- cómo distinguir un rol de la posición física;
- qué tests y diagnóstico necesita cada bug;
- si hay que migrar a Qt por apariencia;
- cómo instrumentar una reproducción;
- cómo conservar la interfaz clásica durante la migración.

## Hipótesis aún no convertidas en decisiones

No bloquean documentación ni fases iniciales:

1. **Virtualización:** puede ser necesaria para las cajas completas, pero debe
   medirse en Fase 5 con CustomTkinter antes de elegir implementación.
2. **Qt:** puede reducir trabajo de model/view y accesibilidad, pero no está
   justificado migrar sin el benchmark definido.
3. **Acciones rápidas internas:** pueden ser legado o una función útil no expuesta.
   Antes de mostrarlas hay que contrastar historial de producto/uso, no asumir que
   toda función interna merece botón.
4. **Revisión global del equipo:** `_open_team_review()` existe sin acceso visible
   demostrado. Se tratará como capacidad candidata hasta verificar si quedó
   intencionadamente retirada.

