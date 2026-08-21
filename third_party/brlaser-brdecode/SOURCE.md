# brlaser Brother HBP decoder

This directory contains the source used to build the isolated Brother
HBP/XL2HB decoder for the report gateway.

- Upstream: `https://github.com/pdewacht/brlaser`
- Branch: `master`
- Commit: `2a49e3287c70c254e7e3ac9dabe9d6a07218c3fa`
- Source file: `src/brdecode.cc`
- Unmodified upstream source SHA-256: `0b9cf03429eb22fb56ed385d06bc6703f00a3b4a076dab5e5aa316490bfbbd92`
- Resource-limited vendored source SHA-256: `da9b306f41b25bab02ca53f347938213e493e69e1400c5822957aca9741f65eb`
- License: GNU GPL version 2 or later
- Complete GPL v2 text: `../foo2zjs-hbpl/COPYING`

`brdecode` is the reverse diagnostic utility shipped in the brlaser source
tree. It converts the compressed monochrome stream emitted for HBP and XL2HB
printers into PBM pages. The gateway runs it as a separate command-line
process and then converts the PBM pages to PDF.

The vendored source adds only two resource guards around the upstream parser:
at most 20,000 raster lines per page and at most 100 pages per job. The limits
prevent malformed captured streams from consuming unbounded memory or disk.

The ARM64 executable is built from this pinned source on the KICKPI K2B Ubuntu
Noble test board. Its SHA-256 is
`48fc35456f4be5eb61014e6b584a336637ed28bdfbd66a25a6926a5a1ecf8d27`.
Product distribution must retain the source and GPL license and complete a
legal review before commercial release.
