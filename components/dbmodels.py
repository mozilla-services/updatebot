#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from enum import unique, IntEnum


@unique
class JOBSTATUS(IntEnum):
    AWAITING_INITIAL_PLATFORM_TRY_RESULTS = 1
    AWAITING_SECOND_PLATFORMS_TRY_RESULTS = 2
    AWAITING_RETRIGGER_RESULTS = 3
    DONE = 4

    # pymysql expects simple arguments, e.g. ints and strings.
    # Rather than putting foo.value everywhere, we're just going
    # to define the ultimate function pymysql calls to translate
    # the value into unicode for the database operation, and
    # hope this doesn't cause problems down the road.
    def translate(self, _escape_table):
        return str(self.value)


@unique
class JOBOUTCOME(IntEnum):
    PENDING = 1
    COULD_NOT_VENDOR = 2
    BUILD_FAILED = 3
    CLASSIFIED_FAILURES = 4
    UNCLASSIFIED_FAILURES = 5
    ALL_SUCCESS = 6
    ABORTED = 7

    # See above
    def translate(self, _escape_table):
        return str(self.value)


@unique
class JOBTYPE(IntEnum):
    VENDORING = 1
    COMMITALERT = 2

    # See above
    def translate(self, _escape_table):
        return str(self.value)


def transform_job_and_try_results_into_objects(rows):
    """
    In this function we are given an array of rows where the try runs
    have been left-outer-joined into the jobs table, so we have duplicate
    job data.
    We're going to transform this data into objects
    """
    jobs = {}
    for r in rows:
        jobs[r['job_id']] = Job(r)
    for r in rows:
        if r['try_run_id']:
            jobs[r['job_id']].try_runs.append(TryRun(r, id_column='try_run_id'))

    # Make sure the try runs are in ascending order. Uses a database-internal
    # key which is a bad practice, because what if the key turns into a guid
    # in the future?
    for j in jobs:
        jobs[j].try_runs.sort(key=lambda i: i.id)

    return list(jobs.values())


class Job:
    def __init__(self, row=None):
        if row:
            self.id = row['id']
            self.type = JOBTYPE(row['job_type'])
            self.ff_version = row['ff_version']
            self.created = row['created']
            self.library_shortname = row['library']
            self.version = row['version']
            self.status = JOBSTATUS(row['status'])
            self.outcome = JOBOUTCOME(row['outcome'])
            self.bugzilla_id = row['bugzilla_id']
            self.phab_revision = row['phab_revision']
            self.try_runs = []

    def get_try_run_ids(self):
        return ",".join([t.revision for t in self.try_runs])


class TryRun:
    def __init__(self, row=None, id_column='id'):
        if row:
            self.id = row[id_column]
            self.revision = row['revision']
            self.job_id = row['job_id']
            self.purpose = row['purpose']
