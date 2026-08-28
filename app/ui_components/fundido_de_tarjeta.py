"""El menú de una tarjeta de juego aparece y desaparece con un fundido.

Los banners nuevos llevan el título dentro, así que en reposo la tarjeta es solo
el banner: taparlo con una franja fija sería tapar precisamente lo que se ha
dibujado. El menú —estado del archivo, ARCHIVOS y ABRIR— sale al pasar el ratón.

## Por qué oscurece la tarjeta entera

El primer intento oscurecía solo la mitad de abajo, como hacía la franja fija de
antes. Con los banners nuevos no vale: el título va dentro del dibujo y justo
ahí, así que a media transición se leían dos títulos superpuestos. Se oscurece
la tarjeta completa y el menú sale centrado encima.

## Por qué el fundido va en la imagen y no en un widget

Tk no sabe de transparencias por widget: un ``CTkFrame`` está o no está. Bajarle
la opacidad no existe, y acercar su color al del banner tampoco vale, porque el
banner **no es un color**: tiene un sol, una luna y un logo. La franja aparecería
como un rectángulo plano de golpe.

Así que la franja se compone **dentro de la imagen**, que es donde sí hay canal
alfa de verdad, y el fundido es cambiar de una imagen a la siguiente. Salen ocho
pasos que se construyen una sola vez por juego.

## Y el texto, que no se puede fundir

Un texto de Tk tampoco tiene opacidad. Lo que sí se puede es **mover su color**
desde el del fondo hasta el suyo: si el color de partida es el que va a tener
la franja debajo, el texto nace invisible y se va revelando. Para eso hace falta
saber de qué color queda esa zona en cada paso, y por eso se mide el color medio
del banner justo ahí.
"""

from __future__ import annotations

from typing import Any, Sequence

#: Diez pasos de 16 ms son 160 ms: se lee como un fundido, no como una espera.
PASOS = 10
FOTOGRAMA_MS = 16

#: Lo negra que llega a ser la capa.
NEGRO_DE_LA_FRANJA = (17, 17, 17)

#: Y hasta dónde llega. Sin tope, el banner desaparecía del todo y la tarjeta
#: se quedaba en un rectángulo plano; dejando pasar algo, el dibujo se sigue
#: intuyendo debajo del menú.
MAXIMA_OPACIDAD = 0.94

#: Hasta dónde llega el oscurecido antes de que empiece a revelarse el texto.
#:
#: Este número se ajustó mirando el resultado, no a ojo. Un texto de Tk no tiene
#: opacidad: lo que se hace es moverlo desde el color que tiene el fondo debajo,
#: y ese color se estima con la **media** de la zona. Mientras el banner se siga
#: viendo, su textura no coincide con esa media y el rótulo asoma como un
#: rectángulo plano —el botón ABRIR, que va relleno, era el que más cantaba—.
#: Empezando en 0,6 el fondo ya está al 56% de negro y la diferencia no se ve.
TEXTO_EMPIEZA_EN = 0.6


def a_rgb(color: str | Sequence[int]) -> tuple[int, int, int]:
    """Acepta ``#rrggbb`` o una terna, que es lo que devuelve Pillow."""
    if isinstance(color, str):
        texto = color.strip().lstrip("#")
        if len(texto) == 3:
            texto = "".join(letra * 2 for letra in texto)
        return (int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16))
    valores = tuple(int(v) for v in color)[:3]
    return (valores + (0, 0, 0))[:3]


