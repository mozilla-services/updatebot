#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Local, live, END-TO-END test: the whole updatebot vendoring pipeline for a
contrived nestegg update, using real dev credentials.

This is NOT run by test.py / CI. It runs the real `Updatebot(...).run()` with a
`nestegg` library filter, which -- against the real dev backends -- will:
  * detect that nestegg is out of date and `./mach vendor` the new revision,
  * file a real bug on the dev Bugzilla,
  * hit a local-patch conflict and resolve it with the real `claude` CLI,
  * push a real Try run (`./mach try auto --push-to-vcs`),
  * submit real revision(s) to the dev Phabricator (`arc diff`),
  * and record job/try/phab rows in the dev database.

It costs money, pushes to Try, and creates real (dev) bugs/revisions, so it is
opt-in and SKIPS unless everything it needs is present.

How the scenario is contrived
-----------------------------
The trick is to make nestegg look out of date *and* guarantee the local patch
conflicts once it is upgraded:

  1. Downgrade nestegg to NESTEGG_OLD_REV (the parent of the upstream commit that
     refactored ne_read_uint) via `./mach vendor --revision ... --patch-mode
     none`. That rewrites moz.yaml's revision *and* the vendored source, so the
     later re-vendor is a real (non-spurious) change.
  2. Add the conflicting local patch. Its context is the pre-refactor guard
     `if (length == 0 || length > 8)`, which exists at NESTEGG_OLD_REV -- so it
     applies cleanly now, but will fail once updatebot upgrades to the refactored
     tip (`if (length > 8)`), triggering the AI conflict-resolution path.
  3. Commit it. updatebot's `check_for_update` then sees the tip as a new version
     and runs the full pipeline.

Requirements (SKIPS if any are missing):
  - localconfig.py with General.env == 'dev' and Database + Bugzilla blocks
  - an AI api key:  localconfig['AI']['apikey']  or  $ANTHROPIC_API_KEY
  - a gecko checkout: localconfig['General']['gecko-path'] or $LIVE_GECKO_PATH
  - the `claude` and `arc` CLIs on $PATH
  - (implicitly) Try push access for `./mach try --push-to-vcs`

Teardown restores the gecko checkout only; the filed bug, Phabricator revisions,
and dev DB rows are deliberately LEFT for inspection.
"""

import os
import sys
import copy
import shutil
import subprocess
import tempfile
import unittest

# Sibling helpers from the AI-only live test (this directory is on sys.path via
# test_local.py, or via the __main__ block below). We reuse the nestegg fixture,
# the moz.yaml patch-insertion, the hg helper, the working-parent lookup, and the
# checkout-restore logic rather than duplicating them.
from ai_conflict_resolution import (
    LIBRARY_DIR, MOZ_YAML, PATCH_REL, PATCH_FIXTURE,
    _add_patch_to_moz_yaml, hg, _working_parent_node, restore_checkout,
)

# The upstream nestegg revision to downgrade to: the parent of
# 1c9936b1... ("Handle zero-length uint... Bug 2045549"), which refactored the
# ne_read_uint length guard. At this revision the guard is still
# `if (length == 0 || length > 8)`, matching the conflicting patch's context.
NESTEGG_OLD_REV = "405fdae0802b9d6aa0c7937dbc660da197164980"

SCENARIO_COMMIT_MESSAGE = "TEST SCENARIO (do not land): downgrade nestegg + add conflicting local patch"

# A local Arcanist install that may not be on PATH. If present, we prepend it so
# both the `arc` requirement check and updatebot's real `arc` subprocesses find
# it (and pick up this specific build over any other).
ARC_BIN_DIR = "/home/tom/packages/arcanist/bin"


def _ensure_arc_on_path():
    if os.path.isdir(ARC_BIN_DIR) and ARC_BIN_DIR not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = ARC_BIN_DIR + os.pathsep + os.environ.get("PATH", "")


def _resolve_requirements():
    """Return (apikey, gecko_path, localconfig), or a string describing what's missing."""
    _ensure_arc_on_path()
    try:
        from localconfig import localconfig
    except ImportError:
        return ("No localconfig.py found. Copy localconfig.py.example to "
                "localconfig.py and fill in your dev credentials.")

    # Safety: this test files bugs and submits patches. Refuse to run it against
    # anything but an explicit dev environment.
    if localconfig.get("General", {}).get("env") != "dev":
        return "localconfig['General']['env'] must be 'dev' to run this test (refusing to touch prod)."

    apikey = os.environ.get("ANTHROPIC_API_KEY") or localconfig.get("AI", {}).get("apikey")
    gecko_path = os.environ.get("LIVE_GECKO_PATH") or localconfig.get("General", {}).get("gecko-path")

    missing = []
    if not apikey:
        missing.append("an AI api key (localconfig['AI']['apikey'] or $ANTHROPIC_API_KEY)")
    if not gecko_path:
        missing.append("a gecko checkout (localconfig['General']['gecko-path'] or $LIVE_GECKO_PATH)")
    if not localconfig.get("Database"):
        missing.append("a Database config block (dev DB) in localconfig")
    if not localconfig.get("Bugzilla", {}).get("apikey"):
        missing.append("a Bugzilla apikey in localconfig['Bugzilla']")
    if not shutil.which("claude"):
        missing.append("the 'claude' CLI on $PATH")
    if not shutil.which("arc"):
        missing.append("the 'arc' CLI on $PATH (for Phabricator submission)")
    if missing:
        return "Missing required configuration:\n  - " + "\n  - ".join(missing)

    gecko_path = os.path.abspath(gecko_path)
    if not os.path.isdir(os.path.join(gecko_path, ".hg")):
        return "%s is not a mercurial checkout." % gecko_path
    return apikey, gecko_path, localconfig


