#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Runs the vendoring flow against a real Mercurial repository.

Unlike the other functionality tests, every hg command really runs, in a
throwaway repository with a fake library in it. `./mach vendor` is
tests/vendoring_hg/fake_mach.py, which behaves like mozbuild's vendoring code
(including its spurious-update check). Try, Phabricator, Bugzilla, the upstream
git repository and the AI are still mocked.
"""

import os
import sys
import shutil
import difflib
import tempfile
import unittest
import subprocess
from collections import OrderedDict

sys.path.append(".")
sys.path.append("..")
import components.utilities
components.utilities.RETRY_TIMES_OVERRIDE = 3

from automation import Updatebot

from components.utilities import Struct
from components.logging import SimpleLoggingTest, LoggingProvider, log, logEntryExitHeaderLine
from components.commandprovider import CommandProvider
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.mach_vendor import VendorProvider
from components.hg import MercurialProvider
from components.scmprovider import SCMProvider
from components.libraryprovider import LibraryProvider, Library
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.functionality_utilities import SHARED_COMMAND_MAPPINGS, TRY_OUTPUT, MockedBugzillaProvider
from tests.mock_commandprovider import TestCommandProvider, DO_EXECUTE
from tests.mock_aiprovider import MockAIProvider
from tests.mock_libraryprovider import MockLibraryProvider
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

NEW_VERSION = "v2"
VENDOR_DIR = "media/fakelib"
YAML_PATH = VENDOR_DIR + "/moz.yaml"
BUG_ID = 50

LIB_C = ["line %d\n" % i for i in range(1, 11)]
PATCHED_LIB_C = LIB_C[:4] + ["line 5 (with a mozilla fix)\n"] + LIB_C[5:]
FIX_PATCH = "".join(difflib.unified_diff(LIB_C, PATCHED_LIB_C, "a/lib.c", "b/lib.c"))
# Patches that add and delete whole files (GNU patch creates and removes files for /dev/null diffs)
ADD_FILE_PATCH = "--- /dev/null\n+++ b/extra.c\n@@ -0,0 +1 @@\n+int mozilla_extra;\n"
DELETE_FILE_PATCH = "--- a/unwanted.c\n+++ /dev/null\n@@ -1 +0,0 @@\n-int unwanted;\n"
MODIFY_EXTRA_PATCH = "--- a/extra.c\n+++ b/extra.c\n@@ -1 +1 @@\n-int mozilla_extra;\n+int mozilla_extra = 1;\n"
ADD_FILE_IN_NEW_DIR_PATCH = "--- /dev/null\n+++ b/newdir/extra.c\n@@ -0,0 +1 @@\n+int mozilla_extra;\n"
# Post-patch scripts, modelled on the real ones: libogg/libjpeg keep a source list
# in step with the vendored files (and libjpeg's update.py fails when it finds files
# it doesn't know about), and opentelemetry-proto generates code from .proto files.
LIST_SOURCES_SCRIPT = """#!/usr/bin/env python3
import glob
with open("sources.mozbuild", "w") as f:
    f.write("SOURCES += [\\n" + "".join("    '%s',\\n" % s for s in sorted(glob.glob("*.c"))) + "]\\n")
"""
GENERATE_FROM_PROTO_SCRIPT = """#!/usr/bin/env python3
import glob
for proto in sorted(glob.glob("*.proto")):
    with open(proto) as src, open(proto[:-len(".proto")] + ".pb.h", "w") as out:
        out.write("// Generated from %s\\n" % proto + src.read())
"""
CHECK_SOURCES_SCRIPT = """#!/usr/bin/env python3
import glob, sys
sources = sorted(glob.glob("*.c"))
with open("sources.mozbuild", "w") as f:  # updated before checking, so a failure leaves it half-done
    f.write("SOURCES += %r\\n" % sources)
unknown = sorted(set(sources) - set(open("known_sources.txt").read().split()))
if unknown:
    print("Unhandled new files:", unknown)
    sys.exit(1)
