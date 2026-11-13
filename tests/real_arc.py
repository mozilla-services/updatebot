#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Run Updatebot's Phabricator submission with the real arc, installed the way the
Docker image installs it (tests/setup_real_arc.py), against tests/fake_conduit.py.
These catch arc's own behaviour: its prompts, exit codes and output, and how it
handles binary and huge files.

Skipped if arc isn't on the PATH, unless UPDATEBOT_REAL_ARC=required (as in CI).
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess
from unittest import mock

sys.path.append(".")
sys.path.append("..")
import components.utilities
from apis.phabricator import PhabricatorProvider, ArcNeedsInputError, DiffTooLargeError
from components.commandprovider import CommandProvider
from components.logging import SimpleLogger, LogLevel
from tests.fake_conduit import FakeConduit, USER_PHID

ARC = shutil.which("arc")
REQUIRED = os.environ.get("UPDATEBOT_REAL_ARC") == "required"
AUTHOR = "Updatebot <updatebot@example.com>"
# For the clone, where arc amends commits too
HGRC = """[ui]
username = %s
[extensions]
evolve =
""" % AUTHOR
# Used if arc wasn't installed by tests/setup_real_arc.py, which saves Firefox's
FIREFOX_ARCCONFIG = {"repository.callsign": "FIREFOXAUTOLAND", "history.immutable": False}


def firefox_arcconfig(conduit_url):
    saved = os.path.join(os.path.dirname(os.path.dirname(ARC)), "arcconfig")
    arcconfig = FIREFOX_ARCCONFIG
    if os.path.exists(saved):
        with open(saved) as f:
            arcconfig = json.load(f)
    return dict(arcconfig, **{"phabricator.uri": conduit_url})


def arc_marks_non_utf8_files_binary():
    # Whether arc has the image's patch to accept its non-UTF-8 prompt without a TTY
    workflow = os.path.join(os.path.dirname(os.path.realpath(ARC)), "..", "src", "workflow", "ArcanistDiffWorkflow.php")
    with open(workflow) as f:
        return "Mozilla: without a TTY" in f.read()


