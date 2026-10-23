#!/usr/bin/env python3
"""devpip core + CLI: a pip-like package manager built on top of an installed Orwell Dev-C++.

Uses Dev-C++'s own MinGW-w64 compiler. Libraries come from MSYS2's prebuilt mingw64 packages
(the repo database also carries dependency info).

Two install modes:
  managed     -> ~/.devpip/prefix   (Dev-C++ untouched; you pass -I/-L flags, see `devpip flags`)
  integrated  -> Dev-C++'s MinGW64\\<triple>\\{include,lib}, so #include <zlib.h> just works
                 (you still add the -l flags; Program Files may need admin rights)

Requires: pip install zstandard
"""
import argparse, io, json, os, shutil, subprocess, sys, tarfile, urllib.request
from pathlib import Path

import zstandard

MIRROR = "https://mirror.msys2.org/mingw/mingw64/"
PKG_PREFIX = "mingw-w64-x86_64-"
HOME = Path(os.environ.get("DEVPIP_HOME", Path.home() / ".devpip"))
MANAGED = HOME / "prefix"
STATE = HOME / "installed.json"
CONFIG = HOME / "config.json"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# friendly name -> MSYS2 package, linker flags, extra include subdirs
REGISTRY = {
    "zlib":   {"pkg": "zlib",   "libs": ["-lz"]},
    "libpng": {"pkg": "libpng", "libs": ["-lpng"]},
    "curl":   {"pkg": "curl",   "libs": ["-lcurl"]},
    "glfw":   {"pkg": "glfw",   "libs": ["-lglfw3", "-lgdi32"]},
    "sdl2":   {"pkg": "SDL2",   "libs": ["-lmingw32", "-lSDL2main", "-lSDL2"], "inc": ["SDL2"]},
    "sfml":   {"pkg": "sfml",   "libs": ["-lsfml-graphics", "-lsfml-window", "-lsfml-system"]},
}
# the Dev-C++ compiler already provides these
SKIP_DEPS = ("gcc", "gcc-libs", "crt-git", "headers-git", "binutils", "libwinpthread-git")


class DevpipError(Exception):
    pass


log = print  # the GUI swaps this for a signal emitter


# ---------- config / state ----------
def _read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _write(path, data):
    HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_config():
    return _read(CONFIG)


def save_config(cfg):
    _write(CONFIG, cfg)


def load_state():
    return _read(STATE)


def save_state(s):
    _write(STATE, s)


# ---------- Dev-C++ detection ----------
def detect_devcpp():
    roots = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            for name in ("Dev-Cpp", "Dev-C++", "Embarcadero\\Dev-Cpp"):
                roots.append(Path(base) / name)
    roots += [Path("C:/Dev-Cpp"), Path("D:/Dev-Cpp")]
    for r in roots:
        if (r / "devcpp.exe").exists():
            return str(r)
    return None


def find_toolchain(root=None):
    root = root or load_config().get("devcpp") or detect_devcpp()
    if not root:
        raise DevpipError("Dev-C++ not found. Set its folder in Settings (the one containing devcpp.exe).")
    root = Path(root)
    cdir = next((root / s for s in ("MinGW64", "MinGW32", "MinGW") if (root / s / "bin" / "gcc.exe").exists()), None)
    if not cdir:
        raise DevpipError(f"No bundled MinGW (bin\\gcc.exe) found under {root}")
    gcc = cdir / "bin" / "gcc.exe"
    run = lambda *a: subprocess.run([str(gcc), *a], capture_output=True, text=True, creationflags=NOWIN).stdout.strip()
    machine, version = run("-dumpmachine"), run("-dumpversion")
    sysdir = cdir / machine
    if not sysdir.exists():
        sysdir = next(iter(cdir.glob("*-w64-mingw32")), None) or next(iter(cdir.glob("mingw32")), None)
    if not sysdir:
        raise DevpipError(f"Could not find the target folder ({machine}) inside {cdir}")
    return {"root": root, "cdir": cdir, "gcc": gcc, "gpp": cdir / "bin" / "g++.exe",
            "machine": machine, "version": version, "sysdir": sysdir, "is64": machine.startswith("x86_64")}


def toolchain_env(tc):
    env = dict(os.environ)
    env["PATH"] = str(tc["cdir"] / "bin") + os.pathsep + env.get("PATH", "")
    return env


