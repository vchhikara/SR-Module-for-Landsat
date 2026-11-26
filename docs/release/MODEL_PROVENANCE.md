# Model provenance

This record separates verified facts from open questions. It is not legal advice.

## Verified (2026-11-26)

- The plugin accepts only `real_hat_64.onnx` with SHA-256
  `3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908`.
- The upstream project `github.com/XPixelGroup/HAT` reports the Apache-2.0 license for its repository.
- Its README describes a "sharper" Real-HAT GAN model.

## Added on 2026-11-27

- **Checkpoint named by the 0.6.3 release.** `third_party/NOTICE.md` in
  `landsat_sr_0.6.3_windows_offline.zip` says that the ONNX file was exported from
  `Real_HAT_GAN_sharper.pth`, SHA-256
  `5800b67136006eb8cab3b4ed7c8d73b6a195bb18e6cc709b674f9aa069c00271`.
- **Public copy.** The file list of [Acly/hat](https://huggingface.co/Acly/hat) (revision `8403819b`)
  gives the same SHA-256 for `Real_HAT_GAN_sharper.pth`. Its model card has the tag `apache-2.0`. The card
  calls itself a mirror and links to a
  [Google Drive folder](https://drive.google.com/drive/folders/1HpmReFfoUqUbnAOQ7rvOeNU3uf_m69w0) for the
  original weights. The upstream README links to the same folder. The checkpoint was not downloaded, and
  the copy in that folder was not compared.
- **Upstream license.** GitHub reports Apache-2.0 for `XPixelGroup/HAT`.
- **Export data in the ONNX file.** Producer PyTorch 2.6.0, IR version 8, opset 17. The file has no other
  metadata.
- **Runtime versions.** Python 3.12.10, NumPy 2.2.6, ONNX Runtime DirectML 1.23.0. `DirectML.dll` reports
  file version 1.15.4.

## Not verified

- That the ONNX file was made from that checkpoint. Only the 0.6.3 notice says so.
- The conversion script and settings. They are not in this repository or its history.
- Whether the Apache-2.0 license of the upstream repository covers the published weights. The tag on a
  mirror is not a grant from the authors.
- Terms of the data that trained the weights.
- The right to redistribute the converted ONNX file.
- Author and license of `landsat_sr/icon.png` and `docs/images/banner.png`.

## To close the record

| Step | State on 2026-11-27 |
|---|---|
| 1. Name the source checkpoint, its download address and its SHA-256 | Recorded above, from the 0.6.3 notice. The hash matches the public mirror |
| 2. Commit the conversion script. Record the versions of the tools | Open. No script was found. Only the PyTorch version and opset are known |
| 3. Convert again. Compare the numeric output with the shipped model | Open. It needs step 2 or a new script, the checkpoint and PyTorch |
| 4. Record the license grant for the weights | Open. No grant for the weights from the authors was found or recorded |
| 5. Copy `rights-record.template.json`. Complete every field. Add one notice file for each component | Open. A draft with versions, sources and notice files is kept outside the repository, next to the runtime. The owner has not confirmed redistribution |

The offline package builder refuses a distributable build until step 5 is complete. It refused the draft,
because `redistribution_confirmed`, `confirmed_by` and `confirmed_on` are empty. It checks that the
record is complete. It cannot check that the statements are true.

An internal test build has no `third_party` license files. The 0.6.3 package had them. A build with a
completed rights record adds the notice files under `licenses/`.
