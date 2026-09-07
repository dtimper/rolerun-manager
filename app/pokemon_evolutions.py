"""Cadenas de evolución por especie: quién puede convertirse en quién.

Pedido por el usuario el 2026-09-05 tras encontrar, en pruebas físicas
reales, que evolucionar deja una ventana real (varios segundos, no un
instante) en la que la fila de aprendizajes por nivel de la NUEVA especie
sigue sin parchear -RoleRun solo se entera de la evolución por su propio
sondeo, y parchear (releer party, recorrer las ~826 especies del GARC,
reescribir el archivo) tarda lo suficiente como para perder la carrera si
el jugador sube de nivel enseguida-. Validado con Flabébé → Floette
(especie 669 → 670): aprendió Deseo sin sustituir, con el rol ya asignado
desde antes de evolucionar.

En vez de intentar ganar esa carrera, se elimina: si un Pokémon con rol
asignado puede evolucionar a otra especie, esa especie recibe el MISMO
parche de rol *antes* de que evolucione de verdad -sin esperar a que
ocurra-. Cuando evoluciona, su fila ya lleva un rato correcta.

No se intenta reproducir bit a bit la tabla de evolución real del juego
-método (nivel, piedra, intercambio...), parámetro, forma-: esto solo
necesita saber QUÉ especies son alcanzables, para decidir a qué filas del
GARC de aprendizajes aplicar el mismo parche por adelantado. Una entrada de
más aquí es inofensiva -esa fila solo se toca si además hay un Pokémon con
rol asignado que apunte a ella-; una de menos simplemente deja sin cerrar
la ventana para esa especie en concreto, ni mejor ni peor que antes de
este cambio.

Cubre las cadenas de evolución de la Dex Nacional hasta la 6ª generación
(hasta Volcanion, #721), que es el límite de especies reales de Pokémon
X/Y y de los demás juegos que ya usan esta capacidad.
"""

from __future__ import annotations

