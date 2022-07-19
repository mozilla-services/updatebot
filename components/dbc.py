#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.db import MySQLDatabase
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel, logEntryExit


class DatabaseProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, database_config):
        self.config = database_config
        self.db = MySQLDatabase(self.config)

    def _update_config(self, config):
        self.db.update_config(config)

    def updatebot_is_enabled(self):
        return self.db.updatebot_is_enabled()

    def check_database(self):
        return self.db.check_database()

    def delete_database(self):
        return self.db.delete_database()

    def get_configuration(self):
        return self.db.get_configuration()

    def get_all_statuses(self):
        return self.db.get_all_statuses()

    def get_all_outcomes(self):
        return self.db.get_all_outcomes()

    def get_all_jobs(self):
        return self.db.get_all_jobs()

    def get_all_try_runs(self):
        return self.db.get_all_try_runs()

    def get_all_jobs_for_library(self, library, jobtype):
        jobs = self.db.get_all_jobs_for_library(library)
        return [j for j in jobs if j.type == jobtype]

    def get_job(self, library, new_version):
        return self.db.get_job(library, new_version)

    # Only used for testing purposes, in the real database, we don't delete records.
    def delete_job(self, library=None, version=None, job_id=None):
        return self.db.delete_job(library=library, version=version, job_id=job_id)

    def create_job(self, jobtype, library, new_version, status, outcome, bug_id=0):
        assert self.config['General']['ff-version'], "Called create_job but self.config['General']['ff-version'] was not provided"
        return self.db.create_job(jobtype, library, new_version, self.config['General']['ff-version'], status, outcome, bug_id)

    @logEntryExit
    def update_job_status(self, existing_job, newstatus=None, newoutcome=None):
        if newstatus:
            existing_job.status = newstatus
        if newoutcome:
            existing_job.outcome = newoutcome
        return self.db.update_job_status(existing_job)

    def update_job_relinquish(self, existing_job):
        existing_job.relinquished = True
        return self.db.update_job_relinquish(existing_job)

    def update_job_add_bug_id(self, existing_job, bug_id):
        return self.db.update_job_add_bug_id(existing_job, bug_id)

    def update_job_add_phab_revision(self, existing_job, phab_revision):
        return self.db.update_job_add_phab_revision(existing_job, phab_revision)

    def update_job_ff_versions(self, existing_job, ff_version_to_add):
        return self.db.update_job_ff_versions(existing_job, ff_version_to_add)

    def add_try_run(self, existing_job, try_revision, try_run_type):
        return self.db.add_try_run(existing_job, try_revision, try_run_type)

    def print(self):
        def get_column_widths(objects, columns):
            widths = []

            for c in columns:
                thiswidth = len(c) + 2
                for o in objects:
                    thislen = len(str(getattr(o, c))) + 2
                    if thislen > thiswidth:
                        thiswidth = thislen
                widths.append(thiswidth)
            return widths

        def print_line(widths):
            line = "+"
            for w in widths:
                line += "-" * w + "+"
            self.logger.log(line, level=LogLevel.Debug)

        def print_values(values, widths):
            assert(len(values) == len(widths))

            line = "| "
            for i in range(len(values)):
                line += str(values[i]).ljust(widths[i] - 2) + " | "
            self.logger.log(line, level=LogLevel.Debug)

        def print_object_values(obj, columns, widths):
            print_values([getattr(obj, c) for c in columns], widths)

        def print_objects(name, objects, columns):
            widths = get_column_widths(objects, columns)
            self.logger.log("", level=LogLevel.Debug)
            self.logger.log("", level=LogLevel.Debug)
            self.logger.log(name, level=LogLevel.Debug)
            print_line(widths)
            print_values(columns, widths)
            print_line(widths)
            for o in objects:
                print_object_values(o, columns, widths)
                print_line(widths)

        config_columns = ['k', 'v']
        print_objects("CONFIGURATION", self.get_configuration(), config_columns)

        status_columns = ['id', 'name']
        print_objects("STATUSES", self.get_all_statuses(), status_columns)
        print_objects("OUTCOMES", self.get_all_outcomes(), status_columns)

        job_columns = ['id', 'type', 'created', 'library_shortname', 'version',
                       'status', 'outcome', 'relinquished', 'bugzilla_id', 'phab_revision', 'ff_versions']
        print_objects("JOBS", self.get_all_jobs(), job_columns)

        try_run_columns = ['id', 'revision', 'job_id', 'purpose']
        print_objects("TRY RUNS", self.get_all_try_runs(), try_run_columns)
