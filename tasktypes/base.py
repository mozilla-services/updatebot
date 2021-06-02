#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from datetime import datetime, timedelta

from components.logging import logEntryExit, LogLevel


class BaseTaskRunner:
    @logEntryExit
    def _should_process_new_job(self, library, task):
        if task.frequency == 'every':
            self.logger.log("Task frequency is 'every' so processing the new job.", level=LogLevel.Info)
            return True

        existing_jobs = self.dbProvider.get_all_jobs_for_library(library, self.jobType, include_relinquished=True)
        if not existing_jobs:
            self.logger.log("No prior jobs found, so processing the new job.", level=LogLevel.Info)
            return True

        most_recent_job = existing_jobs[0]

        if task.frequency == 'release':
            if self.config['General']['ff-version'] not in most_recent_job.ff_versions:
                self.logger.log("Firefox version %s is not in the most recent job (revision %s) so processing the new job." % (
                    self.config['General']['ff-version'], most_recent_job.version), level=LogLevel.Info)
                return True
            return False

        try:
            week_count = int(task.frequency.split(" ")[0])
        except Exception as e:
            raise Exception("Could not parse %s as a week frequency" % task.frequency, e)

        if most_recent_job.created + timedelta(weeks=week_count) < datetime.now():
            self.logger.log("The most recent job was processed %s and %s weeks have passed, so processing the new job." % (
                most_recent_job.created, week_count), level=LogLevel.Info)
            return True
        return False
