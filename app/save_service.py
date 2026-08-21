from __future__ import annotations
import hashlib, os, shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
@dataclass(slots=True)
class SaveInfo:
    path: Path
    size: int
    sha256: str
    display_type: str
class SaveService:
    def inspect(self, path: str | Path) -> SaveInfo:
        p=Path(path).expanduser().resolve()
        if not p.is_file(): raise FileNotFoundError("El archivo seleccionado no existe.")
        size=p.stat().st_size
        if size == 0: raise ValueError("El archivo está vacío.")
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        display={".bin":"Guardado binario",".sav":"Guardado SAV",".dat":"Guardado DAT",".dsv":"Guardado DeSmuME"}.get(p.suffix.lower(),"Guardado sin formato reconocido por extensión")
        return SaveInfo(p,size,digest,display)
    def create_backup(self, info: SaveInfo, backup_root: Path) -> Path:
        backup_root.mkdir(parents=True,exist_ok=True)
        ts=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest=backup_root/f"{info.path.stem or 'save'}_{ts}{info.path.suffix}.backup"
        shutil.copy2(info.path,dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=info.sha256:
            dest.unlink(missing_ok=True); raise IOError("La copia de seguridad no coincide con el original.")
        return dest
    def create_visible_previous_copy(self, info: SaveInfo) -> Path:
        """Crea junto al guardado una copia fechada del archivo activo anterior."""
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base = info.path.with_name(f"{info.path.stem}_anterior_{ts}{info.path.suffix}")
        dest = base
        counter = 2
        while dest.exists():
            dest = info.path.with_name(
                f"{info.path.stem}_anterior_{ts}_{counter}{info.path.suffix}"
            )
            counter += 1
        shutil.copy2(info.path, dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != info.sha256:
            dest.unlink(missing_ok=True)
            raise IOError("La copia visible del guardado anterior no coincide con el original.")
        return dest

    def replace_active_save(self, prepared: Path, active: Path, previous_copy: Path, restore_on_failure: bool = True) -> SaveInfo:
        """Sustituye de forma atómica el guardado activo.

        Para .dsv bloqueados por DeSmuME, restore_on_failure=False conserva el
        archivo preparado para instalarlo durante la ventana de Reset.
        """
        prepared = prepared.resolve()
        active = active.resolve()
        previous_copy = previous_copy.resolve()
        if not prepared.is_file():
            raise FileNotFoundError("No existe el guardado preparado que se iba a instalar.")
        try:
            os.replace(prepared, active)
            installed = self.inspect(active)
            if installed.size == 0:
                raise IOError("El guardado instalado está vacío.")
            return installed
        except Exception:
            # La copia visible se conserva. Solo restauramos cuando la llamada
            # pretendía una sustitución inmediata; un bloqueo de DeSmuME deja
            # intacto el original y el preparado se reutiliza durante Reset.
            if restore_on_failure and previous_copy.is_file():
                shutil.copy2(previous_copy, active)
            raise

