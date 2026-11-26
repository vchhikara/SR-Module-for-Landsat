# Third-party components

The plugin source is GPL-3.0-or-later. The repository ZIP contains no third-party code or binaries.

## Components that a separate runtime package uses

| Component | Role | License reported upstream | Where this was read (2026-11-26) |
|---|---|---|---|
| Python | Runs the worker | Python Software Foundation License | Not re-read for this release |
| NumPy | Arrays | BSD | Package metadata of NumPy |
| ONNX Runtime | Inference | MIT | Package metadata of onnxruntime |
| DirectML | GPU inference | The GitHub repository reports MIT. The redistributable DLL package can carry its own terms. Check the license file of the exact package that you ship. | github.com/microsoft/DirectML |
| HAT (model design and weights) | Model | Apache-2.0 for the repository | github.com/XPixelGroup/HAT |

This table is not a redistribution grant and not legal advice. See `docs/release/MODEL_PROVENANCE.md`
in the source repository.

## Assets

`icon.png` and the repository banner have no recorded author or license yet.
