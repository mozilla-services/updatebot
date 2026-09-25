#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Local, live test: AIProvider.resolve_patch_conflicts against a *real* AI backend.

This is NOT run by test.py / CI. It drives the real `claude` CLI on a real gecko
checkout, using the committed nestegg conflict scenario. It costs money and is
non-deterministic, so it is opt-in and lives in the local-tests tier (run it with
`poetry run ./test_local.py`).

Requirements (from localconfig.py or the environment); the test SKIPS if any are
missing:
  - an AI api key:    localconfig['AI']['apikey']            or  $ANTHROPIC_API_KEY
  - a gecko checkout: localconfig['General']['gecko-path']   or  $LIVE_GECKO_PATH
  - the `claude` CLI on $PATH

The gecko checkout MUST be clean (no modifications, no untracked files) before
starting -- we assert this so we never clobber your work. We set up the scenario
as a commit, run the live resolution, assert on the result, and strip everything
back to the original revision (registered as a cleanup up front, so it runs even
if setup fails partway) so the test is re-runnable.
"""

import os
import re
import sys
import shutil
import subprocess
import tempfile
import unittest


def hg(args, cwd):
    return subprocess.run(["hg"] + args, cwd=cwd, capture_output=True, text=True)


# --- The nestegg conflict scenario -------------------------------------------
#
# We add a local Mozilla patch to media/libnestegg that was written against an
# older revision of ne_read_uint, so it no longer applies to the current
# (vendored) nestegg.c. Running `./mach vendor --patch-mode only` on it then
# fails with a conflict -- exactly the situation resolve_patch_conflicts is
# meant to resolve. The patch fixture (nestegg_conflict.patch) lives next to
# this file.

LIBRARY_DIR = "media/libnestegg"
MOZ_YAML = os.path.join(LIBRARY_DIR, "moz.yaml")
PATCH_REL = "patches/0001-clamp-nestegg-uint-reads.patch"
PATCH_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nestegg_conflict.patch")
SCENARIO_COMMIT_MESSAGE = "TEST SCENARIO (do not land): nestegg local patch that conflicts with upstream"


def _add_patch_to_moz_yaml(moz_yaml_path):
    with open(moz_yaml_path) as f:
        lines = f.readlines()

    if any(PATCH_REL in line for line in lines):
        return  # already set up

    out = []
    inserted = False
    for line in lines:
        out.append(line)
        # Insert a patches list immediately after the vendor-directory line,
        # which sits inside the `vendoring:` block.
        if not inserted and line.strip().startswith("vendor-directory:"):
            out.append("  patches:\n")
            out.append("    - %s\n" % PATCH_REL)
            inserted = True

    if not inserted:
        raise Exception("Could not find a vendor-directory line to anchor the patches list in %s" % moz_yaml_path)

    with open(moz_yaml_path, "w") as f:
        f.writelines(out)


def _setup_nestegg_scenario(gecko_path):
    """Add the conflicting local patch, list it in moz.yaml, and commit it."""
    lib = os.path.join(gecko_path, LIBRARY_DIR)
    os.makedirs(os.path.join(lib, "patches"), exist_ok=True)

    with open(PATCH_FIXTURE) as src:
        patch_text = src.read()
    with open(os.path.join(lib, PATCH_REL), "w") as dst:
        dst.write(patch_text)

    _add_patch_to_moz_yaml(os.path.join(gecko_path, MOZ_YAML))

    hg(["add", os.path.join(LIBRARY_DIR, PATCH_REL)], gecko_path)
    hg(["commit", "-m", SCENARIO_COMMIT_MESSAGE], gecko_path)


def restore_checkout(gecko_path, original_rev):
    # Restore the checkout: discard working changes, strip everything committed on
    # top of original_rev (the scenario setup + anything updatebot/the AI added),
    # and purge leftover untracked files, so re-runs start clean. Run every step
    # even if an earlier one fails, so a single error doesn't leave a commit
    # checked out / the tree dirty.
    print("Restoring the checkout to %s ..." % original_rev[:12])
    for step in (["update", "-C", original_rev],
                 ["debugstrip", "-r", "children(%s)" % original_rev, "--no-backup"],
                 ["--config", "extensions.purge=", "purge", "--all"]):
        try:
            r = hg(step, gecko_path)
            if r.returncode != 0:
                print("WARNING: `hg %s` exited %d:\n%s" % (" ".join(step), r.returncode, r.stderr.strip()))
        except OSError as e:
            print("WARNING: could not run `hg %s`: %s" % (" ".join(step), e))


def _working_parent_node(gecko_path):
    # Return the single 40-char node of the working-directory parent.
    #
    # We deliberately do NOT trust `hg log -r . -T {node}` blindly: a user's hg
    # config (a `log` alias, `[defaults]`, or firefoxtree/version-control-tools
    # setup) can turn that into a follow/all-revisions log, so it emits many
    # concatenated node hashes -- a multi-megabyte string. Interpolated into the
    # teardown revset, that argv exceeds the kernel's ARG_MAX and the shell-out
    # dies with `OSError: [Errno 7] Argument list too long`. `-l 1` caps the
    # output to one changeset, and we validate the shape before using it.
    out = hg(["log", "-r", ".", "-l", "1", "-T", "{node}\n"], gecko_path).stdout
    lines = out.splitlines()
    node = lines[0].strip() if lines else ""
    if not re.fullmatch(r"[0-9a-f]{40}", node):
        raise AssertionError(
            "Could not determine a single working-parent revision: `hg log -r .` "
            "returned %d line(s) / %d chars (first 60: %r). Check whether your hg "
            "configuration redefines `log`." % (len(lines), len(out), node[:60]))
    return node


def _resolve_requirements():
    """Return (apikey, gecko_path), or a string describing what's missing."""
    apikey = os.environ.get("ANTHROPIC_API_KEY")
    gecko_path = os.environ.get("LIVE_GECKO_PATH")
    try:
        from localconfig import localconfig
        apikey = apikey or localconfig.get("AI", {}).get("apikey")
        gecko_path = gecko_path or localconfig.get("General", {}).get("gecko-path")
    except ImportError:
        pass

    missing = []
    if not apikey:
        missing.append("an AI api key (localconfig['AI']['apikey'] or $ANTHROPIC_API_KEY)")
    if not gecko_path:
        missing.append("a gecko checkout (localconfig['General']['gecko-path'] or $LIVE_GECKO_PATH)")
    if not shutil.which("claude"):
        missing.append("the 'claude' CLI on $PATH")
    if missing:
        return "Missing required configuration:\n  - " + "\n  - ".join(missing)

    gecko_path = os.path.abspath(gecko_path)
    if not os.path.isdir(os.path.join(gecko_path, ".hg")):
        return "%s is not a mercurial checkout." % gecko_path
    return apikey, gecko_path


