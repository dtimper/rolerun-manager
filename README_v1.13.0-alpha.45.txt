RoleRun Manager 1.13.0-alpha.45
================================

Objetivo de esta build
----------------------
Corregir el selector de MT de ORAS sin tocar el detector de medallas, el PC ni
las reglas de roles ya cerradas en las builds anteriores.

Problema corregido
------------------
Alpha.44 seguía leyendo las MT desde una dirección nominal fija de RAM aunque
el sistema de medallas ya había aprendido a localizar dinámicamente la copia
viva real de la mochila. En Azahar pueden coexistir copias antiguas/vacías, de
modo que el contador podía detectar 8 medallas correctamente y la ventana de
MT mostrar 0 opciones al mismo tiempo.

Alpha.45 unifica ambas rutas:
- medallas y selector de MT comparten la mochila MT/MO viva validada;
- SUSTITUIR usa también RAM viva en su comprobación silenciosa;
- la dirección fija solo se acepta si pasa validación;
- si no hay candidatos, la ventana muestra cuántas MT detectó, cuántas puede
  aprender la especie y cuántas cumplen el rol.

Prueba recomendada
------------------
1. Abre Azahar y tu Run ORAS normalmente.
2. No ejecutes preparar_motor.bat.
3. Comprueba que las medallas siguen mostrando 8.
4. En un Pokémon Prisma pulsa SUSTITUIR sobre un ataque incompatible.
5. La cabecera debe indicar "RAM viva validada".
6. Deben aparecer las MT de daño de tu mochila que ese Pokémon pueda aprender.
7. Si la lista quedara vacía, envía una captura donde se vea la línea de
   diagnóstico (MTs detectadas / aprendibles / compatibles con Prisma).

Verificación automática
------------------------
- 53/53 pruebas específicas ORAS live-write/medallas/MT vivas.
- 150 pruebas no gráficas superadas (se omite únicamente el test que importa
  customtkinter directamente, dependencia no instalada en este contenedor).
- compileall correcto para app, tests y main.py.

Motor .NET
----------
No es necesario ejecutar preparar_motor.bat para esta actualización.

---

Historial de alpha.44
---------------------
RoleRun Manager 1.13.0-alpha.44
================================

Objetivo de esta build
----------------------
Mejorar el gestor del PC y ajustar los drafteos defensivos sin tocar la detección
de medallas ORAS que ya funciona en alpha.41+ ni el nuevo orden de marcadores de
alpha.43.

1. Drafteos Tanque / Prisma
---------------------------
Se elimina "Recuperación Pasiva" como categoría independiente de drafteo.

Tanque draftea ahora:
- Subir Defensa Física
- Protección
- Ataque Físico
- Ataque Especial

Prisma draftea ahora:
- Subir Defensa Especial
- Protección
- Ataque Físico
- Ataque Especial

Acua Aro y Arraigo SIGUEN siendo movimientos legales para Tanque y Prisma si ya
los tienen o los obtienen por otro mecanismo. Simplemente dejan de tener una
categoría propia de drafteo.

2. Scroll entre cajas
---------------------
Corregido el estado heredado del CTkScrollableFrame al cambiar entre cajas.

Caso reproducido:
- Caja 1 llena, scroll al fondo.
- Caja 2 con pocos Pokémon.
- Al pasar a Caja 2, el scroll conservaba la posición de la caja alta y las
  tarjetas podían quedar fuera del viewport hasta cambiar otra vez de caja.

Ahora cada cambio de caja reinicia el viewport al principio antes de reconstruir
las tarjetas y vuelve a fijarlo al inicio después de los ciclos de geometría de
CustomTkinter. Una caja corta ya no puede heredar un desplazamiento imposible de
una caja larga.

3. Buscador global del PC
-------------------------
CAJAS PC incorpora un buscador encima de la cuadrícula.

La búsqueda se realiza sobre TODAS las cajas y contempla:
- nombre real de la especie;
- mote;
- habilidad;
- cualquiera de los movimientos del Pokémon.

Características:
- ignora mayúsculas/minúsculas y tildes;
- permite varias palabras (todas deben aparecer en los datos del Pokémon);
- cada resultado conserva y muestra su Caja y hueco reales;
- seleccionar, cambiar rol, añadir o sustituir desde un resultado sigue actuando
  sobre el Pokémon de su posición original;
- al borrar la búsqueda se vuelve a la caja que estaba abierta;
- usar las flechas o escribir un número de caja abandona la búsqueda y vuelve al
  modo normal de cajas.

Medallas / tiempo real
----------------------
No se modifica el detector de medallas ORAS. La lógica de alpha.41 que ya detecta
correctamente una partida de 8 medallas permanece intacta.

Motor .NET
----------
No es necesario ejecutar preparar_motor.bat para esta actualización. Los cambios
de alpha.44 están en la aplicación Python/datos de drafteo y no cambian el
contrato del SaveEngine.

Pruebas manuales recomendadas
-----------------------------
A. Drafteos
1. Abre Drafteos -> Tanque y verifica que no existe Recuperación Pasiva.
2. Repite con Prisma.
3. Verifica que las otras cuatro categorías siguen apareciendo correctamente.

B. Scroll
1. Abre una caja llena y baja hasta el final.
2. Pasa directamente a una caja con 1-3 Pokémon.
3. Debe abrirse arriba y mostrar inmediatamente esos Pokémon.
4. Alterna varias veces entre ambas cajas, también usando el número de caja.

C. Buscador
1. Busca el nombre real de un Pokémon que esté en otra caja.
2. Busca su mote.
3. Busca uno de sus ataques.
4. Busca su habilidad.
5. Prueba el mismo texto sin tildes y en mayúsculas.
6. Selecciona un resultado y comprueba que la ficha indica Caja/Hueco correctos.
7. Cambia su rol o úsalo en un cambio Equipo <-> PC y comprueba que se modifica
   exactamente ese Pokémon.
8. Borra el texto y confirma que vuelve la vista normal de la caja.
