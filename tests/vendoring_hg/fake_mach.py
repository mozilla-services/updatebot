#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
A stand-in for `./mach vendor`, copied into a test Mercurial repository as `mach`.

It implements the three commands Updatebot runs, the way mozbuild's vendoring
code behaves, using real Mercurial operations:

  ./mach vendor --check-for-update <yaml>
      Prints the newest upstream revision and a timestamp.
  ./mach vendor <yaml> --revision <rev> [--patch-mode none]
      Replaces the vendored files (except 'keep' ones) with upstream snapshot
      <rev>, stages added and removed files, exits 254 if nothing changed
      (ignoring 'generated' files), and otherwise records <rev> in the moz.yaml.
      Like mach, it never applies the patches here.
  ./mach vendor --patch-mode only <yaml>
      Applies the local patches, then runs the 'post-patch' scripts.

Upstream snapshots are directories in $FAKE_UPSTREAM, one per revision, and
$FAKE_UPSTREAM/latest names the newest revision.

The moz.yaml is a small subset of the real format:
  revision: <rev>
  patches: <file> [<file> ...]      (optional, relative to the moz.yaml's directory)
  generated: <file> [<file> ...]    (optional)
  keep: <file> [<file> ...]         (optional; in-tree files that aren't from upstream)
  post-patch: <script> [<script> ...]
      (optional; like a 'run-script' post-patch action with cwd '{yaml_dir}':
      run after the patches, and a failing script fails mach)
"""

import os
import shutil
import subprocess
import sys
import tempfile

KEPT_FILES = ("moz.yaml", "patches")  # in-tree files that aren't part of the upstream snapshot


def read_manifest(yaml_path):
    manifest = {"patches": [], "generated": [], "keep": [], "post-patch": []}
    with open(yaml_path) as f:
        for line in f:
            key, _, value = line.partition(":")
            if key.strip() in ("patches", "generated", "keep", "post-patch"):
                manifest[key.strip()] = value.split()
            elif key.strip() == "revision":
                manifest["revision"] = value.strip()
    return manifest


def apply_patches(vendor_dir, manifest):
    # The same patch options as mozbuild's import_local_patches, including sending
    # rejects to a temporary file rather than leaving .rej files in the tree.
    for p in manifest["patches"]:
        with tempfile.NamedTemporaryFile(suffix=".rej") as reject:
            ret = subprocess.run(["patch", "-r", reject.name, "-p1", "--directory", vendor_dir,
                                  "--input", os.path.abspath(os.path.join(vendor_dir, p)),
                                  "--no-backup-if-mismatch", "--batch", "--forward"])
        if ret.returncode:
            # What mozbuild logs for any patch that fails to apply (and not for a
            # failed post-patch action); Updatebot looks for it to spot conflicts.
            print("Could not apply %s, possible reasons:" % p)
            print(" - The library update has modified the files so the patch no longer applies cleanly")
            print("Error running mach")
            sys.exit(1)


def run_post_patch_scripts(vendor_dir, manifest):
    env = dict(os.environ, GECKO_PATH=os.getcwd(), MACH_VENDOR="1")
    for script in manifest["post-patch"]:
        ret = subprocess.run([os.path.abspath(os.path.join(vendor_dir, script))], cwd=vendor_dir, env=env)
        if ret.returncode:
            print("Error running mach: %s exited with %d" % (script, ret.returncode))
            sys.exit(1)


def vendor(yaml_path, revision, patch_mode):
    vendor_dir = os.path.dirname(yaml_path)
    manifest = read_manifest(yaml_path)
    snapshot = os.path.join(os.environ["FAKE_UPSTREAM"], revision)

    for name in os.listdir(vendor_dir):
        if name not in KEPT_FILES and name not in manifest["keep"]:
            path = os.path.join(vendor_dir, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(snapshot):
        src = os.path.join(snapshot, name)
        dst = os.path.join(vendor_dir, name)
        shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
    subprocess.run(["hg", "addremove", "-q", vendor_dir], check=True)

    # mozbuild's spurious_check: staged changes, ignoring generated files
    status = subprocess.run(["hg", "status", "-n", vendor_dir], check=True, capture_output=True, text=True).stdout.split()
    generated = set(os.path.join(vendor_dir, g) for g in manifest["generated"])
    if not set(status) - generated:
        print("Upstream %s hasn't modified files locally." % revision)
        sys.exit(-2)  # exit status 254
    print("Version '%s' has changed %d files." % (revision, len(set(status) - generated)))

    with open(yaml_path) as f:
        lines = f.readlines()
    with open(yaml_path, "w") as f:
        f.writelines(("revision: %s\n" % revision) if line.startswith("revision:") else line for line in lines)

    if manifest["patches"]:
        print("Patches present in manifest!!! Please run './mach vendor --patch-mode only' after commiting changes.")


def check_modified_files():
    # Like mozbuild's check_modified_files: refuse to run while any tracked file in
    # the checkout is modified, unless --ignore-modified is passed.
    modified = subprocess.run(["hg", "status", "-m", "-n"], check=True, capture_output=True, text=True).stdout.split()
    if modified:
        print("You have uncommitted changes to the following files:\n\n%s\n\n"
              "Please commit or stash these changes before vendoring, or re-run with `--ignore-modified`." % "\n".join(sorted(modified)))
        sys.exit(1)


def main(args):
    assert args[0] == "vendor", args
    args = args[1:]
    ignore_modified = "--ignore-modified" in args
    args = [a for a in args if a != "--ignore-modified"]
    if args[0] != "--check-for-update" and not ignore_modified:
        check_modified_files()
    if args[0] == "--check-for-update":
        with open(os.path.join(os.environ["FAKE_UPSTREAM"], "latest")) as f:
            print(f.read().strip() + " 2026-11-03T12:00:00Z")
        return
    if args[:2] == ["--patch-mode", "only"]:
        yaml_path = args[2]
        manifest = read_manifest(yaml_path)
        apply_patches(os.path.dirname(yaml_path), manifest)
        run_post_patch_scripts(os.path.dirname(yaml_path), manifest)
        return
    yaml_path = args[0]
    revision = args[args.index("--revision") + 1]
    patch_mode = args[args.index("--patch-mode") + 1] if "--patch-mode" in args else "auto"
    vendor(yaml_path, revision, patch_mode)


if __name__ == "__main__":
    main(sys.argv[1:])