# ---------- MSYS2 repo ----------
def fetch(url):
    log(f"  downloading {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def zstd_tar(data):
    return tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)), mode="r|")


_db = None
_provides = {}


def package_db():
    global _db
    if _db is not None:
        return _db
    HOME.mkdir(parents=True, exist_ok=True)
    raw = fetch(MIRROR + "mingw64.db")
    tf = zstd_tar(raw) if raw[:4] == b"\x28\xb5\x2f\xfd" else tarfile.open(fileobj=io.BytesIO(raw))
    strip = lambda d: d.split(">")[0].split("<")[0].split("=")[0]
    db = {}
    for m in tf:
        if not m.name.endswith("/desc"):
            continue
        fields, key = {}, None
        for line in tf.extractfile(m).read().decode().splitlines():
            if line.startswith("%") and line.endswith("%"):
                key = line.strip("%")
                fields[key] = []
            elif line and key:
                fields[key].append(line)
        name = fields["NAME"][0]
        db[name] = {"version": fields["VERSION"][0], "filename": fields["FILENAME"][0],
                    "depends": [strip(d) for d in fields.get("DEPENDS", [])]}
        for p in fields.get("PROVIDES", []):
            _provides[strip(p)] = name
    _db = db
    return db


def resolve(pkgname, seen, top=True):
    """Install order (dependencies first)."""
    db = package_db()
    pkgname = _provides.get(pkgname, pkgname) if pkgname not in db else pkgname
    if pkgname in seen:
        return []
    seen.add(pkgname)
    if pkgname not in db:
        if top:
            raise DevpipError(f"'{pkgname.removeprefix(PKG_PREFIX)}' not found in the MSYS2 mingw64 repo")
        log(f"  (skipping unknown dependency {pkgname})")
        return []
    order = []
    for dep in db[pkgname]["depends"]:
        if dep.startswith(PKG_PREFIX) and dep.removeprefix(PKG_PREFIX) not in SKIP_DEPS:
            order += resolve(dep, seen, top=False)
    return order + [pkgname]


# ---------- install / remove ----------
def dest_for(rel, mode, tc):
    top, rest = rel.parts[0], Path(*rel.parts[1:])
    if mode == "integrated":
        return tc["sysdir"] / top / rest if top in ("include", "lib") else tc["cdir"] / "bin" / rest
    return MANAGED / rel


def extract(data, mode, tc, owned):
    files = []
    tf = zstd_tar(data)
    for m in tf:
        if not m.isfile() or not m.name.startswith("mingw64/"):
            continue
        rel = Path(m.name).relative_to("mingw64")
        if rel.parts[0] not in ("include", "lib", "bin") or len(rel.parts) < 2:
            continue
        dest = dest_for(rel, mode, tc)
        if mode == "integrated" and dest.exists() and str(dest) not in owned:
            log(f"  keeping existing {dest.name} (not ours)")
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tf.extractfile(m).read())
        except PermissionError:
            raise DevpipError(f"Permission denied writing {dest}. Run as administrator, or switch to managed mode.")
        files.append(str(dest))
    return files


def install(names, mode=None):
    cfg = load_config()
    mode = mode or cfg.get("mode", "managed")
    tc = find_toolchain() if mode == "integrated" else None
    state = load_state()
    for name in names:
        entry = REGISTRY.get(name.lower())
        msys = PKG_PREFIX + (entry["pkg"] if entry else name)
        log(f"Installing {name} ({mode})")
        for pkg in resolve(msys, set()):
            info = package_db()[pkg]
            short = pkg.removeprefix(PKG_PREFIX)
            prev = state.get(short)
            if (prev and prev["version"] == info["version"] and prev.get("mode", "managed") == mode
                    and all(Path(f).exists() for f in prev["files"])):
                log(f"  {short} {info['version']} already installed ({mode})")
                continue
            if prev and prev.get("mode", "managed") != mode:
                log(f"  {short}: moving from {prev.get('mode', 'managed')} to {mode}")
            owned = {f for e in state.values() for f in e["files"]}
            files = extract(fetch(MIRROR + info["filename"]), mode, tc, owned)
            if prev:  # drop files from the old location/version that the new install doesn't reuse
                for f in set(prev["files"]) - set(files):
                    Path(f).unlink(missing_ok=True)
            state[short] = {"version": info["version"], "files": files,
                            "explicit": pkg == msys or bool(prev and prev["explicit"]), "mode": mode}
            save_state(state)
    log("Done.")


