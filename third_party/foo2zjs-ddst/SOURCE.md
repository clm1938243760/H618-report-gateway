# OpenPrinting foo2zjs DDST decoder

This directory contains the complete source needed to build the isolated
Ricoh DDST decoder shipped with the gateway.

- Source package: Debian `foo2zjs 20200505dfsg0-3`
- Source: `https://sources.debian.org/src/foo2zjs/20200505dfsg0-3/`
- Source files: `ddstdecode.c`, `ddst.h`
- License: GNU GPL version 2 or later; see `COPYING`
- `ddstdecode.c` SHA-256: `2389ba36c01d47becac30d999f2a26f2fc878578a8b3ce0349c373552b881aef`
- `ddst.h` SHA-256: `d1980ab5557994a0d2a4fc629aabb47ce020f794178a7310ce3c31b7dc77cea2`

Ubuntu Noble's packaged `/usr/bin/ddstdecode` terminated with SIGSEGV while
decoding a complete Ricoh SP 112 stream produced by the matching PPD and
`foo2ddst-wrapper`. A separately hardened ARM64 build from the source above
decoded the same stream and the encoder smoke stream successfully. The gateway
therefore never invokes the distribution binary; it only uses the executable
installed at `/usr/local/libexec/jvlei-prn-decoders/ddstdecode`.

`bin/linux-arm64/ddstdecode` was built on the KICKPI K2B Ubuntu Noble test
board and linked against the system `libjbig.so.0`. Its SHA-256 is
`63f8154d45a1debd8c7ed68a1c23abaed1c18178cb3575ec490f0d5851646cd0`.

The decoder is a separate GPL command-line process. Product distribution must
preserve the corresponding source and license and still requires legal review.
