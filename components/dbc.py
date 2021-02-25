#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.db import MySQLDatabase
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel


class DatabaseProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, database_config):
        self.db = MySQLDatabase(database_config)

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

    def get_all_jobs_for_library(self, library):
        return self.db.get_all_jobs_for_library(library)

    def get_all_active_jobs_for_library(self, library):
        all_jobs = self.db.get_all_jobs_for_library(library)
        return [j for j in all_jobs if j.status != JOBSTATUS.DONE]

    def get_job(self, library, new_version):
        return self.db.get_job(library, new_version)

    # Only used for testing purposes, in the real database, we don't delete records.
    def delete_job(self, library=None, version=None, job_id=None):
        return self.db.delete_job(library=library, version=version, job_id=job_id)

    def create_job(self, jobtype, library, new_version, try_run_type, status, outcome, bug_id, phab_revision=None, try_run=None):
        return self.db.create_job(jobtype, library, new_version, try_run_type, status, outcome, bug_id, phab_revision, try_run)

    def update_job_status(self, existing_job):
        return self.db.update_job_status(existing_job)

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

        job_columns = ['id', 'library_shortname', 'version',
                       'status', 'outcome', 'bugzilla_id', 'phab_revision']
        print_objects("JOBS", self.get_all_jobs(), job_columns)

        try_run_columns = ['id', 'revision', 'job_id', 'purpose']
        print_objects("TRY RUNS", self.get_all_try_runs(), try_run_columns)
