# Third-party notices

This project's own code is MIT licensed (see `LICENSE`). It bundles no third-party
code. The dependencies below are installed separately by the user and keep their
own licenses.

## CodeWalker

<https://github.com/dexyfex/CodeWalker>

`tools/GtavScout.Extract` references `CodeWalker.Core` as a project reference,
located at build time through the `CODEWALKER_PATH` environment variable. No
CodeWalker source is vendored into this repository, and no CodeWalker binary is
distributed with it. Consult the CodeWalker repository for its own terms before
redistributing anything built against it.

## Sollumz

<https://github.com/Sollumz/Sollumz> — GPL-3.0-or-later

The Blender renderer calls Sollumz's import operator. Sollumz is installed by the
user into their own Blender and is not bundled, modified or redistributed here.

## Python dependencies

Pillow and NumPy are required; `sentence-transformers` is an optional extra for
semantic search, which downloads model weights from Hugging Face on first use.
Their licenses apply as published.

## Game data

No GTA V binaries, archives, models, textures, decoded pixels, catalogue databases
or reviewed annotation datasets are included in this repository, and none may be
committed to it. The tool reads a local, legitimately obtained installation and
writes metadata and locally rendered evidence outside it.

Not affiliated with, endorsed by, or sponsored by Rockstar Games or Take-Two
Interactive.