def a_hex(rgb: Sequence[int]) -> str:
    r, g, b = (max(0, min(255, int(v))) for v in tuple(rgb)[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def mezclar(desde: str | Sequence[int], hasta: str | Sequence[int], paso: float) -> str:
    """Color intermedio. ``paso`` 0 devuelve el primero y 1 el segundo."""
    paso = max(0.0, min(1.0, float(paso)))
    origen, destino = a_rgb(desde), a_rgb(hasta)
    return a_hex(tuple(
        round(origen[i] + (destino[i] - origen[i]) * paso) for i in range(3)
    ))


#: El revelado no es lineal. Con reparto igual, el botón ABRIR —que va relleno—
#: se veía bastante antes que los rótulos: una superficie de color pesa mucho más
#: que unas letras finas a la misma opacidad. Cargando el revelado hacia el final
#: los primeros fotogramas quedan apagados y todo aparece a la vez.
CURVA_DEL_TEXTO = 1.6


def avance_del_texto(paso: float) -> float:
    """Cuánto se ha revelado el texto cuando el oscurecido va por ``paso``."""
    paso = max(0.0, min(1.0, float(paso)))
    if paso <= TEXTO_EMPIEZA_EN:
        return 0.0
    return ((paso - TEXTO_EMPIEZA_EN) / (1.0 - TEXTO_EMPIEZA_EN)) ** CURVA_DEL_TEXTO


def color_bajo_la_franja(fondo: str | Sequence[int], paso: float) -> str:
    """De qué color queda la zona del menú con la capa a media opacidad."""
    return mezclar(fondo, NEGRO_DE_LA_FRANJA, paso * MAXIMA_OPACIDAD)


def color_medio(imagen: Any, caja: tuple[int, int, int, int]) -> str:
    """El color medio del banner justo donde va a caer la franja.

    Es el color desde el que nace el texto. Medirlo en vez de suponerlo importa:
    Sol/Luna es un banner clarísimo y Blanca/Negra casi negro, y un mismo color
    de partida dejaría un texto fantasma en uno de los dos.
    """
    from PIL import Image

    try:
        recorte = imagen.convert("RGB").crop(caja)
        if not recorte.width or not recorte.height:
            return "#111111"
        # Reducir a un pixel con BOX es exactamente la media, y lo hace Pillow
        # en C en vez de recorrer treinta mil tuplas en Python.
        return a_hex(recorte.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)))
    except Exception:
        return "#111111"


def capas_de_la_franja(
    imagen: Any,
    caja: tuple[int, int, int, int],
    *,
    radio: int = 14,
    pasos: int = PASOS,
) -> list[Any]:
    """La misma tarjeta con la franja a opacidad creciente, de 0 a 1.

    La primera capa es el banner intacto, así que en reposo no se le añade nada.
    """
    from PIL import Image, ImageDraw

    base = imagen.convert("RGBA")
    capas = [base]
    for indice in range(1, pasos + 1):
        alfa = round(255 * MAXIMA_OPACIDAD * indice / pasos)
        franja = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(franja).rounded_rectangle(
            caja, radius=radio, fill=(*NEGRO_DE_LA_FRANJA, alfa),
        )
        capas.append(Image.alpha_composite(base, franja))
    return capas


def siguiente_paso(actual: int, hacia: int, pasos: int = PASOS) -> int:
    """Un paso hacia el destino. Sirve igual para entrar que para salir."""
    destino = max(0, min(pasos, int(hacia)))
    actual = max(0, min(pasos, int(actual)))
    if actual == destino:
        return actual
    return actual + (1 if destino > actual else -1)


class Fundido:
    """Lleva una tarjeta de un extremo al otro, fotograma a fotograma.

    Esto vive aquí, y no como funciones anidadas dentro del bucle que monta las
    tarjetas, por una razón concreta: **allí no funcionaba**.

    El animador se llamaba a sí mismo por su nombre para encadenar el siguiente
    fotograma, y quien lo arrancaba también lo nombraba. Python resuelve esos
    nombres *cuando se ejecuta la línea*, no cuando se define la función, así que
    al terminar el bucle los siete apuntaban al último. El menú solo salía en
    Perla Reluciente —y salía aunque el ratón estuviera en cualquier otra—.

    Un objeto no tiene ese problema: cada tarjeta tiene el suyo y se encadena a
    través de ``self``, que no se puede confundir con el de otra.

    ``programar(ms, funcion)`` devuelve algo verdadero si consiguió agendar el
    fotograma. Así este objeto no sabe nada de Tk y se puede probar entero.
    """

    def __init__(
        self,
        pintar: Any,
        programar: Any,
        *,
        pasos: int = PASOS,
        fotograma_ms: int = FOTOGRAMA_MS,
    ) -> None:
        self.pintar = pintar
        self.programar = programar
        self.pasos = int(pasos)
        self.fotograma_ms = int(fotograma_ms)
        self.paso = 0
        self.destino = 0
        self.en_marcha = False

    def ir(self, destino: int) -> None:
        """Marca hacia dónde va y arranca si no estaba ya andando."""
        self.destino = max(0, min(self.pasos, int(destino)))
        if not self.en_marcha:
            self.fotograma()

    def fotograma(self) -> None:
        self.en_marcha = False
        siguiente = siguiente_paso(self.paso, self.destino, self.pasos)
        if siguiente == self.paso:
            return
        self.paso = siguiente
        self.pintar(siguiente)
        if siguiente == self.destino:
            return
        if self.programar(self.fotograma_ms, self.fotograma):
            self.en_marcha = True
