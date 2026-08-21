# OpenPrinting foo2zjs SLX decoder

This directory contains the complete source needed to build the isolated
Lexmark SLX decoder shipped with the gateway.

- Source package: Debian `foo2zjs 20200505dfsg0-3`
- Source: `https://sources.debian.org/src/foo2zjs/20200505dfsg0-3/`
- Source files: `slxdecode.c`, `slx.h`
- License: GNU GPL version 2 or later; see `COPYING`
- `slxdecode.c` SHA-256: `4032f2ea95b5c61ed7093b9c9b801976988cb474b0257f94ab6664db6ac28b29`
- `slx.h` SHA-256: `e40822ddae7e8a9e4def5158f62844c5740e067527e8f0f01a05f978977d25ff`

Ubuntu Noble's packaged `/usr/bin/slxdecode` omitted the fourth (yellow) plane
from a complete color Lexmark C500 stream even though the extracted JBIG plane
was valid. A separately hardened ARM64 build from the unmodified source above
decoded all four planes. The gateway therefore only uses the executable at
`/usr/local/libexec/jvlei-prn-decoders/slxdecode`.

`bin/linux-arm64/slxdecode` was built on the KICKPI K2B Ubuntu Noble test board
and linked against the system `libjbig.so.0`. Its SHA-256 is
`03eaa5afb30e78220f941aa7ee0b02224e2b4813d8504f2bc73167c1aa3b7665`.

The decoder is a separate GPL command-line process. Product distribution must
preserve the corresponding source and license and still requires legal review.
