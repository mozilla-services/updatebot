#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from datetime import datetime, timedelta

from components.logging import logEntryExit, LogLevel


class BaseTaskRunner:
    @logEntryExit
    def _should_process_new_job(self, library, task, new_version=None):
        def frequency_type():
            if 'commit' in task.frequency:
                return 'commit'
            elif 'week' in task.frequency:
                return 'week'
            return task.frequency

        if task.frequency == 'every':
            self.logger.log("Task frequency is 'every' so processing the new job.", level=LogLevel.Info)
            return True

        existing_jobs = self.dbProvider.get_all_jobs_for_library(library, self.jobType)
        if not existing_jobs and frequency_type() in ['week', 'release']:
            self.logger.log("No prior jobs found, so processing the new job.", level=LogLevel.Info)
            return True

        most_recent_job = existing_jobs[0] if existing_jobs else None

        if task.frequency == 'release':
            if self.config['General']['ff-version'] not in most_recent_job.ff_versions:
                self.logger.log("Firefox version %s is not in the most recent job (revision %s) so processing the new job." % (
                    self.config['General']['ff-version'], most_recent_job.version), level=LogLevel.Info)
                return True
            return False

        # Check week/commit requirement, but more complicated because you can specify both
        week_count = 0
        commit_count = 0
        if 'week' in task.frequency and 'commit' in task.frequency:
            assert "," in task.frequency
            week_half, commit_half = task.frequency.split(",")
        else:
            week_half = task.frequency if 'week' in task.frequency else ""
            commit_half = task.frequency if 'commit' in task.frequency else ""

        try:
            if week_half:
                week_count = int(week_half.strip().split(" ")[0])
            if commit_half:
                commit_count = int(commit_half.strip().split(" ")[0])
        except Exception as e:
            raise Exception("Could not parse '%s' or '%s' as a frequency" % (week_half, commit_half), e)

        if week_count > 0:
            do_not_process_job = most_recent_job.created + timedelta(weeks=week_count) > datetime.now()
            self.logger.log("The most recent job was processed %s and we process jobs every %s weeks, so %sprocessing the new job." % (
                most_recent_job.created, week_count, "not " if do_not_process_job else ""), level=LogLevel.Info)
            if do_not_process_job:
                return False

        if commit_count > 0:
            all_upstream_commits, unseen_upstream_commits = self.scmProvider.check_for_update(library, task, new_version, existing_jobs)
            commits_since_in_tree = len(all_upstream_commits)
            commits_since_new_job = len(unseen_upstream_commits)

            # Take the smaller number
            if commits_since_in_tree < commits_since_new_job:
                new_commits = commits_since_in_tree
                explanation = "the version in-tree (and %s since the last job)" % commits_since_new_job
            else:
                new_commits = commits_since_new_job
                explanation = "the last job (and %s since the version in tree)" % commits_since_in_tree

            self.logger.log("There have been %s commits since %s, and we need at least %s, so %sprocessing the new job." % (
                new_commits, explanation, commit_count, "not " if commit_count > new_commits else ""), level=LogLevel.Info)

            if commit_count > new_commits:
                return False

        return True