# {especie: (especies_a_las_que_puede_evolucionar_directamente, ...)}
# Solo la especie base o intermedia -> su(s) siguiente(s) etapa(s). Las
# especies finales de su línea simplemente no aparecen como clave.
EVOLUTIONS: dict[int, tuple[int, ...]] = {
    # Bulbasaur - Venusaur
    1: (2,), 2: (3,),
    # Charmander - Charizard
    4: (5,), 5: (6,),
    # Squirtle - Blastoise
    7: (8,), 8: (9,),
    # Caterpie - Butterfree / Weedle - Beedrill
    10: (11,), 11: (12,),
    13: (14,), 14: (15,),
    # Pidgey - Pidgeot
    16: (17,), 17: (18,),
    # Rattata - Raticate
    19: (20,),
    # Spearow - Fearow
    21: (22,),
    # Ekans - Arbok
    23: (24,),
    # Pichu - Pikachu - Raichu
    172: (25,), 25: (26,),
    # Sandshrew - Sandslash
    27: (28,),
    # Nidoran F - Nidorina - Nidoqueen ; Nidoran M - Nidorino - Nidoking
    29: (30,), 30: (31,),
    32: (33,), 33: (34,),
    # Cleffa - Clefairy - Clefable
    173: (35,), 35: (36,),
    # Vulpix - Ninetales
    37: (38,),
    # Igglybuff - Jigglypuff - Wigglytuff
    174: (39,), 39: (40,),
    # Zubat - Golbat - Crobat (Crobat por amistad, sin evolución "directa" de nivel en Golbat aquí)
    41: (42,), 42: (169,),
    # Oddish - Gloom - Vileplume / Bellossom
    43: (44,), 44: (45, 182),
    # Paras - Parasect
    46: (47,),
    # Venonat - Venomoth
    48: (49,),
    # Diglett - Dugtrio
    50: (51,),
    # Meowth - Persian
    52: (53,),
    # Psyduck - Golduck
    54: (55,),
    # Mankey - Primeape
    56: (57,),
    # Growlithe - Arcanine
    58: (59,),
    # Poliwag - Poliwhirl - Poliwrath / Politoed
    60: (61,), 61: (62, 186),
    # Abra - Kadabra - Alakazam
    63: (64,), 64: (65,),
    # Machop - Machoke - Machamp
    66: (67,), 67: (68,),
    # Bellsprout - Weepinbell - Victreebel
    69: (70,), 70: (71,),
    # Tentacool - Tentacruel
    72: (73,),
    # Geodude - Graveler - Golem
    74: (75,), 75: (76,),
    # Ponyta - Rapidash
    77: (78,),
    # Slowpoke - Slowbro / Slowking
    79: (80, 199),
    # Magnemite - Magneton - Magnezone (Gen4+, se incluye por completitud)
    81: (82,), 82: (462,),
    # Farfetch'd (sin evolución en esta gen)
    # Doduo - Dodrio
    84: (85,),
    # Seel - Dewgong
    86: (87,),
    # Grimer - Muk
    88: (89,),
    # Shellder - Cloyster
    90: (91,),
    # Gastly - Haunter - Gengar
    92: (93,), 93: (94,),
    # Onix - Steelix
    95: (208,),
    # Drowzee - Hypno
    96: (97,),
    # Krabby - Kingler
    98: (99,),
    # Voltorb - Electrode
    100: (101,),
    # Exeggcute - Exeggutor
    102: (103,),
    # Cubone - Marowak
    104: (105,),
    # Tyrogue - Hitmonlee / Hitmonchan / Hitmontop
    236: (106, 107, 237),
    # Koffing - Weezing
    109: (110,),
    # Rhyhorn - Rhydon - Rhyperior
    111: (112,), 112: (464,),
    # Happiny - Chansey - Blissey
    440: (113,), 113: (242,),
    # Tangela - Tangrowth
    114: (465,),
    # Lickitung - Lickilicky
    108: (463,),
    # Kangaskhan (sin evolución)
    # Horsea - Seadra - Kingdra
    116: (117,), 117: (230,),
    # Goldeen - Seaking
    118: (119,),
    # Staryu - Starmie
    120: (121,),
    # Mime Jr. - Mr. Mime
    439: (122,),
    # Scyther - Scizor
    123: (212,),
    # Smoochum - Jynx
    238: (124,),
    # Elekid - Electabuzz - Electivire
    239: (125,), 125: (466,),
    # Magby - Magmar - Magmortar
    240: (126,), 126: (467,),
    # Pinsir (sin evolución)
    # Tauros (sin evolución)
    # Magikarp - Gyarados
    129: (130,),
    # Eevee - Vaporeon/Jolteon/Flareon/Espeon/Umbreon/Leafeon/Glaceon/Sylveon
    133: (134, 135, 136, 196, 197, 470, 471, 700),
    # Omanyte - Omastar / Kabuto - Kabutops
    138: (139,), 140: (141,),
    # Dratini - Dragonair - Dragonite
    147: (148,), 148: (149,),
    # Larvitar - Pupitar - Tyranitar
    246: (247,), 247: (248,),
    # Chikorita - Bayleef - Meganium
    152: (153,), 153: (154,),
    # Cyndaquil - Quilava - Typhlosion
    155: (156,), 156: (157,),
    # Totodile - Croconaw - Feraligatr
    158: (159,), 159: (160,),
    # Sentret - Furret
    161: (162,),
    # Hoothoot - Noctowl
    163: (164,),
    # Ledyba - Ledian
    165: (166,),
    # Spinarak - Ariados
    167: (168,),
    # Chinchou - Lanturn
    170: (171,),
    # Natu - Xatu
    177: (178,),
    # Mareep - Flaaffy - Ampharos
    179: (180,), 180: (181,),
    # Marill - Azumarill (con Azurill antes)
    298: (183,), 183: (184,),
    # Sudowoodo (Bonsly evoluciona a Sudowoodo)
    438: (185,),
    # Hoppip - Skiploom - Jumpluff
    187: (188,), 188: (189,),
    # Aipom - Ambipom
    190: (424,),
    # Sunkern - Sunflora
    191: (192,),
    # Yanma - Yanmega
    193: (469,),
    # Wooper - Quagsire
    194: (195,),
    # Murkrow - Honchkrow
    198: (430,),
    # Misdreavus - Mismagius
    200: (429,),
    # Girafarig (sin evolución)
    # Pineco - Forretress
    204: (205,),
    # Dunsparce (sin evolución)
    # Gligar - Gliscor
    207: (472,),
    # Snubbull - Granbull
    209: (210,),
    # Qwilfish (sin evolución en esta gen)
    # Shuckle (sin evolución)
    # Heracross (sin evolución)
    # Sneasel - Weavile
    215: (461,),
    # Teddiursa - Ursaring
    216: (217,),
    # Slugma - Magcargo
    218: (219,),
    # Swinub - Piloswine - Mamoswine
    220: (221,), 221: (473,),
    # Remoraid - Octillery
    223: (224,),
    # Mantyke - Mantine
    458: (226,),
    # Houndour - Houndoom
    228: (229,),
    # Phanpy - Donphan
    231: (232,),
    # Porygon - Porygon2 - Porygon-Z
    137: (233,), 233: (474,),
    # Stantler (sin evolución)
    # Wynaut - Wobbuffet
    360: (202,),
    # Snorunt - Glalie / Froslass
    361: (362, 478),
    # Spheal - Sealeo - Walrein
    363: (364,), 364: (365,),
    # Clamperl - Huntail / Gorebyss
    366: (367, 368),
    # Bagon - Shelgon - Salamence
    371: (372,), 372: (373,),
    # Beldum - Metang - Metagross
    374: (375,), 375: (376,),
    # Treecko - Grovyle - Sceptile
    252: (253,), 253: (254,),
    # Torchic - Combusken - Blaziken
    255: (256,), 256: (257,),
    # Mudkip - Marshtomp - Swampert
    258: (259,), 259: (260,),
    # Poochyena - Mightyena
    261: (262,),
    # Zigzagoon - Linoone
    263: (264,),
    # Wurmple - Silcoon - Beautifly / Cascoon - Dustox
    265: (266, 268), 266: (267,), 268: (269,),
    # Lotad - Lombre - Ludicolo
    270: (271,), 271: (272,),
    # Seedot - Nuzleaf - Shiftry
    273: (274,), 274: (275,),
    # Taillow - Swellow
    276: (277,),
    # Wingull - Pelipper
    278: (279,),
    # Ralts - Kirlia - Gardevoir / Gallade
    280: (281,), 281: (282, 475),
    # Surskit - Masquerain
    283: (284,),
    # Shroomish - Breloom
    285: (286,),
    # Slakoth - Vigoroth - Slaking
    287: (288,), 288: (289,),
    # Nincada - Ninjask (+ Shedinja)
    290: (291, 292),
    # Whismur - Loudred - Exploud
    293: (294,), 294: (295,),
    # Makuhita - Hariyama
    296: (297,),
    # Nosepass - Probopass
    299: (476,),
    # Skitty - Delcatty
    300: (301,),
    # Sableye (sin evolución)
    # Mawile (sin evolución en esta gen)
    # Aron - Lairon - Aggron
    304: (305,), 305: (306,),
    # Meditite - Medicham
    307: (308,),
    # Electrike - Manectric
    309: (310,),
    # Plusle / Minun (sin evolución)
    # Volbeat / Illumise (sin evolución)
    # Gulpin - Swalot
    316: (317,),
    # Carvanha - Sharpedo
    318: (319,),
    # Wailmer - Wailord
    320: (321,),
    # Numel - Camerupt
    322: (323,),
    # Spoink - Grumpig
    325: (326,),
    # Trapinch - Vibrava - Flygon
    328: (329,), 329: (330,),
    # Cacnea - Cacturne
    331: (332,),
    # Swablu - Altaria
    333: (334,),
    # Barboach - Whiscash
    339: (340,),
    # Corphish - Crawdaunt
    341: (342,),
    # Baltoy - Claydol
    343: (344,),
    # Lileep - Cradily
    345: (346,),
    # Anorith - Armaldo
    347: (348,),
    # Feebas - Milotic
    349: (350,),
    # Shuppet - Banette
    353: (354,),
    # Duskull - Dusclops - Dusknoir
    355: (356,), 356: (477,),
    # Chimecho (sin evolución previa en esta gen sin Chingling; Chingling->Chimecho)
    433: (358,),
    # Absol (sin evolución)
    # Snorunt ya cubierto arriba
    # Spheal ya cubierto
    # Bagon ya cubierto
    # Turtwig - Grotle - Torterra
    387: (388,), 388: (389,),
    # Chimchar - Monferno - Infernape
    390: (391,), 391: (392,),
    # Piplup - Prinplup - Empoleon
    393: (394,), 394: (395,),
    # Starly - Staravia - Staraptor
    396: (397,), 397: (398,),
    # Bidoof - Bibarel
    399: (400,),
    # Kricketot - Kricketune
    401: (402,),
    # Shinx - Luxio - Luxray
    403: (404,), 404: (405,),
    # Budew - Roselia - Roserade
    406: (315,), 315: (407,),
    # Cranidos - Rampardos
    408: (409,),
    # Shieldon - Bastiodon
    410: (411,),
    # Burmy - Wormadam / Mothim
    412: (413, 414),
    # Combee - Vespiquen
    415: (416,),
    # Buizel - Floatzel
    418: (419,),
    # Cherubi - Cherrim
    420: (421,),
    # Shellos - Gastrodon
    422: (423,),
    # Drifloon - Drifblim
    425: (426,),
    # Buneary - Lopunny
    427: (428,),
    # Glameow - Purugly
    431: (432,),
    # Chingling ya cubierto arriba (a Chimecho)
    # Stunky - Skuntank
    434: (435,),
    # Bronzor - Bronzong
    436: (437,),
    # Bonsly ya cubierto (a Sudowoodo)
    # Mime Jr. ya cubierto (a Mr. Mime)
    # Happiny ya cubierto (a Chansey)
    # Chatot (sin evolución)
    # Spiritomb (sin evolución)
    # Gible - Gabite - Garchomp
    443: (444,), 444: (445,),
    # Munchlax - Snorlax
    446: (143,),
    # Riolu - Lucario
    447: (448,),
    # Hippopotas - Hippowdon
    449: (450,),
    # Skorupi - Drapion
    451: (452,),
    # Croagunk - Toxicroak
    453: (454,),
    # Finneon - Lumineon
    456: (457,),
    # Snover - Abomasnow
    459: (460,),
    # Rotom (formas, sin especie nueva relevante aquí)
    # Uxie / Mesprit / Azelf / Dialga / Palkia / Heatran / Regigigas / Giratina / Cresselia / Phione / Manaphy / Darkrai / Shaymin / Arceus: sin evolución
    # Victini: sin evolución
    # Snivy - Servine - Serperior
    495: (496,), 496: (497,),
    # Tepig - Pignite - Emboar
    498: (499,), 499: (500,),
    # Oshawott - Dewott - Samurott
    501: (502,), 502: (503,),
    # Patrat - Watchog
    504: (505,),
    # Lillipup - Herdier - Stoutland
    506: (507,), 507: (508,),
    # Purrloin - Liepard
    509: (510,),
    # Pansage - Simisage / Pansear - Simisear / Panpour - Simipour
    511: (512,), 513: (514,), 515: (516,),
    # Munna - Musharna
    517: (518,),
    # Pidove - Tranquill - Unfezant
    519: (520,), 520: (521,),
    # Blitzle - Zebstrika
    522: (523,),
    # Roggenrola - Boldore - Gigalith
    524: (525,), 525: (526,),
    # Woobat - Swoobat
    527: (528,),
    # Drilbur - Excadrill
    529: (530,),
    # Audino (sin evolución en esta gen)
    # Timburr - Gurdurr - Conkeldurr
    532: (533,), 533: (534,),
    # Tympole - Palpitoad - Seismitoad
    535: (536,), 536: (537,),
    # Sewaddle - Swadloon - Leavanny
    540: (541,), 541: (542,),
    # Venipede - Whirlipede - Scolipede
    543: (544,), 544: (545,),
    # Cottonee - Whimsicott
    546: (547,),
    # Petilil - Lilligant
    548: (549,),
    # Sandile - Krokorok - Krookodile
    551: (552,), 552: (553,),
    # Darumaka - Darmanitan
    554: (555,),
    # Dwebble - Crustle
    557: (558,),
    # Scraggy - Scrafty
    559: (560,),
    # Yamask - Cofagrigus
    562: (563,),
    # Tirtouga - Carracosta
    564: (565,),
    # Archen - Archeops
    566: (567,),
    # Trubbish - Garbodor
    568: (569,),
    # Zorua - Zoroark
    570: (571,),
    # Minccino - Cinccino
    572: (573,),
    # Gothita - Gothorita - Gothitelle
    574: (575,), 575: (576,),
    # Solosis - Duosion - Reuniclus
    577: (578,), 578: (579,),
    # Ducklett - Swanna
    580: (581,),
    # Vanillite - Vanillish - Vanilluxe
    582: (583,), 583: (584,),
    # Deerling - Sawsbuck
    585: (586,),
    # Karrablast - Escavalier
    588: (589,),
    # Foongus - Amoonguss
    590: (591,),
    # Frillish - Jellicent
    592: (593,),
    # Joltik - Galvantula
    595: (596,),
    # Ferroseed - Ferrothorn
    597: (598,),
    # Klink - Klang - Klinklang
    599: (600,), 600: (601,),
    # Tynamo - Eelektrik - Eelektross
    602: (603,), 603: (604,),
    # Elgyem - Beheeyem
    605: (606,),
    # Litwick - Lampent - Chandelure
    607: (608,), 608: (609,),
    # Axew - Fraxure - Haxorus
    610: (611,), 611: (612,),
    # Cubchoo - Beartic
    613: (614,),
    # Shelmet - Accelgor
    616: (617,),
    # Mienfoo - Mienshao
    619: (620,),
    # Golett - Golurk
    622: (623,),
    # Pawniard - Bisharp
    624: (625,),
    # Rufflet - Braviary
    627: (628,),
    # Vullaby - Mandibuzz
    629: (630,),
    # Deino - Zweilous - Hydreigon
    633: (634,), 634: (635,),
    # Larvesta - Volcarona
    636: (637,),
    # Espurr - Meowstic
    677: (678,),
    # Honedge - Doublade - Aegislash
    679: (680,), 680: (681,),
    # Spritzee - Aromatisse
    682: (683,),
    # Swirlix - Slurpuff
    684: (685,),
    # Inkay - Malamar
    686: (687,),
    # Binacle - Barbaracle
    688: (689,),
    # Skrelp - Dragalge
    690: (691,),
    # Clauncher - Clawitzer
    692: (693,),
    # Helioptile - Heliolisk
    694: (695,),
    # Tyrunt - Tyrantrum
    696: (697,),
    # Amaura - Aurorus
    698: (699,),
    # Pancham - Pangoro
    674: (675,),
    # Flabébé - Floette - Florges
    669: (670,), 670: (671,),
    # Skiddo - Gogoat
    672: (673,),
    # Bergmite - Avalugg
    712: (713,),
    # Noibat - Noivern
    714: (715,),
    # Chespin - Quilladin - Chesnaught
    650: (651,), 651: (652,),
    # Fennekin - Braixen - Delphox
    653: (654,), 654: (655,),
    # Froakie - Frogadier - Greninja
    656: (657,), 657: (658,),
    # Bunnelby - Diggersby
    659: (660,),
    # Fletchling - Fletchinder - Talonflame
    661: (662,), 662: (663,),
    # Scatterbug - Spewpa - Vivillon
    664: (665,), 665: (666,),
    # Litleo - Pyroar
    667: (668,),
    # Furfrou (sin evolución)
    # Doedenne (sin evolución)
    # Goomy - Sliggoo - Goodra
    704: (705,), 705: (706,),
    # Klefki (sin evolución)
    # Phantump - Trevenant
    708: (709,),
    # Pumpkaboo - Gourgeist
    710: (711,),
    # Hawlucha, Dedenne, Carbink, Sylveon (final), Zygarde, Diancie, Hoopa, Volcanion: sin evolución adicional
}


def evolution_descendants(species_id: int) -> frozenset[int]:
    """Todas las especies alcanzables evolucionando cero o más veces desde
    ``species_id`` -sin incluir la propia especie de partida-.

    Recorre el grafo en anchura; una cadena rota o un ciclo accidental en
    los datos no puede colgarse gracias al conjunto ``visitados``.
    """
    visited: set[int] = set()
    pending = [int(species_id)]
    while pending:
        current = pending.pop()
        for target in EVOLUTIONS.get(current, ()):
            if target not in visited:
                visited.add(target)
                pending.append(target)
    return frozenset(visited)