def _build_config(gecko_path, apikey, localconfig):
    config = copy.deepcopy(localconfig)
    config["General"]["env"] = "dev"
    config["General"]["gecko-path"] = gecko_path
    # Updatebot._validate requires an hg.mozilla.org repo; the dev localconfig may
    # point at a GitHub mirror. The value is only used for validation / a short
    # name -- env == 'dev' is what actually routes Bugzilla + Phabricator at their
    # dev instances -- so override it with the holly project repo.
    config["General"]["repo"] = "https://hg.mozilla.org/projects/holly"
    config.setdefault("AI", {})["apikey"] = apikey

    # Capture each claude invocation for debugging (honor $DEBUG_OUTPUT_DIR, else
    # a fresh /tmp dir we deliberately leave behind).
    debug_dir = os.environ.get("DEBUG_OUTPUT_DIR")
    debug_dir = os.path.abspath(debug_dir) if debug_dir else tempfile.mkdtemp(
        prefix="updatebot-ai-debug-", dir="/tmp")
    config["AI"]["debug-output-dir"] = debug_dir
    print("AI debug output will be written to %s" % debug_dir)
    return config


def _setup_downgraded_nestegg_scenario(gecko_path):
    # 1. Downgrade nestegg (moz.yaml revision + vendored source) to a pre-refactor
    #    revision, so check_for_update sees the tip as new and the re-vendor is a
    #    real change. --patch-mode none: there are no local patches yet.
    print("Downgrading nestegg to %s via `./mach vendor`..." % NESTEGG_OLD_REV[:12])
    vendor = subprocess.run(
        ["./mach", "vendor", MOZ_YAML, "--revision", NESTEGG_OLD_REV, "--patch-mode", "none"],
        cwd=gecko_path, capture_output=True, text=True)
    if vendor.returncode != 0:
        raise AssertionError("Downgrade vendor failed (rc=%d):\n%s\n%s" % (
            vendor.returncode, vendor.stdout, vendor.stderr))

    # 2. Add the conflicting local patch (applies cleanly at the old revision).
    lib = os.path.join(gecko_path, LIBRARY_DIR)
    os.makedirs(os.path.join(lib, "patches"), exist_ok=True)
    with open(PATCH_FIXTURE) as src:
        patch_text = src.read()
    with open(os.path.join(lib, PATCH_REL), "w") as dst:
        dst.write(patch_text)
    _add_patch_to_moz_yaml(os.path.join(gecko_path, MOZ_YAML))

    # 3. Commit everything (source downgrade + moz.yaml + the new patch file).
    #    --addremove so any files the downgrade added/removed are picked up.
    commit = hg(["commit", "--addremove", "-m", SCENARIO_COMMIT_MESSAGE], gecko_path)
    if commit.returncode != 0:
        raise AssertionError("Committing the scenario failed (rc=%d):\n%s\n%s" % (
            commit.returncode, commit.stdout, commit.stderr))


