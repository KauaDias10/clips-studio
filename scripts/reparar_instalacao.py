"""Confere e conserta a instalacao a partir do codigo (instalar.bat / iniciar.bat).

Dois defeitos ja aconteceram de verdade num PC e deixavam o app sem abrir:

1. O Electron nao era extraido. O `npm install` baixa o zip do Electron e o
   extrai num passo de pos-instalacao; com Node novo (22+) esse passo pode
   terminar calado no meio, sem erro, e o `npm run dev` falha com
   "Electron uninstall". Aqui o zip e baixado (ou pego do cache do Electron),
   conferido pelo checksum oficial e extraido com o Python.

2. Pacotes Python corrompidos dentro da .venv: arquivos .py cheios de bytes
   nulos depois de uma instalacao interrompida (PC desligou, disco cheio,
   antivirus). O backend quebra com "source code string cannot contain null
   bytes". Aqui cada pacote afetado e reinstalado.

So usa a biblioteca padrao, para rodar mesmo com a .venv quebrada.

E, antes de instalar, confere se o caminho da pasta cabe no limite de 260
letras do Windows (--checar-pasta): o torch tem arquivos muito fundos.

Uso:  python scripts/reparar_instalacao.py [--so-electron | --so-python | --checar-pasta]
Sai com codigo 0 quando tudo esta certo (ou foi consertado), 1 se nao deu.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELECTRON = ROOT / "ui" / "node_modules" / "electron"
VENV = ROOT / ".venv"
SITE = VENV / "Lib" / "site-packages"
VENV_PY = VENV / "Scripts" / "python.exe"


# ---------------------------------------------------------------- Electron
def _arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "ia32" if machine in ("x86", "i386", "i686") else "x64"


def _electron_ok(version: str) -> bool:
    try:
        return ((ELECTRON / "dist" / "version").read_text("utf-8").strip().lstrip("v") == version
                and (ELECTRON / "path.txt").read_text("utf-8") == "electron.exe"
                and (ELECTRON / "dist" / "electron.exe").is_file())
    except OSError:
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _cached_zip(name: str) -> Path | None:
    """O mesmo zip que o `npm install` ja baixou, para nao baixar 100 MB de novo."""
    roots = [os.environ.get("electron_config_cache"), os.environ.get("LOCALAPPDATA") and
             str(Path(os.environ["LOCALAPPDATA"]) / "electron" / "Cache")]
    for root in filter(None, roots):
        for found in Path(root).glob(f"*/{name}"):
            return found
    return None


def _download(url: str, dest: Path) -> None:
    print(f"      baixando {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "clips-kitty-installer"})
    with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -10
        while block := r.read(1 << 20):
            f.write(block)
            done += len(block)
            if total and (pct := done * 100 // total) >= shown + 10:
                shown = pct
                print(f"      {pct}%", flush=True)


def reparar_electron() -> bool:
    pkg = ELECTRON / "package.json"
    if not pkg.is_file():
        print("[ERRO] ui\\node_modules\\electron nao existe: rode o instalar.bat (npm install).")
        return False
    version = json.loads(pkg.read_text("utf-8"))["version"]
    if _electron_ok(version):
        print(f"[ok] Electron {version}")
        return True

    print(f"[..] Electron {version} nao esta extraido: consertando")
    name = f"electron-v{version}-win32-{_arch()}.zip"
    try:
        expected = json.loads((ELECTRON / "checksums.json").read_text("utf-8")).get(name)
    except (OSError, ValueError):
        expected = None

    tmp_dir = Path(tempfile.mkdtemp(prefix="electron-"))
    try:
        zip_path = _cached_zip(name)
        if zip_path is None or (expected and _sha256(zip_path) != expected):
            zip_path = tmp_dir / name
            _download(f"https://github.com/electron/electron/releases/download/v{version}/{name}", zip_path)
        if expected and _sha256(zip_path) != expected:
            print("[ERRO] o zip do Electron baixado nao confere com o checksum oficial. Tente de novo.")
            return False

        dist = ELECTRON / "dist"
        shutil.rmtree(dist, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dist)
        types = dist / "electron.d.ts"
        if types.exists():
            os.replace(types, ELECTRON / "electron.d.ts")
        (ELECTRON / "path.txt").write_text("electron.exe", "utf-8")
    except Exception as e:  # rede, disco, zip ruim: diga o que foi
        print(f"[ERRO] nao deu para instalar o Electron: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if _electron_ok(version):
        print(f"[ok] Electron {version} consertado")
        return True
    print("[ERRO] o Electron continua incompleto depois da extracao.")
    return False


# ---------------------------------------------------------------- Python
def _corrompidos() -> set[str]:
    bad = set()
    for p in SITE.rglob("*.py"):
        try:
            if b"\x00" in p.read_bytes():
                bad.add(os.path.normcase(str(p.resolve())))
        except OSError:
            bad.add(os.path.normcase(str(p.resolve())))
    return bad


def _pacotes_de(bad: set[str]) -> tuple[set[str], set[str]]:
    """Os pacotes (nome==versao) donos dos arquivos ruins, pelo RECORD de cada um.
    Devolve tambem os arquivos que nenhum pacote reclama."""
    owners, claimed = set(), set()
    for info in SITE.glob("*.dist-info"):
        try:
            rows = list(csv.reader((info / "RECORD").read_text("utf-8", errors="replace").splitlines()))
        except OSError:
            continue
        hits = {os.path.normcase(str((SITE / r[0]).resolve())) for r in rows if r} & bad
        if hits:
            name, version = info.name[: -len(".dist-info")].rsplit("-", 1)
            owners.add(f"{name}=={version}")
            claimed |= hits
    return owners, bad - claimed


def reparar_python() -> bool:
    if not VENV_PY.is_file() or not SITE.is_dir():
        print("[ERRO] a pasta .venv nao existe: rode o instalar.bat.")
        return False
    bad = _corrompidos()
    if not bad:
        print("[ok] bibliotecas Python")
        return True

    owners, orphans = _pacotes_de(bad)
    print(f"[..] {len(bad)} arquivos Python corrompidos em {len(owners)} pacotes: reinstalando")
    if owners:
        cmd = [str(VENV_PY), "-m", "pip", "install", "--force-reinstall", "--no-deps",
               "--no-cache-dir", "--disable-pip-version-check", *sorted(owners)]
        if subprocess.call(cmd) != 0:
            print("[ERRO] a reinstalacao dos pacotes falhou (veja acima).")
            return False
    left = _corrompidos()
    if left:
        print(f"[ERRO] ainda ha {len(left)} arquivos corrompidos, por exemplo {sorted(left)[0]}")
        if orphans:
            print("       Apague a pasta .venv e rode o instalar.bat de novo.")
        return False
    print("[ok] bibliotecas Python consertadas")
    return True


# ---------------------------------------------------------------- caminho
# O torch instala um arquivo de licenca com um caminho de ~151 letras abaixo da
# pasta do projeto (.venv\Lib\site-packages\torch-*.dist-info\licenses\...).
# Sem "caminhos longos" ligados no Windows, o limite e 260 letras e o pip para
# no meio com "No such file or directory". Folga para versoes futuras.
LONGEST_INSIDE = 165
WINDOWS_LIMIT = 259


def _long_paths_on() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return winreg.QueryValueEx(k, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def checar_pasta() -> bool:
    if os.name != "nt" or _long_paths_on():
        return True
    room = WINDOWS_LIMIT - LONGEST_INSIDE
    if len(str(ROOT)) <= room:
        return True
    print(f"[ERRO] O caminho desta pasta e longo demais para o Windows ({len(str(ROOT))} letras, maximo {room}):")
    print(f"       {ROOT}")
    print("       Mova a pasta para um lugar mais curto, por exemplo C:\\clips-studio, e rode de novo.")
    print("       (Ou ligue os caminhos longos do Windows, como administrador, no PowerShell:")
    print("        New-ItemProperty -Path HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem "
          "-Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force )")
    return False


def main(argv: list[str]) -> int:
    if "--checar-pasta" in argv:
        return 0 if checar_pasta() else 1
    ok = True
    if "--so-python" not in argv:
        ok &= reparar_electron()
    if "--so-electron" not in argv:
        ok &= reparar_python()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
