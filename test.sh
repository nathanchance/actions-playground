#!/usr/bin/env bash

set -eux

mount
df -HT

curl -LOSs https://builds.tuxbuild.com/27SRt2AJZWsh6WklUTrD4wsEs8I/linux
chmod 0755 vmlinux

git clone --depth=1 https://github.com/ClangBuiltLinux/boot-utils

boot-utils/boot-uml.sh -k linux
