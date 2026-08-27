RoleRun Manager v0.2.2-alpha.136

Esta versión incorpora el entrenamiento automático por rol en Pokémon
Sol/Luna. Al asignar un rol, RoleRun prepara sus dos EV a 252 y pone los demás
a 0; Líbero permite elegir los dos atributos.

El writer SM recalcula inmediatamente PS y estadísticas usando los datos
efectivos de la ROM, conserva el daño ya sufrido y verifica la escritura y su
posible rollback antes de aceptar el cambio.

Validado físicamente en Pokémon Sol/Azahar: al reasignar Asesino a un Pikipek
de nivel 4, los EV de Ataque/Velocidad quedaron en 252/252, los otros cuatro en
0 y las estadísticas finales se recalcularon manteniendo sus PS actuales.
