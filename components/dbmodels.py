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
    RELINQUISHED = 5


@unique
class JOBOUTCOME(IntEnum):
    PENDING = 1
    COULD_NOT_VENDOR = 2
    BUILD_FAILED = 3
    CLASSIFIED_FAILURES = 4
    UNCLASSIFIED_FAILURES = 5
    ALL_SUCCESS = 6
    ABORTED = 7
    CROSS_VERSION_STUB = 8


@unique
class JOBTYPE(IntEnum):
    VENDORING = 1
    COMMITALERT = 2


def transform_job_and_try_results_into_objects(rows):
    """
    In this function we are given an array of rows where the firefox
    versions and try runs have been left-outer-joined into the jobs
    table, so we have duplicate job data.
    We're going to transform this data into objects
    """
    jobs = {}
    for r in rows:
        jobs[r['job_id']] = Job(r)
    for r in rows:
        if r['ff_version']:
            jobs[r['job_id']].ff_versions.add(r['ff_version'])
        if r['try_run_id']:
            jobs[r['job_id']].try_runs.append(TryRun(r, id_column='try_run_id'))

    # Make sure the try runs are in ascending order. Uses a database-internal
    # key which is a bad practice, because what if the key turns into a guid
    # in the future?
    for j in jobs:
        jobs[j].try_runs.sort(key=lambda i: i.id)

    job_list = list(jobs.values())
    job_list.sort(key=lambda x: (x.created, x.id), reverse=True)

    # Every job should be associated with at least one Firefox Version.
    for j in job_list:
        assert len(j.ff_versions) > 0, "Job ID %s does not have any associated Firefox Versions." % j.id

    return job_list


class Job:
    def __init__(self, row=None):
        if row:
            self.id = row['id']
            self.type = JOBTYPE(row['job_type'])
            self.created = row['created']
            self.library_shortname = row['library']
            self.version = row['version']
            self.status = JOBSTATUS(row['status'])
            self.outcome = JOBOUTCOME(row['outcome'])
            self.bugzilla_id = row['bugzilla_id']
            self.phab_revision = row['phab_revision']
            self.ff_versions = set()
            self.try_runs = []

    def get_try_run_ids(self):
        return ",".join([t.revision for t in self.try_runs])

    def get_ff_versions(self):
        return ",".join(self.ff_versions)


class TryRun:
    def __init__(self, row=None, id_column='id'):
        if row:
            self.id = row[id_column]
            self.revision = row['revision']
            self.job_id = row['job_id']
            self.purpose = row['purpose']
