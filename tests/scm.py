#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import copy
import shutil
import tempfile
import subprocess
import unittest

sys.path.append(".")
sys.path.append("..")
from components.scmprovider import SCMProvider
from components.logging import SimpleLogger, log
from components.commandprovider import CommandProvider
from components.utilities import Struct

from tests.mock_repository import default_test_repo, test_repo_path_wrapper, COMMITS_MAIN, COMMITS_BRANCH2, COMMITS_BRANCH1

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

# 0 index is newest, make a reverse copy
COMMITS_MAIN_R = copy.deepcopy(COMMITS_MAIN)
COMMITS_MAIN_R.reverse()


class TestCommandRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loggingProvider = SimpleLogger(localconfig['Logging'])

        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': loggingProvider
        })

        cls.scmProvider = SCMProvider({})
        cls.scmProvider.update_config({
            'CommandProvider': real_command_runner,
            'LoggingProvider': loggingProvider
        })

        cls.repo_url = test_repo_path_wrapper(default_test_repo())

        cls.scmProvider.initialize()
        cls.scmProvider._ensure_checkout(cls.repo_url)
        # _ensure_checkout leaves us in the checkout; go back so the rest of the
        # process isn't left in a directory that tearDownClass deletes.
        os.chdir(cls.scmProvider.previous_dir_stack.pop())

    @classmethod
    def tearDownClass(cls):
        cls.scmProvider.reset()

    def testCommitsBetween(self):
        # _commits_between runs git in the current directory, so work inside the checkout.
        self.scmProvider._ensure_checkout(self.repo_url)
        try:
            # Test a full commits between test
            commits = self.scmProvider._commits_between(COMMITS_MAIN[-1], COMMITS_MAIN[0])
            for i in range(len(commits)):
                self.assertEqual(commits[i].revision, COMMITS_MAIN_R[i + 1])

            # Test rev1 == rev2
            commits = self.scmProvider._commits_between(COMMITS_MAIN[0], COMMITS_MAIN[0])
            self.assertEqual(len(commits), 0)

            # Test rev1 = rev2^
            commits = self.scmProvider._commits_between(COMMITS_MAIN[1], COMMITS_MAIN[0])
            self.assertEqual(commits[0].revision, COMMITS_MAIN[0])
        finally:
            os.chdir(self.scmProvider.previous_dir_stack.pop())

    def _get_library(self):
        library = Struct(**{
            'repo_url': self.repo_url,
            'name': 'Test-Library',
            'revision': None,
            'should_show_commit_details': False
        })
        task = Struct(**{
            'branch': None
        })
        return library, task

    def testCheckForUpdates(self):
        library, task = self._get_library()

        new_version = COMMITS_MAIN[0]
        library.revision = COMMITS_MAIN[1]
        all_new_upstream_commits, unseen_new_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, None)
        self.assertEqual(len(all_new_upstream_commits), 1)
        self.assertEqual(all_new_upstream_commits[0].revision, COMMITS_MAIN[0])
        self.assertEqual(len(unseen_new_upstream_commits), 1)
        self.assertEqual(unseen_new_upstream_commits[0].revision, COMMITS_MAIN[0])

        new_version = COMMITS_MAIN[0]
        library.revision = COMMITS_MAIN[-1]
        ignoreme = Struct(**{'version': COMMITS_MAIN[3]})
        all_new_upstream_commits, unseen_new_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, ignoreme.version)
        self.assertEqual(len(all_new_upstream_commits), len(COMMITS_MAIN) - 1)
        for i in range(len(COMMITS_MAIN) - 1):
            self.assertEqual(all_new_upstream_commits[i].revision, COMMITS_MAIN_R[i + 1])
        self.assertEqual(len(unseen_new_upstream_commits), 3)
        for i in range(len(unseen_new_upstream_commits) - 1):
            self.assertEqual(unseen_new_upstream_commits[i].revision, COMMITS_MAIN_R[i + len(COMMITS_MAIN_R) - 3])

    def testCheckForUpdatesOnTag(self):
        library, task = self._get_library()

        new_version = 'v0.0.2'
        library.revision = 'v0.0.1'
        all_new_upstream_commits, unseen_new_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, None)
        self.assertEqual(len(all_new_upstream_commits), 2)
        self.assertEqual(len(unseen_new_upstream_commits), 2)

    def testCheckForUpdatesOnTagSkipOne(self):
        library, task = self._get_library()

        new_version = 'v0.0.2'
        library.revision = 'v0.0.1'
        ignoreme = Struct(**{'version': COMMITS_MAIN[-4]})
        all_new_upstream_commits, unseen_new_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, ignoreme.version)
        self.assertEqual(len(all_new_upstream_commits), 2)
        self.assertEqual(len(unseen_new_upstream_commits), 1)

    def testCheckForUpdatesSwitchBranch(self):
        library, task = self._get_library()

        new_version = COMMITS_BRANCH2[0]
        library.revision = COMMITS_BRANCH1[0]
        all_new_upstream_commits, unseen_new_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, None)
        self.assertEqual(len(all_new_upstream_commits), 1)
        self.assertEqual(all_new_upstream_commits[0].revision, COMMITS_BRANCH2[0])
        self.assertEqual(len(unseen_new_upstream_commits), 1)
        self.assertEqual(unseen_new_upstream_commits[0].revision, COMMITS_BRANCH2[0])