class TestAIConflictResolutionLive(unittest.TestCase):
    def setUp(self):
        requirements = _resolve_requirements()
        if isinstance(requirements, str):
            self.skipTest(requirements)
        self.apikey, self.gecko_path = requirements

        # The checkout must be pristine so we don't clobber uncommitted work.
        status = hg(["status"], self.gecko_path)
        self.assertFalse(
            status.stdout.strip(),
            "The gecko checkout at %s is not clean:\n%s\nStart from a clean checkout." % (
                self.gecko_path, status.stdout))

        self.original_rev = _working_parent_node(self.gecko_path)
        print("Clean gecko checkout at %s (rev %s)." % (self.gecko_path, self.original_rev[:12]))

        # Register the restore BEFORE we mutate anything, so it runs even if the
        # scenario setup below (or the test) raises partway through.
        self.addCleanup(self._restore)

        print("Setting up the nestegg conflict scenario (and committing it)...")
        _setup_nestegg_scenario(self.gecko_path)

    def _restore(self):
        restore_checkout(self.gecko_path, self.original_rev)

    def _resolve_with_real_ai(self):
        from components.commandprovider import CommandProvider
        from components.logging import SimpleLogger
        from components.aiprovider import AIProvider

        logger = SimpleLogger({"local": True, "level": 5})
        command_provider = CommandProvider({})
        command_provider.update_config({"LoggingProvider": logger})
        ai_config = {"apikey": self.apikey}
        # Capture the prompt/system prompt/stdout/stderr of each claude invocation
        # for debugging (the CLI buffers its JSON until it finishes, so there is
        # nothing to watch mid-run -- inspect this afterwards). Honor
        # $DEBUG_OUTPUT_DIR if set; otherwise make a fresh /tmp dir that we
        # deliberately leave behind so the output survives the run.
        debug_dir = os.environ.get("DEBUG_OUTPUT_DIR")
        if debug_dir:
            debug_dir = os.path.abspath(debug_dir)
        else:
            debug_dir = tempfile.mkdtemp(prefix="updatebot-ai-debug-", dir="/tmp")
        ai_config["debug-output-dir"] = debug_dir
        print("AI debug output will be written to %s" % debug_dir)
        ai = AIProvider(ai_config)
        ai.update_config({"CommandProvider": command_provider, "LoggingProvider": logger})

        return ai.resolve_patch_conflicts(
            MOZ_YAML,
            "Bug 0 - update nestegg local patches to apply cleanly (test)",
            cwd=self.gecko_path)

    def test_resolve_nestegg_patch_conflict(self):
        print("Running the live AI conflict resolution (this calls the real claude CLI)...")
        result = self._resolve_with_real_ai()

        self.assertIsNotNone(result, "resolve_patch_conflicts produced no result file.")
        outcome = result.get("outcome")
        print("AI outcome: %s" % outcome)
        print("AI details:\n  - " + "\n  - ".join(result.get("details", [])))
        self.assertIn(outcome, ("trivial success", "uncertain success"),
                      "AI reported outcome %r; expected a success." % outcome)

        # The patch should now apply cleanly (or have been removed as upstreamed).
        reapply = subprocess.run(
            ["./mach", "vendor", "--patch-mode", "only", MOZ_YAML],
            cwd=self.gecko_path, capture_output=True, text=True)
        self.assertEqual(
            reapply.returncode, 0,
            "After AI resolution, `./mach vendor --patch-mode only` still failed:\n%s" % reapply.stderr)

        print("PASS: the AI resolved the nestegg patch conflict (%s)." % outcome)


if __name__ == "__main__":
    # Allow running this file directly, like the other test modules
    # (e.g. `python tests/local-tests/ai_conflict_resolution.py`). Put the repo
    # root on sys.path so the lazy `components.*` / `localconfig` imports resolve
    # regardless of the current working directory.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    unittest.main(verbosity=2)
