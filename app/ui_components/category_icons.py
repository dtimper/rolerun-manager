from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image


#: Nombre de archivo por categoría de combate. Los PNG los aportó el usuario
#: el 02-09-2026 ya coloreados (rojo/físico, azul/especial, gris/estado) al
#: estilo de los juegos: se usan tal cual, sin recolorear -a diferencia de
#: ``RoleIconProvider``, que sí tiñe una silueta.
CATEGORY_ICON_FILES = {
    "physical": "physical.png",
    "special": "special.png",
    "status": "status.png",
}


class CategoryIconProvider:
    """Icono de categoría (físico/especial/estado) tal cual lo trae el PNG."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._pil_cache: dict[str, Image.Image] = {}
        self._ctk_cache: dict[tuple[str, int], ctk.CTkImage] = {}

    def image(self, category: str, size: int) -> ctk.CTkImage | None:
        canvas = self.pil_image(category, size)
        if canvas is None:
            return None
        category = str(category or "")
        size = max(10, int(size))
        key = (category, size)
        cached = self._ctk_cache.get(key)
        if cached is not None:
            return cached
        # Los PNG son rectangulares (70x36, no cuadrados): forzar
        # `size=(size, size)` los estiraba y se veían aplastados -pedido del
        # usuario 02-09-2026, «salen muy comprimidas»-. `canvas.size` ya
        # respeta la proporción real, porque `pil_image` la conserva con
        # `thumbnail`.
        image = ctk.CTkImage(light_image=canvas, dark_image=canvas, size=canvas.size)
        self._ctk_cache[key] = image
        return image

    def pil_image(self, category: str, size: int) -> Image.Image | None:
        """Devuelve una copia raster comprobable sin requerir una ventana Tk."""
        category = str(category or "")
        filename = CATEGORY_ICON_FILES.get(category)
        if filename is None:
            return None
        size = max(10, int(size))
        source = self._pil_cache.get(category)
        if source is None:
            path = self.folder / filename
            if not path.is_file():
                return None
            source = Image.open(path).convert("RGBA")
            self._pil_cache[category] = source
        fitted = source.copy()
        fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
        return fitted
