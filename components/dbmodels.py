#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from enum import unique, IntEnum


@unique
class JOBSTATUS(IntEnum):
    AWAITING_TRY_RESULTS = 1
    AWAITING_RETRIGGER_RESULTS = 2
    DONE = 3

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


class Job:
    def __init__(self, row=None):
        if row:
            self.id = row['id']
            self.library_shortname = row['library']
            self.version = row['version']
            self.status = JOBSTATUS(row['status'])
            self.outcome = JOBOUTCOME(row['outcome'])
            self.bugzilla_id = row['bugzilla_id']
            self.phab_revision = row['phab_revision']
            self.try_revision = row['try_revision']
