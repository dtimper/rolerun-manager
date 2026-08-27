from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image


ROLE_ICON_FILES = {
    "Líbero": "libero.png",
    "Asesino": "asesino.png",
    "Mago": "mago.png",
    "Tanque": "tanque.png",
    "Prisma": "prisma.png",
    "Support": "support.png",
}


class RoleIconProvider:
    """Convierte las siluetas aportadas por el usuario en iconos dorados.

    El alfa del PNG es la única máscara autoritativa. No se infiere la figura
    desde RGB (Prisma es deliberadamente casi negro) ni se altera el original.
    """

    def __init__(self, folder: Path, color: str) -> None:
        self.folder = Path(folder)
        value = str(color).lstrip("#")
        self.color = tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        self._pil_cache: dict[str, Image.Image] = {}
        self._ctk_cache: dict[tuple[str, int], ctk.CTkImage] = {}

    def image(self, role: str, size: int) -> ctk.CTkImage | None:
        canvas = self.pil_image(role, size)
        if canvas is None:
            return None
        role = str(role or "")
        size = max(12, int(size))
        key = (role, size)
        cached = self._ctk_cache.get(key)
        if cached is not None:
            return cached
        image = ctk.CTkImage(light_image=canvas, dark_image=canvas, size=(size, size))
        self._ctk_cache[key] = image
        return image

    def pil_image(self, role: str, size: int) -> Image.Image | None:
        """Devuelve una copia raster comprobable sin requerir una ventana Tk."""
        role = str(role or "")
        filename = ROLE_ICON_FILES.get(role)
        if filename is None:
            return None
        size = max(12, int(size))
        source = self._pil_cache.get(role)
        if source is None:
            path = self.folder / filename
            if not path.is_file():
                return None
            raw = Image.open(path).convert("RGBA")
            alpha = raw.getchannel("A")
            bounds = alpha.getbbox()
            if bounds is None:
                return None
            source = raw.crop(bounds).getchannel("A")
            self._pil_cache[role] = source
        fitted_alpha = source.copy()
        fitted_alpha.thumbnail((size, size), Image.Resampling.LANCZOS)
        fitted = Image.new("RGBA", fitted_alpha.size, (*self.color, 255))
        fitted.putalpha(fitted_alpha)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
        return canvas
