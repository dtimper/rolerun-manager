RoleRun Manager v0.2.2-alpha.42 — Sol/Luna · medallas automáticas por Kahunas

OBJETIVO DE ESTA BUILD
Cerrar el último bloque funcional pendiente de Pokémon Sol/Luna: MEDALLAS se actualiza automáticamente al completar las cuatro Grandes Pruebas, igual que el progreso de gimnasios ya se sincroniza en X/Y y ORAS.

REGLA ROLERUN PARA ALOLA
- Hala derrotado   → 1 medalla.
- Olivia derrotada → 2 medallas.
- Nanu derrotado   → 3 medallas.
- Hapu derrotada   → 4 medallas.
- Máximo: 4.
- Pruebas normales y capitanes NO cuentan como medallas.

CÓMO SE DETECTA
Alpha.42 no suma una medalla por observar el final de un combate. Reconstruye un valor absoluto 0..4 desde progreso persistente de la propia partida, siguiendo la misma filosofía que ORAS/X/Y.

Cada Gran Prueba entrega un Z-Crystal persistente:
- Hala   → Fightinium Z
- Olivia → Rockium Z
- Nanu   → Darkinium Z
- Hapu   → Groundium Z

El bolsillo Z-Crystals y sus IDs se leen desde la estructura SAV7SM documentada por PKHeX. La secuencia debe ser un prefijo válido: si apareciera un premio posterior sin los anteriores, RoleRun rechaza esa muestra en lugar de convertirla en una medalla falsa.

SEGURIDAD DE LA RAM LIVE
RoleRun no acepta una dirección porque esté documentada o porque sea legible.

Orden de resolución:
1. Reutiliza la mochila viva si ya fue demostrada por el sistema de MT.
2. Reutiliza la relación PC→Items si el PC ya fue demostrado para esa sesión.
3. Prueba una candidata guest rápida derivada de la referencia LiveHeX ya usada por el backend SM.
4. Si ninguna ruta rápida vale, fuera de combate reutiliza el descubrimiento estructural host↔guest del sistema de MT.
5. El `main` queda como fallback de solo lectura.

Toda candidata rápida exige:
- dos lecturas idénticas;
- tamaño exacto del bloque Items;
- coincidencia estructural fuerte contra el `main` real;
- al menos dos ventanas no vacías idénticas al `main` para impedir que una región RAM llena de ceros simule 0 medallas;
- bolsillo Z-Crystals estructuralmente válido;
- secuencia Hala→Olivia→Nanu→Hapu coherente.

RENDIMIENTO
- Dentro de combate NO se permite la calibración FCRAM pesada de mochila.
- El detector de PS alpha.41 mantiene su monitor rápido (~250 ms).
- Fuera de combate, si hiciera falta una calibración estructural completa, se ejecuta en el worker live y entra en cooldown si falla; nunca desde el render de la UI.

UI / OBS
En Sol/Luna MEDALLAS pasa a tener una única fuente de verdad: el juego.
- Dashboard: muestra AUTOMÁTICO.
- Barra flotante: muestra AUTO.
- Botones +/- de medallas: deshabilitados/ocultos.
- Hotkeys de +/- medallas: no se ofrecen y se ignoran si una Run antigua aún los conserva.
- Al cambiar el valor vivo se actualizan Dashboard, barra flotante y OBS.
- La sincronización usa valor absoluto, por lo que no puede sumar dos veces la misma Gran Prueba.

COMPATIBILIDAD SOL / LUNA
La implementación vive en el backend común `sm` y acepta explícitamente ambos Title IDs retail. Los tests cubren la ruta live tanto con Pokémon Sol como con Pokémon Luna.

PRUEBA MANUAL RECOMENDADA
La prueba definitiva debe hacerse en el juego real:
1. Abre la Run y deja RoleRun conectado antes de completar una Gran Prueba.
2. Comprueba el valor actual de MEDALLAS.
3. Derrota al Kahuna y avanza hasta recibir su Z-Crystal / completar la Gran Prueba.
4. Sin tocar los controles de RoleRun, MEDALLAS debe pasar al valor correspondiente en el siguiente monitor live (normalmente ~1 s fuera de combate).
5. Comprueba que Dashboard, barra flotante y OBS muestran el mismo valor.
6. Deja RoleRun abierto varios ticks: no debe volver a sumar.
7. Reinicia RoleRun: debe reconstruir el mismo valor absoluto.

PRUEBAS AUTOMATIZADAS
- Conteo 0/1/2/3/4 por prefijo exacto.
- Rechazo de huecos en la secuencia.
- Rechazo de bolsillo Z inválido, duplicados y cantidades imposibles.
- Fallback desde `main`.
- Candidata live validada con `main` todavía una medalla por detrás.
- Rechazo de candidata RAM falsa.
- Title ID de Pokémon Sol.
- Title ID de Pokémon Luna.
- Publicación de badges/badge_source por SMRealTimeAdapter.
- MEDALLAS automático en UI para backend `sm`.

NO TOCADO
- Party live.
- HP intra-combate / muertes alpha.41.
- Cementerio y sustitución.
- Writer Equipo↔PC / ENVIAR AL PC.
- Roles.
- Movimientos / MT.
- Inventario / dinero.
- ORAS / X/Y.
