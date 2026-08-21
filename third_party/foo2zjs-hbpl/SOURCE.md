# OpenPrinting foo2zjs HBPL decoder

This directory contains the source needed to build the isolated HBPL v1/v2
decoder used by the report gateway.

- Upstream: `https://github.com/OpenPrinting/foo2zjs`
- Branch: `main-fixes`
- Commit: `b917a495f7b8adb1793e1b689379fdc4044b0ced`
- Source file: `hbpldecode.c`
- License: GNU GPL version 2 or later; see `COPYING`

The Ubuntu Noble package's `hbpldecode` crashed on a valid synthetic HBPL v2
stream during H618 testing. The source at the pinned upstream commit decoded
the same stream successfully. The gateway therefore never invokes
`/usr/bin/hbpldecode`; it only uses the separately built executable at
`/usr/local/libexec/jvlei-prn-decoders/hbpldecode`.

The decoder is a separate command-line process. Its complete corresponding
source and license are retained here for offline builds and redistribution
review. Product distribution must preserve these files and comply with the
GPL. Legal review remains required before commercial release.

`bin/linux-arm64/hbpldecode` is the ARM64 executable built from the pinned
source on the KICKPI K2B Ubuntu Noble test board and linked against the system
`libjbig.so.0`. Its SHA-256 is
`25c2f178941f1f88bf5cfc87cdec36f05372ecbf7b8fd240ed00d2ce093251e5`.
The company update package includes both this executable and its corresponding
source so installation remains fully offline.