class TestMergeCommits(unittest.TestCase):
    r"""
    History where upstream revisions are merge commits, as with PDF.js:

      A (in-tree) -- M1 ---------- c3 -- M2 (new version)
       |\-- s1a -- s1b --/              /
        \-- s2 (dated before M1) ------/

    M1 is the most recent job. All new commits are s1a, s1b, s2, c3; the unseen
    ones are s2 and c3. s2 is older than M1, so git lists it last.

    Separately, Z is a merge of A with its own parent R that adds no commits,
    followed by c4.

    Then P, on a branch that forked at R (before A), is merged after M2 (M3),
    followed by c5. A commit-alert job can be for a commit like P.
    """

    @classmethod
    def _git(cls, *args, date=None):
        env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
                   GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "%s +0000" % (1700000000 + date)
        return subprocess.run(["git", "-C", cls.upstream] + list(args), check=True, capture_output=True, env=env).stdout.decode().strip()

    @classmethod
    def _commit(cls, name, date):
        with open(os.path.join(cls.upstream, name), "w") as f:
            f.write(name)
        cls._git("add", name)
        cls._git("commit", "-q", "-m", name, date=date)
        return cls._git("rev-parse", "HEAD")

    @classmethod
    def setUpClass(cls):
        cls.upstream = tempfile.mkdtemp()
        cls._git("init", "-q", "-b", "main")
        c = cls.commits = {}
        c['R'] = cls._commit("R", 900)
        c['A'] = cls._commit("A", 1000)
        cls._git("checkout", "-q", "-b", "side1")
        c['s1a'] = cls._commit("s1a", 2000)
        c['s1b'] = cls._commit("s1b", 2100)
        cls._git("checkout", "-q", "-b", "side2", c['A'])
        c['s2'] = cls._commit("s2", 1500)
        cls._git("checkout", "-q", "main")
        cls._git("merge", "-q", "--no-ff", "-m", "M1", "side1", date=2200)
        c['M1'] = cls._git("rev-parse", "HEAD")
        c['c3'] = cls._commit("c3", 3000)
        cls._git("merge", "-q", "--no-ff", "-m", "M2", "side2", date=3100)
        c['M2'] = cls._git("rev-parse", "HEAD")
        tree = cls._git("rev-parse", c['A'] + "^{tree}")
        c['Z'] = cls._git("commit-tree", "-p", c['A'], "-p", c['R'], "-m", "Z", tree, date=1100)
        cls._git("branch", "emptymerge", c['Z'])
        cls._git("checkout", "-q", "emptymerge")
        c['c4'] = cls._commit("c4", 1200)
        cls._git("checkout", "-q", "-b", "side3", c['R'])
        c['P'] = cls._commit("P", 1050)
        cls._git("checkout", "-q", "main")
        cls._git("merge", "-q", "--no-ff", "-m", "M3", "side3", date=3200)
        c['M3'] = cls._git("rev-parse", "HEAD")
        c['c5'] = cls._commit("c5", 3300)

        loggingProvider = SimpleLogger(localconfig['Logging'])
        command_runner = CommandProvider({})
        command_runner.update_config({'LoggingProvider': loggingProvider})
        cls.scmProvider = SCMProvider({})
        cls.scmProvider.update_config({'CommandProvider': command_runner, 'LoggingProvider': loggingProvider})
        cls.scmProvider.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.scmProvider.reset()
        shutil.rmtree(cls.upstream, ignore_errors=True)

    def setUp(self):
        SCMProvider.check_for_update.cache_clear()

    def _check(self, in_tree, new_version, most_recent_job_version, show_details=False):
        library = Struct(**{'repo_url': self.upstream, 'name': 'Merge-Library', 'revision': self.commits[in_tree],
                            'should_show_commit_details': show_details})
        task = Struct(**{'branch': None})
        all_commits, unseen = self.scmProvider.check_for_update(library, task, self.commits[new_version], most_recent_job_version)
        return all_commits, unseen

    def _names(self, commits):
        by_hash = {v: k for k, v in self.commits.items()}
        return sorted(by_hash[c.revision] for c in commits)

    def testPreviousJobIsAMergeCommit(self):
        all_commits, unseen = self._check('A', 'M2', self.commits['M1'])
        self.assertEqual(self._names(all_commits), ['c3', 's1a', 's1b', 's2'])
        self.assertEqual(self._names(unseen), ['c3', 's2'])

    def testPreviousJobOlderThanInTree(self):
        # The library has since been updated past the most recent job.
        all_commits, unseen = self._check('M1', 'M2', self.commits['s1a'])
        self.assertEqual(self._names(all_commits), ['c3', 's2'])
        self.assertEqual(self._names(unseen), ['c3', 's2'])

    def testPreviousJobNotUpstream(self):
        all_commits, unseen = self._check('A', 'M2', "0" * 40)
        self.assertEqual(self._names(unseen), self._names(all_commits))

    def testPreviousJobIsTheNewVersion(self):
        all_commits, unseen = self._check('A', 'M2', self.commits['M2'])
        self.assertEqual(len(all_commits), 4)
        self.assertEqual(unseen, [])

    def testPreviousJobIsAMergeWithoutCommits(self):
        all_commits, unseen = self._check('A', 'c4', self.commits['Z'])
        self.assertEqual(self._names(all_commits), ['c4'])
        self.assertEqual(self._names(unseen), ['c4'])

    def testPreviousJobOnBranchForkedBeforeInTree(self):
        # P isn't a descendant of A, but it is one of the new commits and has
        # already been seen, so it mustn't be reported again.
        all_commits, unseen = self._check('A', 'c5', self.commits['P'])
        self.assertEqual(self._names(all_commits), ['P', 'c3', 'c5', 's1a', 's1b', 's2'])
        self.assertEqual(self._names(unseen), ['c3', 'c5', 's1a', 's1b', 's2'])

    def testNewCommitsListedFirst(self):
        all_commits, unseen = self._check('A', 'M2', self.commits['M1'], show_details=True)

        def order(text):
            return sorted(['c3', 's1a', 's1b', 's2'], key=lambda n: text.index(self.commits[n]))
        # git's (date) order puts the new commit s2 below the commits from the previous update...
        self.assertEqual(order(self.scmProvider.build_bug_description(all_commits, 65534)[0]), ['c3', 's1b', 's1a', 's2'])
        # ...so the new commits are moved to the top.
        self.assertEqual(order(self.scmProvider.build_bug_description(all_commits, 65534, new_commits=unseen)[0]), ['c3', 's2', 's1b', 's1a'])
        self.assertEqual(order(self.scmProvider.build_bug_description(all_commits, 65534, options={'verbose-diff': True}, new_commits=unseen)[0]), ['c3', 's2', 's1b', 's1a'])


if __name__ == '__main__':
    unittest.main(verbosity=0)
