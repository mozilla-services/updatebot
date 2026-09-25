#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")

from components.scmprovider import SCMProvider, Commit

GITHUB_REPO = "https://github.com/org/repo"


def make_commit(revision, parent_revision, summary="Do a thing",
                description="A longer description of the thing.",
                files_modified=None):
    # Build a fully-populated Commit without touching a real repository.
    c = Commit("%s|2020-01-01 00:00:00 +0000|2020-01-02 00:00:00 +0000" % revision)
    c.summary = summary
    c.author = "Some Developer <dev@example.com>"
    c.description = description
    c.revision_link = "%s/commit/%s" % (GITHUB_REPO, revision)
    c.parent_revision = parent_revision
    c.files_modified = files_modified if files_modified is not None else ["src/thing.c"]
    c.populated = True
    return c


class TestBuildBugDescription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # build_bug_description / _commit_block don't use the command or logging
        # providers, so a bare provider is enough.
        cls.scm = SCMProvider({})

    def _commits(self):
        # Ordered oldest -> newest, as build_bug_description expects.
        return [
            make_commit("aaaaaaa", "p0000000", summary="First commit"),
            make_commit("bbbbbbb", "aaaaaaa", summary="Second commit"),
            make_commit("ccccccc", "bbbbbbb", summary="Third commit"),
        ]

    # -- _commit_block ---------------------------------------------------------

    def test_commit_block_verbosity_levels(self):
        c = make_commit("abcdef0", "0fedcba", summary="Fix the widget",
                        description="Body of the change.", files_modified=["src/w.c"])

        v1 = self.scm._commit_block(c, 1)
        self.assertIn("abcdef0 by Some Developer", v1)
        self.assertIn(c.revision_link, v1)
        self.assertNotIn("Authored:", v1)
        self.assertNotIn("Fix the widget", v1)
        self.assertNotIn("Files Modified", v1)

        v2 = self.scm._commit_block(c, 2)
        self.assertIn("Authored:", v2)
        self.assertIn("Committed:", v2)
        self.assertIn("Fix the widget", v2)
        self.assertNotIn("Body of the change.", v2)
        self.assertNotIn("Files Modified", v2)

        v3 = self.scm._commit_block(c, 3)
        self.assertIn("Fix the widget", v3)
        self.assertIn("Body of the change.", v3)
        self.assertIn("Files Modified", v3)
        self.assertIn("src/w.c", v3)

    def test_commit_block_requires_populated(self):
        c = Commit("deadbee|d|d")  # not populated
        with self.assertRaises(Exception):
            self.scm._commit_block(c, 1)

    # -- dispatch --------------------------------------------------------------

    def test_dispatch_selects_builder(self):
        commits = self._commits()

        # Tiny budget makes the two behaviors clearly distinguishable: the
        # single-comment builder elides, the chained builder splits instead.
        single = self.scm.build_bug_description(commits, 60, GITHUB_REPO, options={})
        self.assertEqual(len(single), 1)
        self.assertIn("commits elided", single[0])

        chained = self.scm.build_bug_description(commits, 60, GITHUB_REPO, options={"verbose-diff": True})
        self.assertGreater(len(chained), 1)
        self.assertNotIn("commits elided", "".join(chained))

    def test_options_default_is_single_comment(self):
        commits = self._commits()
        # No options passed at all -> single-comment behavior.
        result = self.scm.build_bug_description(commits, 60, GITHUB_REPO)
        self.assertEqual(len(result), 1)
        self.assertIn("commits elided", result[0])

    # -- single-comment behavior ----------------------------------------------

    def test_single_comment_full_when_it_fits(self):
        commits = self._commits()
        result = self.scm.build_bug_description(commits, 65534, GITHUB_REPO, options={})
        self.assertEqual(len(result), 1)
        self.assertNotIn("commits elided", result[0])
        # Full detail present, newest commit first.
        self.assertIn("Third commit", result[0])
        self.assertIn("Files Modified", result[0])
        self.assertLess(result[0].index("Third commit"), result[0].index("First commit"))

    # -- chained behavior ------------------------------------------------------

    def test_chained_single_chunk_when_it_fits(self):
        commits = self._commits()
        result = self.scm.build_bug_description(commits, 65534, GITHUB_REPO, options={"verbose-diff": True})
        self.assertEqual(len(result), 1)
        # No continuation header for a single chunk.
        self.assertNotIn("continued in following comments", result[0])

    def test_chained_splits_with_compare_url_including_oldest(self):
        commits = self._commits()
        result = self.scm.build_bug_description(commits, 200, GITHUB_REPO, options={"verbose-diff": True})
        self.assertGreater(len(result), 1)
        # The compare range starts at the parent of the oldest commit, so the
        # oldest commit itself is included.
        self.assertIn("All 3 commits: %s/compare/p0000000...ccccccc" % GITHUB_REPO, result[0])
        self.assertIn("continued in following comments", result[0])

    def test_chained_no_compare_url_for_unsupported_host(self):
        commits = self._commits()
        result = self.scm.build_bug_description(commits, 200, "https://example.com/repo", options={"verbose-diff": True})
        self.assertGreater(len(result), 1)
        self.assertNotIn("/compare/", "".join(result))

    def test_chained_reduces_verbosity_for_oversized_commit(self):
        # A single commit whose full detail exceeds the limit is rendered at a
        # lower verbosity so it fits, rather than blowing past the comment size.
        big = make_commit("abc1234", "par0000", summary="Summary line",
                          description="D" * 500, files_modified=["src/one.c", "src/two.c"])
        result = self.scm.build_bug_description([big], 200, GITHUB_REPO, options={"verbose-diff": True})
        self.assertEqual(len(result), 1)
        self.assertLessEqual(len(result[0]), 200)      # it now fits within the limit
        self.assertIn("abc1234 by", result[0])         # still identifies the commit
        self.assertNotIn("D" * 500, result[0])         # full description dropped
        self.assertNotIn("Files Modified", result[0])  # file list dropped

    def test_chained_empty_commit_list(self):
        result = self.scm.build_bug_description([], 65534, GITHUB_REPO, options={"verbose-diff": True})
        self.assertEqual(result, [""])


if __name__ == "__main__":
    unittest.main(verbosity=2)