"""
# Files the scripts write, which are in-tree files rather than upstream ones
POST_PATCH_OUTPUTS = ["sources.mozbuild"]

# One patch file touching two files, so it can half-apply
TWO_FILE_PATCH = FIX_PATCH + "--- a/util.c\n+++ b/util.c\n@@ -1 +1 @@\n-int util;\n+int util = 42;\n"


class HgLibraryProvider(MockLibraryProvider):
    def get_libraries(self, gecko_path):
        return [Library({
            "name": "fakelib",
            "bugzilla_product": "Core",
            "bugzilla_component": "General",
            "maintainer_phab": "fakelib",
            "maintainer_bz": "fakelib@mozilla.com",
            # The commit-listing git commands are mocked, and they call the in-tree revision this.
            "revision": "_current",
            "repo_url": "https://example.invalid",
            "has_patches": self.config['has_patches'],
            "flavor": "regular",
            "tasks": [LibraryProvider.validate_task({"type": "vendoring", "enabled": True}, "fakelib")],
            "yaml_path": YAML_PATH,
            "generated": self.config.get('generated', []),
        })]

    def library_has_patches(self, gecko_path, library):
        return library.has_patches


PROVIDERS = {
    'Logging': LoggingProvider,
    'Command': TestCommandProvider,
    'Database': DatabaseProvider,
    'Vendor': VendorProvider,
    'Library': HgLibraryProvider,
    'Bugzilla': MockedBugzillaProvider,
    'Mercurial': MercurialProvider,
    'Taskcluster': TaskclusterProvider,
    'Phabricator': PhabricatorProvider,
    'SCM': SCMProvider,
    'AI': MockAIProvider,
}


def write(path, contents):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(contents)


class TestVendoringWithMercurial(SimpleLoggingTest):
    @classmethod
    def setUpClass(cls):
        # Fail rather than skip: these tests are the only ones that exercise the real hg operations.
        for tool in ("hg", "patch"):
            if not shutil.which(tool):
                raise Exception("These tests need %s installed and on the PATH" % tool)

    def setUp(self):
        self.original_cwd = os.getcwd()
        self.original_env = {k: os.environ.get(k) for k in ("HGRCPATH", "GECKO_HEAD_REV", "FAKE_UPSTREAM")}
        self.tmp = tempfile.mkdtemp(prefix="updatebot-vendoring-hg-")
        self.repo = os.path.join(self.tmp, "gecko")
        self.upstream = os.path.join(self.tmp, "upstream")
        os.makedirs(self.repo)
        os.makedirs(self.upstream)

        # Only our config: no user hgrc, and the extensions the Updatebot image enables.
        hgrc = os.path.join(self.tmp, "hgrc")
        write(hgrc, "[ui]\nusername = Updatebot Test <updatebot@example.com>\n[extensions]\nstrip =\npurge =\n")
        os.environ["HGRCPATH"] = hgrc
        os.environ["FAKE_UPSTREAM"] = self.upstream

    def tearDown(self):
        os.chdir(self.original_cwd)
        for k, v in self.original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ----------------------------------------------------------------
    def _hg(self, *args):
        return subprocess.run(["hg"] + list(args), cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def _make_repo(self, has_patches, generated=None, patch=FIX_PATCH, extra_upstream_files=None, post_patch_scripts=None, kept_files=None):
        """The in-tree library at upstream v1 (plus extra_upstream_files), with our patch
        (or list of patches, applied in order) applied if has_patches.

        post_patch_scripts ({name: source}) run after the patches, as a post-patch
        action would; kept_files ({name: contents}) are in-tree files that aren't from
        upstream. Both, and any files the scripts write, are kept when vendoring."""
        patches = patch if isinstance(patch, list) else [patch]
        post_patch_scripts = post_patch_scripts or {}
        kept_files = kept_files or {}
        manifest = "revision: v1\n"
        if has_patches:
            manifest += "patches: %s\n" % " ".join("patches/%d.patch" % i for i in range(len(patches)))
            for i, p in enumerate(patches):
                write(os.path.join(self.repo, VENDOR_DIR, "patches/%d.patch" % i), p)
        if generated:
            manifest += "generated: %s\n" % " ".join(generated)
        if post_patch_scripts:
            manifest += "post-patch: %s\n" % " ".join(post_patch_scripts)
        keep = list(post_patch_scripts) + list(kept_files) + list(POST_PATCH_OUTPUTS)
        if keep:
            manifest += "keep: %s\n" % " ".join(keep)
        write(os.path.join(self.repo, YAML_PATH), manifest)
        for name, source in post_patch_scripts.items():
            write(os.path.join(self.repo, VENDOR_DIR, name), source)
            os.chmod(os.path.join(self.repo, VENDOR_DIR, name), 0o755)
        for name, contents in kept_files.items():
            write(os.path.join(self.repo, VENDOR_DIR, name), contents)

        self.v1 = {"lib.c": "".join(LIB_C), "util.c": "int util;\n", "old.c": "int old;\n"}
        self.v1.update(extra_upstream_files or {})
        for g in generated or []:
            self.v1[g] = "#define GENERATED 1\n"
        self._add_upstream("v1", self.v1)
        for name, contents in self.v1.items():
            write(os.path.join(self.repo, VENDOR_DIR, name), contents)
        if has_patches:
            for p in patches:
                subprocess.run(["patch", "-p1", "--batch", "--quiet", "-d", os.path.join(self.repo, VENDOR_DIR)], input=p, text=True, check=True)
            for name in post_patch_scripts:
                subprocess.run([os.path.join(self.repo, VENDOR_DIR, name)], cwd=os.path.join(self.repo, VENDOR_DIR), check=True)

        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendoring_hg", "fake_mach.py"), os.path.join(self.repo, "mach"))
        os.chmod(os.path.join(self.repo, "mach"), 0o755)

        self._hg("init")
        self._hg("commit", "-A", "-q", "-m", "base")
        self.base = self._hg("log", "-r", ".", "-T", "{node}").strip()
        # Like Taskcluster: reset_repository goes back to the revision we started from.
        os.environ["GECKO_HEAD_REV"] = self.base
        self.has_patches = has_patches
        self.generated = generated or []

    def _add_upstream(self, revision, files):
        for name, contents in files.items():
            write(os.path.join(self.upstream, revision, name), contents)
        write(os.path.join(self.upstream, "latest"), revision)

    def _run(self):
        version_line = NEW_VERSION + "|2026-11-03 12:00:00 +0000|2026-11-03 12:00:00 +0000"
        expected_values = Struct(**{
            'git_pretty_output_func': lambda since_last_job: [version_line],
            'library_new_version_id': lambda: NEW_VERSION,
            'try_revision_id': lambda: "try_rev",
            'get_filed_bug_id_func': lambda: BUG_ID,
            'phab_revision_func': lambda: 83000 + BUG_ID,
            'two_phab_revisions': self.has_patches,
        })

        mappings = OrderedDict([
            ("./mach try", lambda: TRY_OUTPUT("try_rev")),
            ("./mach vendor", DO_EXECUTE),
            # Submitting the patch stack to (mocked) Phabricator walks it with evolve; not under test here.
            ("hg checkout tip~", lambda: ""),
            ("hg next", lambda: ""),
            ("hg ", DO_EXECUTE),
        ])
        for prefix, response in SHARED_COMMAND_MAPPINGS(expected_values, {}).items():
            if not prefix.startswith("./mach vendor") and not prefix.startswith("hg "):
                mappings[prefix] = response

        real_runner = CommandProvider({})
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': self.repo,
                'ff-version': 87,
                'repo': 'https://hg.mozilla.org/mozilla-central'
            },
            'Command': {'test_mappings': mappings, 'real_runner': real_runner},
            'Logging': localconfig['Logging'],
            'Database': db_config,
            'Vendor': {},
            'Bugzilla': {
                'get_filed_bug_id_func': lambda: BUG_ID,
                'filed_bug_ids_func': lambda only_open: {},
                'assert_affected_func': None,
                'assert_assignee_func': None,
                'assert_prior_bug_reference': False,
            },
            'Mercurial': {},
            'Taskcluster': {'url_treeherder': 'http://localhost:27491/', 'url_taskcluster': 'http://localhost:27491/'},
            'Phabricator': {},
            'AI': {},
            'Library': {'has_patches': self.has_patches, 'generated': self.generated},
        }

        u = Updatebot(configs, PROVIDERS)
        real_runner.update_config({'LoggingProvider': u.logger})

        filed_bugs = []
        original_file_bug = u.bugzillaProvider.file_bug
        u.bugzillaProvider.file_bug = lambda *args, **kwargs: (filed_bugs.append(args[1]), original_file_bug(*args, **kwargs))[1]

        try:
            u.run(library_filter="fakelib")
        finally:
            os.chdir(self.original_cwd)

        lib = u.libraryProvider.get_libraries(self.repo)[0]
        job = u.dbProvider.get_job(lib, NEW_VERSION)
        if job:
            u.dbProvider.delete_job(library=lib, version=NEW_VERSION)
        return Struct(**{'job': job, 'filed_bugs': filed_bugs, 'ai_calls': u.aiProvider.resolve_call_count})

    def _new_commits(self):
        """(description, {path: status}) for each commit Updatebot made, oldest first."""
        commits = []
        for rev in self._hg("log", "-r", "descendants(%s) - %s" % (self.base, self.base), "-T", "{node}\n").split():
            desc = self._hg("log", "-r", rev, "-T", "{desc}")
            changes = {}
            for line in self._hg("status", "--change", rev).splitlines():
                status, path = line.split(" ", 1)
                changes[path] = status
            commits.append((desc, changes))
        return commits

    def _new_commit_nodes(self):
        return self._hg("log", "-r", "descendants(%s) - %s" % (self.base, self.base), "-T", "{node}\n").split()

    def _files_at(self, rev):
        return sorted(f[len(VENDOR_DIR) + 1:] for f in self._hg("files", "-r", rev, VENDOR_DIR).split() if "/patches/" not in f and not f.endswith("moz.yaml"))

    def _assert_job_and_commits(self, result, vendoring_changes, patch_changes):
        self.assertIsNotNone(result.job, "Didn't create a job for a real update")
        self.assertEqual(result.job.status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS)
        self.assertEqual(result.job.outcome, JOBOUTCOME.PENDING)
        self.assertEqual(len(result.filed_bugs), 1)
        commits = self._new_commits()
        self.assertEqual([c[0] for c in commits], [
            "Bug %d - Update fakelib to %s" % (BUG_ID, NEW_VERSION),
            "Bug %d - Apply mozilla patches for fakelib" % BUG_ID])

        def prefixed(changes):
            return {VENDOR_DIR + "/" + f: s for f, s in changes.items()}
        self.assertEqual(commits[0][1], prefixed(vendoring_changes), "Wrong changes in the vendoring commit")
        self.assertEqual(commits[1][1], prefixed(patch_changes), "Wrong changes in the patch commit")
        self._assert_tree_is_clean()

    def _assert_patch_failed_cleanly(self, result, vendoring_changes, conflict=True):
        """Got past the spurious-update check (a job, and a correct vendoring commit),
        then the patches (or, if not conflict, a post-patch action) failed, leaving a
        clean tree. Only a patch conflict is handed to the (mocked, failing) AI."""
        self.assertIsNotNone(result.job, "Didn't create a job")
        self.assertEqual(result.ai_calls, 1 if conflict else 0, "Wrong number of AI conflict resolutions")
        self.assertEqual(result.job.status, JOBSTATUS.DONE)
        self.assertEqual(result.job.outcome, JOBOUTCOME.COULD_NOT_PATCH)
        self.assertEqual(len(result.filed_bugs), 1)
        commits = self._new_commits()
        self.assertEqual([c[0] for c in commits], ["Bug %d - Update fakelib to %s" % (BUG_ID, NEW_VERSION)])
        self.assertEqual(commits[0][1], {VENDOR_DIR + "/" + f: st for f, st in vendoring_changes.items()}, "Wrong changes in the vendoring commit")
        self._assert_tree_is_clean()

    def _vendored(self, rev, name):
        return self._hg("cat", "-r", rev, os.path.join(VENDOR_DIR, name))

    def _assert_nothing_happened(self, result):
        self.assertIsNone(result.job, "Created a job for an update with no net change")
        self.assertEqual(result.filed_bugs, [], "Filed a bug for an update with no net change")
        self.assertEqual(self._new_commits(), [], "Made commits for an update with no net change")
        self._assert_tree_is_clean()

    def _assert_tree_is_clean(self):
        self.assertEqual(self._hg("status"), "", "Left changes (or untracked files, like .rej files) in the working directory")
        tracked_dirs = set(os.path.dirname(f) for f in self._hg("files").split())
        for root, dirs, files in os.walk(self.repo):
            dirs[:] = [d for d in dirs if d != ".hg"]
            rel = os.path.relpath(root, self.repo)
            if rel != "." and not any(t == rel or t.startswith(rel + "/") for t in tracked_dirs):
                self.fail("Left an untracked directory behind: " + rel)
        self.assertEqual(self._hg("log", "-r", ".", "-T", "{node}").strip(), self.base, "Didn't return to the starting revision")
        self.assertNotIn("updatebot-spurious-check", self._hg("--config", "extensions.shelve=", "shelve", "--list"), "Left its shelved change behind")

    # ----------------------------------------------------------------
    # Positive: a real update to a library with patches goes through the whole flow,
    # with the vendoring commit (including added and removed files) and the patch
    # commit exactly as before.
    @logEntryExitHeaderLine
    def testRealChangeWithPatches(self):
        self._make_repo(has_patches=True)
        v2_lib_c = LIB_C[:8] + ["line 9, changed upstream\n"] + LIB_C[9:]
        self._add_upstream(NEW_VERSION, {"lib.c": "".join(v2_lib_c), "util.c": "int util = 2;\n", "new.c": "int added;\n"})

        result = self._run()

        self.assertIsNotNone(result.job, "Didn't create a job for a real update")
        self.assertEqual(result.job.status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS)
        self.assertEqual(result.job.outcome, JOBOUTCOME.PENDING)
        self.assertEqual(len(result.filed_bugs), 1)

        commits = self._new_commits()
        self.assertEqual([c[0] for c in commits], [
            "Bug %d - Update fakelib to %s" % (BUG_ID, NEW_VERSION),
            "Bug %d - Apply mozilla patches for fakelib" % BUG_ID])
        self.assertEqual(commits[0][1], {
            VENDOR_DIR + "/moz.yaml": "M",
            VENDOR_DIR + "/lib.c": "M",
            VENDOR_DIR + "/util.c": "M",
            VENDOR_DIR + "/new.c": "A",
            VENDOR_DIR + "/old.c": "R"})
        self.assertEqual(commits[1][1], {VENDOR_DIR + "/lib.c": "M"})

        vendoring_commit, patch_commit = self._hg("log", "-r", "descendants(%s) - %s" % (self.base, self.base), "-T", "{node}\n").split()
        self.assertEqual(self._vendored(vendoring_commit, "lib.c"), "".join(v2_lib_c), "The vendoring commit should be pristine upstream")
        self.assertEqual(self._vendored(patch_commit, "lib.c"),
                         "".join(v2_lib_c[:4] + ["line 5 (with a mozilla fix)\n"] + v2_lib_c[5:]), "The patch commit should reapply our patch")
        self._assert_tree_is_clean()

    # Positive: when our patch no longer applies, the existing patch-failure handling
    # runs, exactly as before.
    @logEntryExitHeaderLine
    def testPatchConflict(self):
        self._make_repo(has_patches=True)
        v2_lib_c = LIB_C[:4] + ["line 5, changed upstream\n"] + LIB_C[5:]
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"lib.c": "".join(v2_lib_c)}))

        result = self._run()

        self.assertIsNotNone(result.job)
        self.assertEqual(result.job.status, JOBSTATUS.DONE)
        self.assertEqual(result.job.outcome, JOBOUTCOME.COULD_NOT_PATCH)
        self.assertEqual(len(result.filed_bugs), 1)
        self.assertEqual(result.ai_calls, 1, "A patch conflict should go to the AI")
        self.assertEqual([c[0] for c in self._new_commits()], ["Bug %d - Update fakelib to %s" % (BUG_ID, NEW_VERSION)])
        self._assert_tree_is_clean()

    # Positive: without patches, mach itself spots the spurious update.
    @logEntryExitHeaderLine
    def testSpuriousWithoutPatches(self):
        self._make_repo(has_patches=False)
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Negative today: upstream changed nothing we vendor, but because we vendor
    # with --patch-mode none, removing our patch looks like a change (#425).
    @logEntryExitHeaderLine
    def testPatchesCancelOut(self):
        self._make_repo(has_patches=True)
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Upstream adds a file (and our patch to lib.c still applies).
    @logEntryExitHeaderLine
    def testFileAddedUpstream(self):
        self._make_repo(has_patches=True)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"new.c": "int added_upstream;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "new.c": "A"}, {"lib.c": "M"})
        self.assertEqual(self._files_at(self._new_commit_nodes()[1]), ["lib.c", "new.c", "old.c", "util.c"])

    # Upstream deletes a file.
    @logEntryExitHeaderLine
    def testFileDeletedUpstream(self):
        self._make_repo(has_patches=True)
        v2 = dict(self.v1)
        del v2["old.c"]
        self._add_upstream(NEW_VERSION, v2)

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "old.c": "R"}, {"lib.c": "M"})
        self.assertEqual(self._files_at(self._new_commit_nodes()[1]), ["lib.c", "util.c"])

    # Our patch adds a file, and upstream changed nothing: vendoring removes the
    # file and the patch puts it back, so there's no net change.
    @logEntryExitHeaderLine
    def testFileAddedByPatchNoUpstreamChange(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_PATCH)
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Our patch adds a file, and upstream changed another one: the vendoring commit
    # removes our file and the patch commit adds it back.
    @logEntryExitHeaderLine
    def testFileAddedByPatchWithUpstreamChange(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"util.c": "int util = 2;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "util.c": "M", "extra.c": "R"}, {"extra.c": "A"})
        self.assertEqual(self._files_at(self._new_commit_nodes()[1]), ["extra.c", "lib.c", "old.c", "util.c"])

    # Our patch deletes an upstream file, and upstream changed nothing: vendoring
    # brings the file back and the patch deletes it again, so there's no net change.
    @logEntryExitHeaderLine
    def testFileDeletedByPatchNoUpstreamChange(self):
        self._make_repo(has_patches=True, patch=DELETE_FILE_PATCH, extra_upstream_files={"unwanted.c": "int unwanted;\n"})
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Our patch deletes an upstream file, and upstream changed another one: the
    # vendoring commit adds the file back and the patch commit deletes it.
    @logEntryExitHeaderLine
    def testFileDeletedByPatchWithUpstreamChange(self):
        self._make_repo(has_patches=True, patch=DELETE_FILE_PATCH, extra_upstream_files={"unwanted.c": "int unwanted;\n"})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"util.c": "int util = 2;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "util.c": "M", "unwanted.c": "A"}, {"unwanted.c": "R"})
        self.assertEqual(self._files_at(self._new_commit_nodes()[1]), ["lib.c", "old.c", "util.c"])

    # ---- Patches that no longer apply. Each should get past the spurious-update
    # ---- check with the vendoring commit intact, then fail cleanly.

    # Upstream added a file our patch adds, with different contents.
    @logEntryExitHeaderLine
    def testUpstreamAddsFileOurPatchAddsDifferently(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"extra.c": "int upstream_extra;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "extra.c": "M"})

    # Upstream added the file our patch adds, identically, and nothing else changed:
    # mach sees no change at all, so it's skipped until a later update.
    @logEntryExitHeaderLine
    def testOurAddedFileUpstreamedNoOtherChange(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"extra.c": "int mozilla_extra;\n"}))

        self._assert_nothing_happened(self._run())

    # Upstream added the file our patch adds, identically, in one commit and changed
    # something unrelated in another: our patch can't create the file again.
    @logEntryExitHeaderLine
    def testOurAddedFileUpstreamedWithOtherChange(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"extra.c": "int mozilla_extra;\n", "util.c": "int util = 2;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "util.c": "M"})

    # Upstream deleted the file our patch modifies.
    @logEntryExitHeaderLine
    def testUpstreamDeletesFileOurPatchModifies(self):
        self._make_repo(has_patches=True)
        v2 = dict(self.v1)
        del v2["lib.c"]
        self._add_upstream(NEW_VERSION, v2)

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "lib.c": "R"})

    # Upstream changed the file our patch deletes.
    @logEntryExitHeaderLine
    def testUpstreamChangesFileOurPatchDeletes(self):
        self._make_repo(has_patches=True, patch=DELETE_FILE_PATCH, extra_upstream_files={"unwanted.c": "int unwanted;\n"})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"unwanted.c": "int unwanted = 2;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "unwanted.c": "A"})

    # Upstream deleted the file our patch deletes, and changed something unrelated.
    @logEntryExitHeaderLine
    def testFileOurPatchDeletesAlsoDeletedUpstream(self):
        self._make_repo(has_patches=True, patch=DELETE_FILE_PATCH, extra_upstream_files={"unwanted.c": "int unwanted;\n"})
        v2 = dict(self.v1, **{"util.c": "int util = 2;\n"})
        del v2["unwanted.c"]
        self._add_upstream(NEW_VERSION, v2)

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "util.c": "M"})

    # Upstream made exactly our patch's change, and nothing else: mach sees no change.
    @logEntryExitHeaderLine
    def testOurPatchUpstreamedNoOtherChange(self):
        self._make_repo(has_patches=True)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"lib.c": "".join(PATCHED_LIB_C)}))

        self._assert_nothing_happened(self._run())

    # Upstream made exactly our patch's change in one commit and something unrelated
    # in another: the patch is "previously applied", which --forward refuses.
    @logEntryExitHeaderLine
    def testOurPatchUpstreamedWithOtherChange(self):
        self._make_repo(has_patches=True)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"lib.c": "".join(PATCHED_LIB_C), "util.c": "int util = 2;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "util.c": "M"})

    # One patch file changes two files; upstream conflicts with only one of them, so
    # the patch half-applies. Nothing from the half-applied patch may be left behind.
    @logEntryExitHeaderLine
    def testPatchPartiallyApplies(self):
        self._make_repo(has_patches=True, patch=TWO_FILE_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"util.c": "int util = 2;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "lib.c": "M", "util.c": "M"})

    # ---- Other shapes of change

    # Two patch files: the first adds a file, the second modifies it.
    @logEntryExitHeaderLine
    def testSeveralPatchesAddThenModify(self):
        self._make_repo(has_patches=True, patch=[ADD_FILE_PATCH, MODIFY_EXTRA_PATCH])
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"util.c": "int util = 2;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "util.c": "M", "extra.c": "R"}, {"extra.c": "A"})
        self.assertEqual(self._vendored(self._new_commit_nodes()[1], "extra.c"), "int mozilla_extra = 1;\n")

    # The same two patches, and upstream changed nothing.
    @logEntryExitHeaderLine
    def testSeveralPatchesNoUpstreamChange(self):
        self._make_repo(has_patches=True, patch=[ADD_FILE_PATCH, MODIFY_EXTRA_PATCH])
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Upstream removes a whole directory and adds a new one.
    @logEntryExitHeaderLine
    def testUpstreamAddsAndRemovesDirectories(self):
        self._make_repo(has_patches=True, extra_upstream_files={"olddir/x.c": "int x;\n"})
        v2 = dict(self.v1, **{"newdir/y.c": "int y;\n"})
        del v2["olddir/x.c"]
        self._add_upstream(NEW_VERSION, v2)

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "olddir/x.c": "R", "newdir/y.c": "A"}, {"lib.c": "M"})

    # Our patch adds a file in a directory upstream doesn't have.
    @logEntryExitHeaderLine
    def testPatchAddsFileInNewDirectory(self):
        self._make_repo(has_patches=True, patch=ADD_FILE_IN_NEW_DIR_PATCH)
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"util.c": "int util = 2;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "util.c": "M", "newdir/extra.c": "R"}, {"newdir/extra.c": "A"})

    # Upstream changes a binary file and makes another file executable.
    @logEntryExitHeaderLine
    def testUpstreamChangesBinaryFileAndExecBit(self):
        self._make_repo(has_patches=True, extra_upstream_files={"data.bin": "\x00\x01blob\n"})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"data.bin": "\x00\x02blob2\n"}))
        os.chmod(os.path.join(self.upstream, NEW_VERSION, "util.c"), 0o755)

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "util.c": "M", "data.bin": "M"}, {"lib.c": "M"})
        vendoring_commit = self._new_commit_nodes()[0]
        self.assertEqual(self._hg("files", "-r", vendoring_commit, "-T", "{flags}", os.path.join(VENDOR_DIR, "util.c")), "x", "Lost the exec bit")
        self.assertEqual(self._vendored(vendoring_commit, "data.bin"), "\x00\x02blob2\n")

    # ---- Post-patch actions (scripts run after the patches are applied)

    # A script keeps a source list up to date; upstream changed nothing, so the
    # script writes the same list and the update is spurious.
    @logEntryExitHeaderLine
    def testPostPatchScriptNoUpstreamChange(self):
        self._make_repo(has_patches=True, post_patch_scripts={"list_sources.py": LIST_SOURCES_SCRIPT})
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Upstream adds a source file: the script's updated list goes in the patch commit.
    @logEntryExitHeaderLine
    def testPostPatchScriptUpdatesSourceList(self):
        self._make_repo(has_patches=True, post_patch_scripts={"list_sources.py": LIST_SOURCES_SCRIPT})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"new.c": "int added_upstream;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "new.c": "A"}, {"lib.c": "M", "sources.mozbuild": "M"})
        self.assertIn("'new.c'", self._vendored(self._new_commit_nodes()[1], "sources.mozbuild"))

    # A script generates code from .proto files; upstream changed nothing.
    @logEntryExitHeaderLine
    def testPostPatchGeneratedFilesNoUpstreamChange(self):
        self._make_repo(has_patches=True, post_patch_scripts={"generate.py": GENERATE_FROM_PROTO_SCRIPT},
                        extra_upstream_files={"api.proto": "message Api {}\n"})
        self._add_upstream(NEW_VERSION, self.v1)

        self._assert_nothing_happened(self._run())

    # Upstream adds a .proto file: the script generates a brand-new file, which has to
    # be added in the patch commit. (The existing generated file is removed by
    # vendoring, since upstream doesn't have it, and comes back with the patches.)
    @logEntryExitHeaderLine
    def testPostPatchScriptGeneratesNewFile(self):
        self._make_repo(has_patches=True, post_patch_scripts={"generate.py": GENERATE_FROM_PROTO_SCRIPT},
                        extra_upstream_files={"api.proto": "message Api {}\n"})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"more.proto": "message More {}\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "more.proto": "A", "api.pb.h": "R"},
                                     {"lib.c": "M", "api.pb.h": "A", "more.pb.h": "A"})

    # Upstream adds a file the script doesn't know about, so (like libjpeg's update.py)
    # it fails, after half-writing its output. Nothing it wrote may be left behind.
    @logEntryExitHeaderLine
    def testPostPatchScriptFails(self):
        self._make_repo(has_patches=True, post_patch_scripts={"check_sources.py": CHECK_SOURCES_SCRIPT},
                        kept_files={"known_sources.txt": "lib.c\nutil.c\nold.c\n"})
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"new.c": "int added_upstream;\n"}))

        self._assert_patch_failed_cleanly(self._run(), {"moz.yaml": "M", "lib.c": "M", "new.c": "A"}, conflict=False)

    # Someone running Updatebot in their own checkout may have shelved changes;
    # Updatebot only ever cleans up its own shelf.
    @logEntryExitHeaderLine
    def testUnrelatedShelvesAreKept(self):
        self._make_repo(has_patches=True)
        write(os.path.join(self.repo, VENDOR_DIR, "util.c"), "int util = 99; // work in progress\n")
        self._hg("--config", "extensions.shelve=", "shelve", "-q", "--name", "someone-elses-work")
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"new.c": "int added_upstream;\n"}))

        result = self._run()

        self._assert_job_and_commits(result, {"moz.yaml": "M", "lib.c": "M", "new.c": "A"}, {"lib.c": "M"})
        self.assertIn("someone-elses-work", self._hg("--config", "extensions.shelve=", "shelve", "--list"))

    # Negative today: the only upstream change is to a generated file, which
    # mach's own spurious check ignores.
    @logEntryExitHeaderLine
    def testOnlyGeneratedFileChanges(self):
        self._make_repo(has_patches=True, generated=["gen.h"])
        self._add_upstream(NEW_VERSION, dict(self.v1, **{"gen.h": "#define GENERATED 2\n"}))

        self._assert_nothing_happened(self._run())


if __name__ == '__main__':
    unittest.main(verbosity=0)