@unittest.skipUnless(ARC or REQUIRED, "arc isn't installed; see tests/setup_real_arc.py")
class TestRealArc(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ARC, "UPDATEBOT_REAL_ARC=required, but arc isn't on the PATH")
        self.conduit = FakeConduit().start()
        self.addCleanup(self.conduit.stop)

        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        home = os.path.join(self.dir, "home")
        os.mkdir(home)
        arcrc = os.path.join(home, ".arcrc")
        with open(arcrc, "w") as f:
            json.dump({"hosts": {self.conduit.url + "api/": {"token": "cli-" + "a" * 28}}}, f)
        os.chmod(arcrc, 0o600)
        environ = mock.patch.dict(os.environ, {"HOME": home})
        environ.start()
        self.addCleanup(environ.stop)

        # Like the gecko checkout: a clone, so arc can tell which commits are ours
        upstream = os.path.join(self.dir, "upstream")
        subprocess.run(["hg", "init", upstream], check=True)
        self.repo = upstream
        self.write(".arcconfig", json.dumps(firefox_arcconfig(self.conduit.url), indent=2))
        self.write("lib/foo.c", "int foo;\n")
        self.commit("Base")
        self.repo = os.path.join(self.dir, "repo")
        subprocess.run(["hg", "clone", "-q", upstream, self.repo], check=True)
        with open(os.path.join(self.repo, ".hg", "hgrc"), "a") as f:
            f.write(HGRC)
        previous_dir = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, previous_dir)

        self.warnings = []
        logger = SimpleLogger({'local': True})
        original_log = logger.log
        logger.log = lambda *args, level=LogLevel.Info, **kwargs: (self.warnings.append(args[0]) if level == LogLevel.Warning else None, original_log(*args, level=level, **kwargs))
        self.commands = CommandProvider({})
        self.commands.update_config({'LoggingProvider': logger})
        self.arc_diffs = 0
        original_run = self.commands.run

        def counting_run(args, *a, **kw):
            if args[:2] == ["arc", "diff"]:
                self.arc_diffs += 1
            return original_run(args, *a, **kw)
        self.commands.run = counting_run
        self.phab = PhabricatorProvider({'url': self.conduit.url})
        self.phab.update_config({'CommandProvider': self.commands, 'LoggingProvider': logger})

        # A failure shouldn't spend minutes in the retry decorator's backoff
        sleep = mock.patch.object(components.utilities.time, "sleep", lambda s: None)
        sleep.start()
        self.addCleanup(sleep.stop)

    def write(self, path, contents):
        path = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(contents, bytes) else "w") as f:
            f.write(contents)

    def commit(self, message):
        # HOME is a fresh directory, so nothing else gives Mercurial a username
        subprocess.run(["hg", "-R", self.repo, "commit", "-q", "--addremove", "--user", AUTHOR, "-m", message], check=True)

    def revision(self, revision_id):
        return self.conduit.revisions[int(revision_id)]

    # ==================================================================
    def testSubmitOneCommit(self):
        self.write("lib/foo.c", "int foo = 2;\n")
        self.commit("Bug 123 - Update foo to abcdef")

        revisions = self.phab.submit_patches(123, 1)

        self.assertEqual(revisions, ["1"])
        self.assertEqual(self.revision(1)["title"], "Bug 123 - Update foo to abcdef")
        self.assertEqual(self.revision(1)["bugzilla.bug-id"], "123")
        self.assertEqual(list(self.conduit.diffs[1]["changes"]), ["lib/foo.c"])

    def testSubmitAStackOfCommits(self):
        # A vendoring commit and a patches commit, submitted one at a time with hg next
        self.write("lib/foo.c", "int foo = 2;\n")
        self.commit("Bug 123 - Update foo to abcdef")
        self.write("lib/foo.c", "int foo = 3;\n")
        self.commit("Bug 123 - Apply mozilla patches for foo")

        revisions = self.phab.submit_patches(123, 2)

        self.assertEqual(revisions, ["1", "2"])
        self.assertEqual(self.revision(2)["parents"], [self.revision(1)["phid"]])
        self.assertEqual([self.revision(r)["bugzilla.bug-id"] for r in revisions], ["123", "123"])
        self.assertEqual(self.revision(2)["title"], "Bug 123 - Apply mozilla patches for foo")

    def testReviewersAbandoningAndCommandeering(self):
        self.write("lib/foo.c", "int foo = 2;\n")
        self.commit("Bug 123 - Update foo to abcdef")
        (revision,) = self.phab.submit_patches(123, 1)
        self.conduit.projects["PHID-PROJ-reviewers00000000"] = "foo-reviewers"
        self.conduit.users["PHID-USER-maintainer00000000"] = "maintainer"

        self.phab.set_reviewer(revision, "#foo-reviewers")
        self.phab.set_reviewer(revision, "maintainer")
        self.assertEqual(self.revision(revision)["reviewers"], ["PHID-PROJ-reviewers00000000", "PHID-USER-maintainer00000000"])

        self.assertFalse(self.phab.is_commandeered(revision))
        self.phab.abandon(revision)
        self.assertEqual(self.revision(revision)["status"], "abandoned")
        self.phab.abandon(revision)  # Already closed: a warning, not an error
        self.assertTrue(any("already closed" in w for w in self.warnings), self.warnings)

        self.revision(revision).update(status="needs-review", authorPHID="PHID-USER-maintainer00000000")
        self.assertTrue(self.phab.is_commandeered(revision))
        self.phab.abandon(revision)  # Someone else's now: left alone
        self.assertEqual(self.revision(revision)["status"], "needs-review")
        self.assertNotEqual(self.revision(revision)["authorPHID"], USER_PHID)

    def testFilesThatArentUTF8(self):
        # Like PDF.js's cmaps: binary, but without the NUL bytes arc looks for
        self.write("lib/font.bcmap", b"\xe0\x81 old\n")
        self.commit("Add a font")
        self.write("lib/font.bcmap", b"\xe0\x81 cmap \xff\xfe data\n")
        self.write("lib/new.bcmap.br", b"\xff\xfe brotli \xe0\n")
        self.commit("Bug 123 - Update foo to abcdef")

        patched = arc_marks_non_utf8_files_binary()
        # So CI's log shows which behaviour the image's arc has
        print("arc %s the image's patch to mark non-UTF-8 files as binary, so testing that it %s" % (
            ("has", "uploads them") if patched else ("doesn't have", "stops to ask")), flush=True)
        if patched:
            (revision,) = self.phab.submit_patches(123, 1)
            uploaded = sorted(f["data"] for f in self.conduit.files.values())
            self.assertEqual(uploaded, sorted([b"\xe0\x81 old\n", b"\xe0\x81 cmap \xff\xfe data\n", b"\xff\xfe brotli \xe0\n"]))
            self.assertEqual(self.revision(revision)["bugzilla.bug-id"], "123")
        else:
            with self.assertRaises(ArcNeedsInputError) as e:
                self.phab.submit_patches(123, 1)
            self.assertEqual(e.exception.prompt, "Do you want to mark these 2 file(s) as binary and continue? [Y/n]")
            self.assertEqual(self.arc_diffs, 1, "Asked arc again, which would get the same question")

    def testDiffTooLarge(self):
        self.write("lib/huge.h", "".join("#define LINE_%d %d\n" % (i, i) for i in range(250000)))
        self.commit("Bug 123 - Update foo to abcdef")

        with self.assertRaises(DiffTooLargeError) as e:
            self.phab.submit_patches(123, 1)
        self.assertIn("lib/huge.h", str(e.exception))
        self.assertEqual(self.arc_diffs, 1, "Retried a diff that can never be submitted")
        self.assertEqual(self.conduit.revisions, {})


if __name__ == '__main__':
    unittest.main(verbosity=0)
