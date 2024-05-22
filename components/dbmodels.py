#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from enum import unique, IntEnum


# If not separate-platforms,
#     goes straight to
#     SECOND_PLATFORMS
#      ┌──────────────── CREATED ────────────────────┐ Skips to DONE on error
#      │                    │                        │
#      │                    ▼                        │
#      │   AWAITING_INITIAL_PLATFORM_TRY_RESULTS ────|
#      │                    │                        │
#      │                    ▼                        │
#      └─► AWAITING_SECOND_PLATFORMS_TRY_RESULTS ────|
#                           │                        │
#                           │                        │
#                           ▼                        │
#               AWAITING_RETRIGGER_RESULTS           |
#                           │                        │
#                           ▼                        │
#                          DONE ◄────────────────────┘
@unique
class JOBSTATUS(IntEnum):
    AWAITING_INITIAL_PLATFORM_TRY_RESULTS = 1
    AWAITING_SECOND_PLATFORMS_TRY_RESULTS = 2
    AWAITING_RETRIGGER_RESULTS = 3
    DONE = 4
    RELINQUISHED = 5  # No longer used, but still in the database
    CREATED = 6


@unique
class JOBOUTCOME(IntEnum):
    PENDING = 1
    COULD_NOT_VENDOR = 2
    BUILD_FAILED = 3
    CLASSIFIED_FAILURES = 4
    UNCLASSIFIED_FAILURES = 5
    ALL_SUCCESS = 6
    ABORTED = 7  # No longer used, but still in the database
    CROSS_VERSION_STUB = 8
    COULD_NOT_COMMIT = 9
    COULD_NOT_PATCH = 10
    COULD_NOT_COMMIT_PATCHES = 11
    COULD_NOT_SUBMIT_TO_TRY = 12
    COULD_NOT_SUBMIT_TO_PHAB = 13
    COULD_NOT_REVENDOR = 14
    COULD_NOT_SET_PHAB_REVIEWER = 15
    COULD_NOT_ABANDON = 16
    SPURIOUS_UPDATE = 17
    UNEXPECTED_CREATED_STATUS = 18


@unique
class JOBTYPE(IntEnum):
    VENDORING = 1
    COMMITALERT = 2


def transform_job_and_try_results_into_objects(rows):
    """
    In this function we are given an array of rows where the firefox
    versions, phab revisions, and try runs have been left-outer-joined
    into the jobs table, so we have duplicate job data.
    We're going to transform this data into objects
    """
    jobs = {}
    for r in rows:
        # This will recreate the Job object a bunch of times, but that's fine, whateber
        jobs[r['id']] = Job(r)

    for r in rows:
        if r['ff_version']:
            jobs[r['id']].ff_versions.add(r['ff_version'])
        if r['try_run_id']:
            # Ensure we only add a try run once
            new = TryRun(r, column_prefix='try_run_')
            if not any([t for t in jobs[r['id']].try_runs if t.id == new.id]):
                jobs[r['id']].try_runs.append(new)
        if r['phab_revision_id']:
            # Ensure we only add a phabricator revision once
            new = PhabRevision(r, column_prefix='phab_revision_')
            if not any([t for t in jobs[r['id']].phab_revisions if t.id == new.id]):
                jobs[r['id']].phab_revisions.append(new)

    # Make sure the try runs are in ascending order. Uses a database-internal
    # key which is a bad practice, because what if the key turns into a guid
    # in the future?
    for j in jobs:
        jobs[j].try_runs.sort(key=lambda i: i.id)
        jobs[j].phab_revisions.sort(key=lambda i: i.id)

    job_list = list(jobs.values())
    job_list.sort(key=lambda x: (x.created, x.id), reverse=True)

    # Create a linked list of job references
    for i in range(len(job_list) - 1):
        job_list[i].prior_job = job_list[i + 1]

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
            self.relinquished = not not row['relinquished']
            self.bugzilla_id = row['bugzilla_id']
            self.ff_versions = set()
            self.phab_revisions = []
            self.try_runs = []

    def get_try_run_ids(self):
        return ",".join([t.revision for t in self.try_runs])

    def get_phab_revision_ids(self):
        return ",".join([t.revision for t in self.phab_revisions])

    def get_ff_versions(self):
        return ",".join(self.ff_versions)

    def __repr__(self):
        return "<Job id: %s library: %s>" % (self.id, self.library_shortname)


class TryRun:
    def __init__(self, row=None, column_prefix=''):
        if row:
            self.id = row[column_prefix + 'id']
            self.revision = row[column_prefix + 'revision']
            self.job_id = row[column_prefix + 'job_id']
            self.purpose = row[column_prefix + 'purpose']


class PhabRevision:
    def __init__(self, row=None, column_prefix=''):
        if row:
            self.id = row[column_prefix + 'id']
            self.revision = row[column_prefix + 'revision']
            self.job_id = row[column_prefix + 'job_id']
            self.purpose = row[column_prefix + 'purpose']
