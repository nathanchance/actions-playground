#!/usr/bin/env python3

from pathlib import Path
import subprocess
from urllib.request import urlretrieve

def run(cmd):
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    workdir = Path(__file__).resolve().parent
    run(["mount"])
    run(["df", "-HT"])

    kernel_image = workdir.joinpath("linux")
    urlretrieve("https://builds.tuxbuild.com/27SRt2AJZWsh6WklUTrD4wsEs8I/linux", kernel_image)
    os.chmod(kernel_image, 0o755)

    boot_utils = workdir.joinpath("boot-utils")
    run(["git", "clone", "--depth", "1", https://github.com/ClangBuiltLinux/boot-utils, boot_utils])

    run([boot_utils.joinpath("boot-uml.sh"), "-k", kernel_image])
