#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Install arc and Mercurial the way Firefox's Updatebot Docker image does, so
tests/real_arc.py can run Updatebot against the real arc.

The recipe is read from Firefox rather than copied here, so it can't drift from
the image: the arcanist revision and Mozilla's patches to it from
taskcluster/docker/updatebot/privileged-setup.sh, the evolve extension from
evolve-requirements.txt next to it, and the Mercurial version from the Debian
package the image's base installs (taskcluster/kinds/packages/debian.yml). It also
saves Firefox's .arcconfig as DEST/arcconfig, since it changes how arc behaves (for
one, it makes arc amend the commits it submits).

    setup_real_arc.py DEST [--firefox CHECKOUT | --firefox-ref REF] [--python PYTHON]

By default it reads Firefox's main branch from GitHub. Use --firefox to test an
image change that hasn't landed. DEST must be new, empty, or an earlier install by
this script, which it replaces. Afterwards, put DEST/bin first on your PATH.
arc also needs php with the curl extension (Debian/Ubuntu: php-cli php-curl).
Mercurial is installed with --python (default: this one), which must be a version
that Mercurial release supports; the image runs it on Debian 12's Python 3.11.
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
import urllib.request

FIREFOX_RAW = "https://raw.githubusercontent.com/mozilla-firefox/firefox/%s/%s"
IMAGE_DIR = "taskcluster/docker/updatebot/"
ARCANIST_REPO = "https://github.com/phacility/arcanist.git"
# Marks a directory as one this script installed into, so it can safely replace it
MARKER = ".setup_real_arc"


def read_firefox_file(args, path):
    if args.firefox:
        with open(os.path.join(args.firefox, path)) as f:
            return f.read()
    with urllib.request.urlopen(FIREFOX_RAW % (args.firefox_ref, path), timeout=60) as r:
        return r.read().decode()


def one(pattern, text, what):
    found = set(re.findall(pattern, text))
    if len(found) != 1:
        sys.exit("Expected one %s in Firefox's Updatebot image, found %s. Has the image's setup changed?" % (what, sorted(found) or "none"))
    return found.pop()


def run(*args, **kwargs):
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dest")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--firefox", help="read the image's recipe from this Firefox checkout")
    source.add_argument("--firefox-ref", default="main", help="read it from this branch or commit on GitHub (default: main)")
    parser.add_argument("--python", default=sys.executable, help="the Python to install Mercurial with")
    args = parser.parse_args()

    setup = read_firefox_file(args, IMAGE_DIR + "privileged-setup.sh")
    arcanist_revision = one(r"git clone %s\s+cd arcanist\s+git checkout ([0-9a-f]{40})" % re.escape(ARCANIST_REPO), setup, "arcanist revision")
    patches = re.findall(r"^git apply /setup/(arcanist_[\w.-]+\.patch)$", setup, re.MULTILINE)
    if not patches:
        sys.exit("Found no arcanist patches in Firefox's Updatebot image. Has the image's setup changed?")
    evolve = read_firefox_file(args, IMAGE_DIR + "evolve-requirements.txt")
    mercurial_version = one(r"mercurial-([\d.]+)\.tar\.gz", read_firefox_file(args, "taskcluster/kinds/packages/debian.yml"), "Mercurial version")

    dest = os.path.abspath(args.dest)
    if os.path.isdir(dest) and os.listdir(dest):
        if not os.path.exists(os.path.join(dest, MARKER)):
            sys.exit("%s isn't empty, and wasn't made by this script, so I won't replace it. Pick a new or empty directory." % dest)
        shutil.rmtree(dest)
    os.makedirs(os.path.join(dest, "bin"))
    open(os.path.join(dest, MARKER), "w").close()

    arcanist = os.path.join(dest, "arcanist")
    run("git", "clone", "--quiet", ARCANIST_REPO, arcanist)
    run("git", "-C", arcanist, "checkout", "--quiet", arcanist_revision)
    for patch in patches:
        run("git", "-C", arcanist, "apply", "-", input=read_firefox_file(args, IMAGE_DIR + patch).encode())

    venv = os.path.join(dest, "mercurial")
    run(args.python, "-m", "venv", venv)
    pip = os.path.join(venv, "bin", "pip")
    run(pip, "install", "--quiet", "mercurial==" + mercurial_version)
    with open(os.path.join(dest, "evolve-requirements.txt"), "w") as f:
        f.write(evolve)
    run(pip, "install", "--quiet", "--no-deps", "--require-hashes", "-r", os.path.join(dest, "evolve-requirements.txt"))

    with open(os.path.join(dest, "arcconfig"), "w") as f:
        f.write(read_firefox_file(args, ".arcconfig"))

    os.symlink(os.path.join(arcanist, "bin", "arc"), os.path.join(dest, "bin", "arc"))
    os.symlink(os.path.join(venv, "bin", "hg"), os.path.join(dest, "bin", "hg"))
    print("Installed arcanist %s with %s, and Mercurial %s with evolve, in %s" % (
        arcanist_revision[:12], ", ".join(patches), mercurial_version, os.path.join(dest, "bin")))


if __name__ == "__main__":
    main()