def remove(names):
    state = load_state()
    for name in names:
        entry = state.pop(name, None)
        if not entry:
            log(f"{name} is not installed")
            continue
        for f in entry["files"]:
            Path(f).unlink(missing_ok=True)
        log(f"Removed {name} (dependencies left in place)")
    save_state(state)


def search(query):
    """-> [(install_name, version, curated)]"""
    q = query.lower().strip()
    out = [(n, "", True) for n in REGISTRY if q in n]
    if q:
        db = package_db()
        curated_pkgs = {v["pkg"] for v in REGISTRY.values()}
        for n, e in sorted(db.items()):
            s = n.removeprefix(PKG_PREFIX)
            if n.startswith(PKG_PREFIX) and q in s.lower() and s not in curated_pkgs:
                out.append((s, e["version"], False))
    return out


# ---------- flags / build ----------
def compile_flags(tc=None):
    state = load_state()
    cflags, libs = [], []
    if any(e.get("mode", "managed") == "managed" for e in state.values()):
        cflags.append(f"-I{MANAGED / 'include'}")
        libs.append(f"-L{MANAGED / 'lib'}")
    for n, e in state.items():
        for sub in REGISTRY.get(n.lower(), {}).get("inc", []):
            base = tc["sysdir"] / "include" if e.get("mode") == "integrated" and tc else MANAGED / "include"
            cflags.append(f"-I{base / sub}")
        if e["explicit"]:
            libs += REGISTRY.get(n.lower(), {}).get("libs", [f"-l{n}"])
    return cflags, libs


def build(sources, output):
    tc = find_toolchain()
    cpp = any(Path(s).suffix.lower() in (".cpp", ".cc", ".cxx") for s in sources)
    c, l = compile_flags(tc)
    cmd = [str(tc["gpp"] if cpp else tc["gcc"]), *map(str, sources), "-o", str(output), *c, *l]
    r = subprocess.run(cmd, capture_output=True, text=True, env=toolchain_env(tc), creationflags=NOWIN)
    out_dir = Path(output).resolve().parent
    for e in load_state().values():
        for f in e["files"]:
            if f.lower().endswith(".dll"):
                shutil.copy2(f, out_dir)
    return cmd, r.returncode, (r.stdout + r.stderr).strip()


def doctor():
    tc = find_toolchain()
    return (f"Dev-C++:  {tc['root']}\ngcc:      {tc['gcc']}\ntarget:   {tc['machine']}\nversion:  {tc['version']}\n"
            + ("OK: 64-bit toolchain" if tc["is64"] else
               "WARNING: 32-bit compiler; devpip currently fetches 64-bit (mingw64) packages only."))


# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(prog="devpip")
    sub = p.add_subparsers(dest="cmd", required=True)
    for n in ("install", "remove"):
        s = sub.add_parser(n); s.add_argument("packages", nargs="+")
    sub.add_parser("search").add_argument("query")
    s = sub.add_parser("build"); s.add_argument("sources", nargs="+"); s.add_argument("-o", "--output", default="a.exe")
    for n in ("list", "flags", "doctor"):
        sub.add_parser(n)
    s = sub.add_parser("mode"); s.add_argument("mode", choices=["managed", "integrated"])
    a = p.parse_args()
    try:
        if a.cmd == "install": install(a.packages)
        elif a.cmd == "remove": remove(a.packages)
        elif a.cmd == "search":
            for n, v, cur in search(a.query): print(f"{n:30} {v} {'(curated)' if cur else ''}")
        elif a.cmd == "list":
            for n, e in sorted(load_state().items()): print(f"{n:20} {e['version']:12} {e.get('mode')}{'' if e['explicit'] else ' (dep)'}")
        elif a.cmd == "flags":
            c, l = compile_flags(find_toolchain()); print("Compiler:", " ".join(c)); print("Linker:  ", " ".join(l))
        elif a.cmd == "doctor": print(doctor())
        elif a.cmd == "mode": save_config({**load_config(), "mode": a.mode}); print("mode =", a.mode)
        elif a.cmd == "build":
            cmd, rc, out = build(a.sources, a.output); print(" ".join(cmd)); print(out); sys.exit(rc)
    except DevpipError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()