# Model provenance

This record separates verified facts from open questions. It is not legal advice.

## Verified (2026-11-26)

- The plugin accepts only `real_hat_64.onnx` with SHA-256
  `3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908`.
- The upstream project `github.com/XPixelGroup/HAT` reports the Apache-2.0 license for its repository.
- Its README describes a "sharper" Real-HAT GAN model.

## Not verified

- Which checkpoint `real_hat_64.onnx` was converted from.
- The conversion script, tool versions and settings. This repository has none.
- Whether the license of the upstream repository covers the published weights.
- Terms of the data that trained the weights.
- The right to redistribute the converted ONNX file.
- Author and license of `landsat_sr/icon.png` and `docs/images/banner.png`.

## To close the record

1. Name the source checkpoint, its download address and its SHA-256.
2. Commit the conversion script. Record the versions of the tools.
3. Convert again. Compare the numeric output with the shipped model.
4. Record the license grant for the weights.
5. Copy `rights-record.template.json`. Complete every field. Add one notice file for each component.

The offline package builder refuses a distributable build until step 5 is complete. It checks that the
record is complete. It cannot check that the statements are true.
