#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import functools

from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.logging import LogLevel, logEntryExit
from components.bugzilla import CommentTemplates


class CommitAlertTaskRunner:
    def __init__(self, provider_dictionary, config_dictionary):
        self.__dict__.update(provider_dictionary)
        self.logger = copy.deepcopy(self.loggingProvider)
        self.logger.log = functools.partial(self.logger.log, category=self.__class__.mro()[0].__name__)
        self.config_dictionary = config_dictionary

    # ====================================================================

    def process_task(self, library, task):
        assert task.type == 'commit-alert'
        my_ff_version = self.config_dictionary['General']['ff-version']

        all_library_jobs = self.dbProvider.get_all_jobs_for_library(library)
        all_library_jobs = [j for j in all_library_jobs if j.type == JOBTYPE.COMMITALERT]
        # Order them from newest to oldest
        sorted(all_library_jobs, key=lambda x: x.created)

        unseen_upstream_commits = self.scmProvider.check_for_update(library, task, all_library_jobs)
        if not unseen_upstream_commits:
            # We logged the reason for this already; just return
            return

        newest_commit = unseen_upstream_commits[-1]
        existing_job = self.dbProvider.get_job(library, newest_commit.revision)
        if existing_job:
            if my_ff_version in existing_job.ff_versions:
                # We've already seen this revision, and we've already associated it with this FF version
                self.logger.log("We found a job with id %s for revision %s that was already processed for this ff version (%s)." % (
                    existing_job.id, newest_commit.revision, my_ff_version), level=LogLevel.Info)
                return

            self.logger.log("We found a job with id %s for revision %s but it hasn't been processed for this ff version (%s) yet." % (
                existing_job.id, newest_commit.revision, my_ff_version), level=LogLevel.Info)
            self.bugzillaProvider.mark_ff_version_affected(existing_job.bugzilla_id, my_ff_version)

            self.dbProvider.update_job_ff_versions(existing_job, my_ff_version)
            existing_job.ff_versions.add(my_ff_version)
            return

        self.logger.log("Processing %s for %s upstream revisions culminating in %s." % (library.name, len(unseen_upstream_commits), newest_commit.revision), level=LogLevel.Info)
        self._process_new_commits(library, task, unseen_upstream_commits, all_library_jobs)

    # ====================================================================

    @logEntryExit
    def _process_new_commits(self, library, task, new_commits, all_library_jobs):
        assert new_commits

        newest_commit = new_commits[-1]

        filtered_commits = new_commits
        if task.filter == 'security':
            # We don't support this filter yet
            pass
        elif task.filter == 'source-extensions':
            # We don't support this filter yet
            pass
        elif task.filter == 'none':
            pass
        else:
            raise Exception("In a commit-altert task for library %s I got a filter '%s' I don't know how to handle." % (library.name, task.filter))

        depends_on = all_library_jobs[0].bugzilla_id if all_library_jobs else None
        description = CommentTemplates.EXAMINE_COMMITS_BODY(library, task, self.scmProvider.build_bug_description(filtered_commits))

        bugzilla_id = self.bugzillaProvider.file_bug(library, CommentTemplates.EXAMINE_COMMITS_SUMMARY(library, new_commits), description, task.cc, needinfo=task.needinfo, depends_on=depends_on, moco_confidential=True)
        self.dbProvider.create_job(JOBTYPE.COMMITALERT, library, newest_commit.revision, JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS, bugzilla_id, phab_revision=None, try_run=None, try_run_type=None)
