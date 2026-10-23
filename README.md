# devpip

**A `pip`-style package manager for [Orwell Dev-C++](https://sourceforge.net/projects/orwelldevcpp/).**

Installing a C/C++ library in Dev-C++ usually means hunting for a download, copying headers and `.a` files into the right folders, and working out linker flags. devpip does the first two steps for you:

```
devpip install zlib
```

It builds on top of the Dev-C++ you already have installed. It uses Dev-C++'s own bundled MinGW-w64 compiler and doesn't ship a compiler of its own.

> **Status: early / experimental.** It works for the libraries listed below on 64-bit Dev-C++. See [Limitations](#limitations) before relying on it.

---

## Features

- `install`, `remove`, `list`, `search`, `build`, `flags`, `doctor` commands
- Desktop GUI (PySide6, Catppuccin Mocha theme) with a package browser and a built-in code playground with syntax highlighting
- Automatic dependency resolution
- Two install modes: **managed** (leaves Dev-C++ untouched) or **integrated** (headers just work in the IDE)
- Uses your installed Dev-C++ compiler. Nothing else to configure.

## How it works

1. devpip finds your Dev-C++ folder and its bundled `MinGW64` toolchain.
2. It downloads prebuilt MinGW-w64 packages from the [MSYS2](https://www.msys2.org/) `mingw64` repository. The repo database also lists each package's dependencies, so devpip installs those too.
3. It extracts the headers (`include/`), libraries (`lib/`) and DLLs (`bin/`) and tracks every file it wrote, so `remove` can undo an install.
4. `devpip build` (or the GUI Playground) calls Dev-C++'s `g++` with the right `-I`, `-L` and `-l` flags and copies the runtime DLLs next to your executable.

devpip does not redistribute any library. Packages are fetched from the MSYS2 mirror, and each keeps its own license.

## Requirements

- Windows
- [Orwell Dev-C++](https://sourceforge.net/projects/orwelldevcpp/) with a **64-bit** bundled compiler (the default for recent versions)
- Python 3.9+

```
pip install PySide6 zstandard
```

(`zstandard` is needed for the CLI as well. `PySide6` is only needed for the GUI.)

## Quick start

```
git clone https://github.com/DanielAndersonCDS/devpip
cd devpip
pip install PySide6 zstandard
python devpip_gui.py
```

1. Open the **Settings** tab, set the Dev-C++ folder (the one containing `devcpp.exe`), choose an install mode, and click **Save**.
2. On the **Packages** tab, select a package (for example `zlib`) and click **Install selected**.
3. Use the **Playground** tab to compile and run a test program.

Or use the command line:

```
python devpip.py doctor            # check your Dev-C++ compiler
python devpip.py mode integrated   # or: managed
python devpip.py install zlib
python devpip.py build main.cpp -o main.exe
```

## Install modes

| Mode | Where files go | `#include <zlib.h>` in the IDE | Admin rights |
|------|----------------|--------------------------------|--------------|
| **managed** (default) | `%USERPROFILE%\.devpip\prefix` | Only after you add the include/lib folders in Dev-C++ | No |
| **integrated** | `<Dev-Cpp>\MinGW64\<triple>\{include,lib}` and `MinGW64\bin` | Works with no `-I`/`-L` flags | Usually, if Dev-C++ is in `Program Files` |

Integrated mode never overwrites a file it didn't install itself. Each package remembers which mode it was installed with, and reinstalling after a mode change moves it.

> Changing the mode in the GUI dropdown only takes effect after you click **Save**.

## Using packages inside the Dev-C++ IDE

devpip puts the headers and libraries in place, but Dev-C++ only links what it is told to. Add the link flags once per project:

**Project → Project Options → Parameters → Linker**, then paste the flags from `devpip flags`, for example:

```
-lz
```

(For a single file with no project: Tools → Compiler Options → Settings → Linker.)

In **managed** mode also add the include and library folders from `devpip flags` under Project Options → Directories.

## Supported packages

Curated entries, which include the right link flags:

| Name | Link flags |
|------|-----------|
| `zlib` | `-lz` |
| `libpng` | `-lpng` |
| `curl` | `-lcurl` |
| `glfw` | `-lglfw3 -lgdi32` |
| `sdl2` | `-lmingw32 -lSDL2main -lSDL2` |
| `sfml` | `-lsfml-graphics -lsfml-window -lsfml-system` |

`devpip search <text>` also lists any other package in the MSYS2 mingw64 repository. Those install, but you may need to work out the `-l` flags yourself.

To add a curated package, add an entry to `REGISTRY` in `devpip.py`:

```python
"mylib": {"pkg": "mylib", "libs": ["-lmylib"], "inc": ["subfolder"]},  # "inc" is optional
```

## Commands

| Command | What it does |
|---------|--------------|
| `install <pkg>...` | Install packages and their dependencies |
| `remove <pkg>...` | Remove a package's files (dependencies stay) |
| `list` | Show installed packages and their mode |
| `search <text>` | Search curated and MSYS2 packages |
| `flags` | Print compiler and linker flags for installed packages |
| `build <files> -o out.exe` | Compile with Dev-C++'s compiler plus your packages |
| `mode managed\|integrated` | Set the default install mode |
| `doctor` | Show the detected Dev-C++ compiler, target and version |

Set `DEVPIP_HOME` to store devpip's data (config, state, managed packages) somewhere other than `%USERPROFILE%\.devpip`.

## Troubleshooting

**`zlib.h: No such file or directory`**
The header isn't where the compiler looks. Make sure you installed in **integrated** mode (and clicked Save on the setting), or add the managed include folder in Project Options → Directories. Check that `<Dev-Cpp>\MinGW64\x86_64-w64-mingw32\include\zlib.h` exists.

**`undefined reference to 'inflate'` (or similar)**
The header was found but the library wasn't linked. Add the flags from `devpip flags` (for zlib, `-lz`) under Linker parameters.

**`Permission denied writing ...`**
Windows blocks writes to `Program Files`. Either run the GUI or CLI from an *administrator* Command Prompt, or give your user **Modify** rights on the Dev-C++ folder. If admin mode seems to lose your settings, set `DEVPIP_HOME` to your normal `.devpip` folder first.

**"already installed" but nothing works**
The package is probably installed in a different mode than you are using. Update to the latest version, switch mode, and install again.

**The program builds but fails to start (missing DLL)**
Copy the needed DLLs from `<Dev-Cpp>\MinGW64\bin` (integrated) or `%USERPROFILE%\.devpip\prefix\bin` (managed) next to your `.exe`. `devpip build` and the Playground do this automatically; the Dev-C++ IDE does not.

## Limitations

- **64-bit only.** devpip fetches 64-bit packages. `devpip doctor` warns you if your Dev-C++ compiler is 32-bit.
- **C libraries are the safe choice.** MSYS2 builds with a newer GCC than the one bundled with Dev-C++. Plain C libraries are fine. C++ libraries can hit ABI mismatches and fail to link.
- **Link flags aren't automatic in the IDE.** Dev-C++'s own settings file isn't edited yet.
- `remove` leaves dependencies in place.
- Relies on the MSYS2 `mingw64` repository staying available.

## Roadmap

- A registry file (`devpip.json`) instead of a hardcoded list
- An "Apply to Dev-C++" button that writes link flags into the IDE settings
- Orphaned-dependency cleanup on `remove`
- Package pinning and version selection
- A 32-bit package source

## Contributing

Issues and pull requests are welcome, especially new curated packages (with tested link flags) and reports from different Dev-C++ versions.

## License

Choose a license for the repository and add it here (MIT is a common choice for tools like this).

## Credits

- [Orwell Dev-C++](https://sourceforge.net/projects/orwelldevcpp/) for the IDE devpip builds on
- [MSYS2](https://www.msys2.org/) for the prebuilt MinGW-w64 packages
- [Catppuccin](https://github.com/catppuccin/catppuccin) for the Mocha palette