class TestFullVendorRunNesteggLive(unittest.TestCase):
    def setUp(self):
        requirements = _resolve_requirements()
        if isinstance(requirements, str):
            self.skipTest(requirements)
        self.apikey, self.gecko_path, self.localconfig = requirements

        # The checkout must be pristine so we don't clobber uncommitted work.
        status = hg(["status"], self.gecko_path)
        self.assertFalse(
            status.stdout.strip(),
            "The gecko checkout at %s is not clean:\n%s\nStart from a clean checkout." % (
                self.gecko_path, status.stdout))

        self.original_rev = _working_parent_node(self.gecko_path)
        print("Clean gecko checkout at %s (rev %s)." % (self.gecko_path, self.original_rev[:12]))

        # updatebot chdir's into the gecko path and doesn't chdir back; restore
        # both the checkout and our cwd. Registered BEFORE any mutation so they
        # run even if scenario setup raises partway through.
        self._original_cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._original_cwd))
        self.addCleanup(lambda: restore_checkout(self.gecko_path, self.original_rev))

        print("Setting up the downgraded-nestegg conflict scenario (and committing it)...")
        _setup_downgraded_nestegg_scenario(self.gecko_path)

    def _nestegg_library(self, updatebot):
        libraries = updatebot.libraryProvider.get_libraries(self.gecko_path)
        matches = [lib for lib in libraries if "nestegg" in lib.name]
        self.assertTrue(matches, "No nestegg library found in %s" % self.gecko_path)
        return matches[0]

    def test_full_vendor_run(self):
        from automation import Updatebot
        from components.dbmodels import JOBTYPE, JOBSTATUS, JOBOUTCOME

        config = _build_config(self.gecko_path, self.apikey, self.localconfig)

        print("Running the REAL updatebot for nestegg (files a dev bug, pushes Try, "
              "submits to dev Phabricator)...")
        updatebot = Updatebot(config)
        updatebot.run(library_filter="nestegg")

        # Read back what the run recorded. run() catches per-library exceptions
        # and logs them rather than raising, so we inspect the DB to judge it.
        library = self._nestegg_library(updatebot)
        jobs = updatebot.dbProvider.get_all_jobs_for_library(library, JOBTYPE.VENDORING)
        self.assertTrue(jobs, "updatebot recorded no vendoring job for nestegg -- did it "
                              "detect an update? (check_for_update / updatebot_is_enabled)")

        job = max(jobs, key=lambda j: j.id)
        bug_url = "https://bugzilla-dev.allizom.org/show_bug.cgi?id=%s" % job.bugzilla_id
        print("\n=== Most recent nestegg vendoring job ===")
        print("  job id:    %s" % job.id)
        print("  version:   %s" % job.version)
        print("  status:    %s" % JOBSTATUS(job.status).name)
        print("  outcome:   %s" % JOBOUTCOME(job.outcome).name)
        print("  bug:       %s" % (bug_url if job.bugzilla_id else "(none filed)"))
        for p in (job.phab_revisions or []):
            print("  phabricator: https://phabricator-dev.allizom.org/D%s" % p.revision)
        print("=========================================\n")

        self.assertIsNotNone(job.bugzilla_id, "no bug was filed for the nestegg job")
        # A fully successful pipeline ends waiting on Try results, with no failure
        # outcome recorded. Anything else (COULD_NOT_PATCH / _SUBMIT_TO_TRY /
        # _SUBMIT_TO_PHAB) means a stage failed -- the printout above says which.
        self.assertEqual(
            job.outcome, JOBOUTCOME.PENDING,
            "nestegg job finished with a failure outcome (%s); see the job details above." % job.outcome)
        self.assertIn(
            job.status,
            (JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS),
            "nestegg job did not reach the awaiting-try-results state; see the job details above.")

        print("PASS: updatebot filed a bug, resolved the patch conflict, pushed Try, and "
              "submitted to Phabricator for nestegg (job %s)." % job.id)


if __name__ == "__main__":
    # Allow running this file directly, like the other test modules. Put the repo
    # root AND this directory on sys.path so both `components.*`/`automation` and
    # the sibling `ai_conflict_resolution` import resolve regardless of cwd.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.abspath(os.path.join(here, "..", "..")))
    sys.path.insert(0, here)
    unittest.main(verbosity=2)
