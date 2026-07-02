# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import copy
import shutil
import tempfile
import functools

from components.utilities import Memoize
from components.logging import LogLevel, logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


def repo_and_commit_to_url(repo, commit):
    if any(
        hostname in repo
        for hostname in [
            "https://chromium.googlesource.com",
            "https://aomedia.googlesource.com",
        ]
    ):
        return repo + "/+/" + commit

    # gitlab wants https://domain.com/org/project/-/commit/sha
    # github wants https://domain.com/org/project/commit/sha
    # _But_ github won't redirect from gitlab's format and gitlab will redirect from github's format
    # So we use github's.  Sorry gitlab.
    return repo.replace(".git", "") + "/commit/" + commit


def repo_and_compare_url(repo, old_commit, new_commit):
    if not repo or not any(h in repo for h in ["github.com", "gitlab.com"]):
        return None
    return repo.replace(".git", "") + "/compare/" + old_commit + "..." + new_commit


# Separator line placed between commit blocks in generated bug comments.
COMMENT_SEPARATOR = "----------------------------------------\n"


class Commit:
    def __init__(self, pretty_line):
        parts = pretty_line.split("|")
        self.revision = parts[0]
        self.author_date = parts[1]
        self.commit_date = parts[2]

        self.files_modified = []
        self.files_added = []
        self.files_deleted = []
        self.files_other = []

        # The parent (first-parent) revision, resolved to a concrete hash in
        # populate_details. Used to build a compare URL whose range includes
        # this commit.
        self.parent_revision = None
        self.populated = False

    def populate_details(self, repo, run):
        if self.populated:
            return

        rev_range = [self.revision + "^", self.revision]
        self.parent_revision = run(["git", "rev-parse", self.revision + "^"]).stdout.decode().strip()

        files_changed = run(["git", "diff", "--name-status"] + rev_range).stdout.decode().split("\n")
        for f in files_changed:
            f = f.strip()
            if not f:
                continue

            parts = f.split("\t")
            if parts[0] == 'M':
                self.files_modified.append(parts[1])
            elif parts[0] == 'A':
                self.files_added.append(parts[1])
            elif parts[0] == 'D':
                self.files_deleted.append(parts[1])
            else:
                self.files_other.append(parts[0] + " " + parts[1])

        self.summary = run(["git", "log", "--pretty=%s", "-1", self.revision]).stdout.decode()
        self.author = run(["git", "log", "--pretty=%an <%ae>", "-1", self.revision]).stdout.decode()
        self.description = run(["git", "log", "--pretty=%b", "-1", self.revision]).stdout.decode()
        self.revision_link = repo_and_commit_to_url(repo, self.revision)
        self.populated = True

    def __eq__(self, other):
        if isinstance(other, Commit):
            return self.revision == other.revision
        return False

    def __str__(self):
        return "Commit: " + self.revision

    def __hash__(self):
        return int(self.revision, 16)


def _contains_commit(list_of_commits, revision):
    for c in list_of_commits:
        if revision == c.revision:
            return True
    return False


class SCMProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def _initialize(self):
        self.tmpdirname = tempfile.mkdtemp()
        self.previous_dir_stack = list()  # We use this as a Stack with append/pop
        self._has_checkedout = False

    def _reset(self):
        shutil.rmtree(self.tmpdirname, ignore_errors=True)

    def _ensure_checkout(self, repo_url, specific_revision=None):
        self.previous_dir_stack.append(os.getcwd())

        os.chdir(self.tmpdirname)

        if not self._has_checkedout:
            if not repo_url:
                raise Exception("Wound up in _ensure_checkout but missing a repo_url")

            self.run(["git", "clone", repo_url, "."])

            if specific_revision:
                self.run(["git", "checkout", specific_revision])

            self._has_checkedout = True

    @logEntryExit
    @Memoize
    def check_for_update(self, library, task, new_version, most_recent_job_version):
        # This function uses two tricky variable names:
        #  all_upstream_commits - This means the commits that have occured upstream, on the branch we care about,
        #                         between the library's current revision and the tip of the branch.
        #
        #  unseen_new_upstream_commits - This means the commits that have occured upstream, on the branch we
        #                                care about, that have never been seen in Updatebot before.
        #
        #  The second is always a subset of the first. *However* the only way to figure out the second is by asking
        #  Updatebot 'what jobs (for this library) have you run before'? and examining the result. This is what
        #  Step 5 is about below.
        #
        #  We do return both lists, because while we only need the unseen list for filing a new bug, we need the
        #  all-upstream list to mark any open bugs as (potentially) affecting a new FF version.

        # This try block is used to ensure we clean up and chdir at the end always. It has no except clause,
        # exceptions raised are sent up the stack.
        try:
            # Step 0: Get the repo and update to the correct branch.
            # If no branch is specified, the default branch we clone is assumed to be correct
            self._ensure_checkout(library.repo_url, task.branch)

            # Step 1: Find the common ancestor between the commit we are and new_version
            common_ancestor = self.run(["git", "merge-base", library.revision, new_version]).stdout.decode().strip()
            self.logger.log("Our common ancestor is %s." % (common_ancestor), level=LogLevel.Debug)

            # Step 2: Get the list of commits between the common ancestor and new_version
            all_new_upstream_commits = self._commits_between(common_ancestor, new_version)
            if not all_new_upstream_commits:
                self.logger.log("Checking for updates to %s but no new upstream commits were found from our current in-tree revision %s." % (library.name, library.revision), level=LogLevel.Info)
                return [], []

            # We do have new upstream commits.
            # Step 4: Check if the most recent job was performed on a revision _after_ the library's current revision or _before_.
            # 'After the library's current revision' means:
            #        in m-c we update the library to A
            #        then B was commited upstream
            #        we saw B and then ran a job for it
            #        Resulting in the most recent job being run after the library's current revision
            # 'Before the library's current revision' means:
            #        (the above happens)
            #        in m-c we update the library to B (or maybe even a new rev C with no job)
            #        Resulting in the most recent job (which was for B) occured _before_ the library's current revision
            # We can only do this if we have a most recent job, if we don't we're processing this library for the first time
            if most_recent_job_version:
                most_recent_job_newer_than_library_rev = most_recent_job_version in [c.revision for c in all_new_upstream_commits]
                if most_recent_job_newer_than_library_rev:
                    self.logger.log("The most recent job we have run is for a revision still upstream and not in the mozilla repo.", level=LogLevel.Debug)
                else:
                    self.logger.log("The most recent job we have run is older than the current revision in the mozilla repo.", level=LogLevel.Debug)
            else:
                self.logger.log("We've never run a job for this library before.", level=LogLevel.Debug)
                most_recent_job_newer_than_library_rev = False

            unseen_new_upstream_commits = []
            if most_recent_job_newer_than_library_rev:
                # Step 5: Get the list of commits between the revision for the most recent job
                # and new_version. (We previously confirmed that most_recent_job_version is in the sequence
                # of commits from common_ancestor..new_version)
                unseen_new_upstream_commits = self._commits_between(most_recent_job_version, new_version)
                if len(unseen_new_upstream_commits) == 0:
                    self.logger.log("Already processed revision %s" % (most_recent_job_version), level=LogLevel.Info)
                    return all_new_upstream_commits, []

                # Step 6: Ensure that the unseen list of a subset of the 'all-new' list
                # Techinically this is optional; we could have started at Step 3. But this approach is
                # more conservative and will help us identify unexpected situations that may invalidate
                # our assumptions about how things should happen.
                # Indeed, originally we verified that the unseen list was an ordered subset of the all-new list
                # but this assertion triggered because it may not be.  We may have 1 -> 2 -> 3 with a most recent job
                # of 3.  And then we have a commit added that, when sorted by date, goes 1 -> 2 -> 4 -> 3 -> 5
                # where 5 is a merge commit.  This is perfectly legal and it screws up the assumption that
                # we'll have an ordered subset.
                assert len(all_new_upstream_commits) > len(unseen_new_upstream_commits), "Somehow the all-new list is not greater than the unseen list?"

                error_func = functools.partial(self._print_differing_commit_lists, all_new_upstream_commits, "all_new_upstream_commits", unseen_new_upstream_commits, "unseen_new_upstream_commits")
                if not set(unseen_new_upstream_commits).issubset(set(all_new_upstream_commits)):
                    error_func("unseen_new_upstream_commits is not a subset of all_new_upstream_commits")

            else:  # not most_recent_job_newer_than_library_rev
                # If the most recent job isn't in the list of all new upstream commits; then the entire
                # list of new upstream commits is the list of the unseen upstream commits.
                unseen_new_upstream_commits = all_new_upstream_commits

            # Step 7: Populate the lists with additional details about the commits
            if library.should_show_commit_details:
                [c.populate_details(library.repo_url, self.run) for c in unseen_new_upstream_commits]
                [c.populate_details(library.repo_url, self.run) for c in all_new_upstream_commits]

        finally:
            # Step 8 Return us to the origin directory
            os.chdir(self.previous_dir_stack.pop())

        # Step 9: Return it
        return all_new_upstream_commits, unseen_new_upstream_commits

    def _commits_between(self, revision1, revision2):
        """
        Returns the commits rev1 and rev2, not including rev1.
        If rev1 == rev2, returns an empty list.
        """
        ret = self.run(["git", "log", "--pretty=%H|%ai|%ci", "--no-merges", "%s..%s" % (revision1, revision2)])
        commits = [line.strip() for line in ret.stdout.decode().split("\n")]
        # Put them in order of oldest to newest
        commits.reverse()
        # Populate them into a class but don't get details just yet.
        return [Commit(c) for c in commits if c]

    def _print_differing_commit_lists(self, list_a, list_a_name, list_b, list_b_name, problem):
        self.logger.log("%s." % problem, level=LogLevel.Error)
        self.logger.log("%s (%s)" % (list_a_name, len(list_a)), level=LogLevel.Error)
        for c in list_a:
            self.logger.log("  - %s" % c, level=LogLevel.Error)
        self.logger.log("%s (%s)" % (list_b_name, len(list_b)), level=LogLevel.Error)
        for c in list_b:
            self.logger.log("  - %s" % c, level=LogLevel.Error)
        raise Exception(problem)

    # =================================================================

    def _commit_block(self, c, verbosity):
        # Render a single commit at the given verbosity:
        #   1: revision, author and the revision link
        #   2: + authored/committed dates and the commit summary
        #   3: + the full description and the lists of changed files
        if not c.populated:
            raise Exception("Tried to build bug description; but commit details not populated.")

        s = "%s by %s\n" % (c.revision, c.author)
        s += c.revision_link + "\n"

        if verbosity >= 2:
            s += "Authored: %s\n" % (c.author_date)
            s += "Committed: %s\n" % (c.commit_date)
            s += "\n"
            s += c.summary + "\n"

        if verbosity >= 3:
            s += "\n"
            s += c.description + "\n"

            if c.files_added:
                s += "\n"
                s += "Files Added:\n"
                for f in c.files_added:
                    s += "  - %s\n" % f

            if c.files_deleted:
                s += "\n"
                s += "Files Deleted:\n"
                for f in c.files_deleted:
                    s += "  - %s\n" % f

            if c.files_modified:
                s += "\n"
                s += "Files Modified:\n"
                for f in c.files_modified:
                    s += "  - %s\n" % f

            if c.files_other:
                s += "\n"
                s += "Files Changed:\n"
                for f in c.files_other:
                    s += "  - %s\n" % f
        return s

    # -----------------------------------------------------------------

    def _build_single_comment_description(self, list_of_commits, max_length):
        # Render all the commits into a single comment.
        # Reducing the verbosity until the result fits within max_length.

        # The caller has already copied the list; reorder it newest-first for display.
        list_of_commits.reverse()

        def _get_details(verbosity):
            if verbosity == 0:
                s = COMMENT_SEPARATOR
                s += "%s commits elided, as they are too long for a bugzilla comment.\n\n" % len(list_of_commits)
                s += COMMENT_SEPARATOR
                return s

            s = COMMENT_SEPARATOR
            for c in list_of_commits:
                s += self._commit_block(c, verbosity)
                s += "\n" + COMMENT_SEPARATOR

            return s

        details = _get_details(verbosity=3)
        if len(details) > max_length:
            details = _get_details(verbosity=2)
        if len(details) > max_length:
            details = _get_details(verbosity=1)
        if len(details) > max_length:
            details = _get_details(verbosity=0)
        return [details]

    # -----------------------------------------------------------------

    def _commit_entry(self, c, max_length):
        # A commit block plus its trailing separator, rendered at the highest
        # verbosity (3 -> 1) that fits within max_length.
        # In theory, it falls back to the least verbose form if even that is
        # too long to fit, but this will never happen in practice (knock on wood)
        for verbosity in (3, 2, 1):
            entry = self._commit_block(c, verbosity) + "\n" + COMMENT_SEPARATOR
            if len(entry) <= max_length:
                return entry
        return entry

    def _chunk_comments(self, entries, max_length, first_header=""):
        # Greedily group the already-rendered commit entries into comment-sized
        # strings, each kept under max_length. first_header goes on the first
        # comment only. entries is assumed non-empty; the first comment is
        # seeded with the first entry, then each subsequent entry starts a new
        # comment whenever it would overflow the current one.
        comments = []
        current = first_header + COMMENT_SEPARATOR + entries[0]
        for entry in entries[1:]:
            if len(current) + len(entry) > max_length:
                comments.append(current)
                current = COMMENT_SEPARATOR + entry
            else:
                current += entry
        comments.append(current)
        return comments

    def _build_chained_comment_description(self, list_of_commits, max_length, repo_url):
        # Always emit full commit details, split across as many comments as needed.
        if not list_of_commits:
            return [""]

        # The compare URL must start at the parent of the oldest commit so that
        # the oldest commit itself is included in the range (a `A...B` compare
        # excludes A).
        base_revision = list_of_commits[0].parent_revision
        newest_revision = list_of_commits[-1].revision
        # The caller has already copied the list; reorder it newest-first.
        list_of_commits.reverse()

        # Format each commit at full detail, but drop to a lower verbosity for
        # any single commit whose block would not otherwise fit in a comment.
        # A comment is a leading separator followed by entries, so budget for it.
        entry_budget = max_length - len(COMMENT_SEPARATOR)
        entries = [self._commit_entry(c, entry_budget) for c in list_of_commits]

        # If the whole thing fits in one comment, post it as-is, with no header.
        whole_length = len(COMMENT_SEPARATOR) + sum(len(e) for e in entries)
        if whole_length <= max_length:
            return [COMMENT_SEPARATOR + "".join(entries)]

        # It needs multiple comments: head the first one with a link to the
        # whole commit range so it can be reviewed at a glance. Passing the
        # header to _chunk_comments lets its length count against the budget.
        compare_url = repo_and_compare_url(repo_url, base_revision, newest_revision) if (repo_url and base_revision) else None

        if compare_url:
            first_header = "All %s commits: %s\n(continued in following comments)\n\n" % (len(list_of_commits), compare_url)
        else:
            first_header = ""
        return self._chunk_comments(entries, max_length, first_header)

    # -----------------------------------------------------------------

    def build_bug_description(self, list_of_commits, max_length, repo_url=None, options=None):
        # The commits are ordered oldest to newest. Copy once here since both
        # builders reorder the list in place, then dispatch on the task options.
        options = options or {}
        list_of_commits = copy.deepcopy(list_of_commits)
        if 'verbose-diff' in options:
            return self._build_chained_comment_description(list_of_commits, max_length, repo_url)
        return self._build_single_comment_description(list_of_commits, max_length)
