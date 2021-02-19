#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.logging import LogLevel, logEntryExit


class CommitAlertTaskRunner:
    def __init__(self, provider_dictionary, config_dictionary):
        self.__dict__.update(provider_dictionary)
        self.logger = self.loggingProvider
        self.config_dictionary = config_dictionary

    # ====================================================================

    def process_task(self, library, task):
        assert task.type == 'commit-alert'

        new_commits = self.scmProvider.check_for_update(library)
        newest_commit = new_commits[-1]
        if not new_commits:
            self.logger.log("Processing %s but no new commits were found." % library.name, level=LogLevel.Info)
            return

        self.logger.log("Processing %s for an upstream revision %s." % (library.name, newest_commit.revision), level=LogLevel.Info)
        existing_job = self.dbProvider.get_job(library, newest_commit.revision)
        if existing_job:
            self.logger.log("already processed revision %s in bug %s" % (newest_commit.revision, existing_job.bugzilla_id), level=LogLevel.Info)
            return

        self.logger.log("%s is a brand new revision to updatebot." % (newest_commit.revision), level=LogLevel.Info)
        self._process_new_commits(library, task, new_commits)

    # ====================================================================

    @logEntryExit
    def _process_new_commits(self, library, task, new_commits):
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

        description = str(filtered_commits)

        bugzilla_id = self.bugzillaProvider.file_bug(library, newest_commit.revision, newest_commit.timestamp, description, task.cc)
        self.dbProvider.create_job(JOBTYPE.COMMITALERT, library, newest_commit.revision, JOBSTATUS.DONE, JOBOUTCOME.DONE, bugzilla_id, phab_revision=None, try_run=None, try_run_type=None)
