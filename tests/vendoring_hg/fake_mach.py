#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
A stand-in for `./mach vendor`, copied into a test Mercurial repository as `mach`.

It implements the commands Updatebot runs, the way mozbuild's vendoring code
behaves, using real Mercurial operations. For a moz.yaml with vendoring stages:

  ./mach vendor <yaml> [--revision <rev>] [--stage <n>]
      Runs stage n (counting from 1; required if there are several). The 'fetch'
      stage replaces the vendored files (except 'keep' ones) with upstream snapshot
      <rev>, then applies its own patches, if any. Any other stage applies its
      patches, then runs its scripts. After every stage, added and removed files
      are registered, and the fetch stage then records <rev> in the moz.yaml.

And in the old format, without stages:

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
  stages: <name> [<name> ...]       (optional; the first must be 'fetch')
  <name>-patches: <file> [<file> ...]
                                    (optional; the patches a stage applies)
  <name>-scripts: <script> [<script> ...]
                                    (optional; run, with cwd '{yaml_dir}', after a
                                    later stage's patches)
  <name>-mozbuild-error: yes        (optional; the stage does its work, then exits
                                    255, as mach does when it can't edit a moz.build)
  patches: <file> [<file> ...]      (optional, old format, relative to the moz.yaml's directory)
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
            if key.strip() == "revision":
                manifest["revision"] = value.strip()
            elif key.strip():
                manifest[key.strip()] = value.split()
    return manifest


def apply_patches(vendor_dir, patches):
    # The same patch options as mozbuild's import_local_patches, including sending
    # rejects to a temporary file rather than leaving .rej files in the tree.
    for p in patches:
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


def run_post_patch_scripts(vendor_dir, scripts):
    env = dict(os.environ, GECKO_PATH=os.getcwd(), MACH_VENDOR="1")
    for script in scripts:
        ret = subprocess.run([os.path.abspath(os.path.join(vendor_dir, script))], cwd=vendor_dir, env=env)
        if ret.returncode:
            print("Error running mach: %s exited with %d" % (script, ret.returncode))
            sys.exit(1)


def fetch(yaml_path, revision):
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


def record_revision(yaml_path, revision):
    with open(yaml_path) as f:
        lines = f.readlines()
    with open(yaml_path, "w") as f:
        f.writelines(("revision: %s\n" % revision) if line.startswith("revision:") else line for line in lines)


def vendor_stage(yaml_path, revision, stage):
    vendor_dir = os.path.dirname(yaml_path)
    manifest = read_manifest(yaml_path)
    name = manifest["stages"][stage]
    print("Stage %d/%d: %s" % (stage + 1, len(manifest["stages"]), name))
    if name == "fetch":
        fetch(yaml_path, revision)
    apply_patches(vendor_dir, manifest.get(name + "-patches", []))
    if name != "fetch":
        run_post_patch_scripts(vendor_dir, manifest.get(name + "-scripts", []))
    subprocess.run(["hg", "addremove", "-q", vendor_dir], check=True)
    if stage == 0:
        record_revision(yaml_path, revision)
    if manifest.get(name + "-mozbuild-error"):
        print("Could not add new.c to the appropriate moz.build file")
        sys.exit(-1)  # exit status 255


def vendor(yaml_path, revision, patch_mode):
    vendor_dir = os.path.dirname(yaml_path)
    manifest = read_manifest(yaml_path)
    fetch(yaml_path, revision)
    subprocess.run(["hg", "addremove", "-q", vendor_dir], check=True)

    # mozbuild's spurious_check: staged changes, ignoring generated files
    status = subprocess.run(["hg", "status", "-n", vendor_dir], check=True, capture_output=True, text=True).stdout.split()
    generated = set(os.path.join(vendor_dir, g) for g in manifest["generated"])
    if not set(status) - generated:
        print("Upstream %s hasn't modified files locally." % revision)
        sys.exit(-2)  # exit status 254
    print("Version '%s' has changed %d files." % (revision, len(set(status) - generated)))

    record_revision(yaml_path, revision)

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
    stage = int(args[args.index("--stage") + 1]) - 1 if "--stage" in args else None
    if args[0] != "--check-for-update" and not ignore_modified and not stage:
        # Like mach, a later stage runs on top of the ones before it
        check_modified_files()
    if args[0] == "--check-for-update":
        with open(os.path.join(os.environ["FAKE_UPSTREAM"], "latest")) as f:
            print(f.read().strip() + " 2026-11-03T12:00:00Z")
        return
    if args[:2] == ["--patch-mode", "only"]:
        yaml_path = args[2]
        manifest = read_manifest(yaml_path)
        apply_patches(os.path.dirname(yaml_path), manifest["patches"])
        run_post_patch_scripts(os.path.dirname(yaml_path), manifest["post-patch"])
        return
    yaml_path = args[0]
    if "stages" in read_manifest(yaml_path):
        stages = read_manifest(yaml_path)["stages"]
        if stage is None and len(stages) > 1:
            print("%s has %d vendoring stages; choose one with --stage" % (yaml_path, len(stages)))
            sys.exit(1)
        revision = args[args.index("--revision") + 1] if "--revision" in args else read_manifest(yaml_path)["revision"]
        vendor_stage(yaml_path, revision, stage or 0)
        return
    revision = args[args.index("--revision") + 1]
    patch_mode = args[args.index("--patch-mode") + 1] if "--patch-mode" in args else "auto"
    vendor(yaml_path, revision, patch_mode)


if __name__ == "__main__":
    main(sys.argv[1:])
