#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import Struct

JOBSTATUS = Struct(**{
    'COULD_NOT_VENDOR': 1,
    'VENDORED': 2,
    'AWAITING_TRY_RESULTS': 3
})


class Job:
    def __init__(self, row=None):
        if row:
            self.id = row['id']
            self.library_shortname = row['library']
            self.version = row['version']
            self.status = row['status']
            self.bugzilla_id = row['bugzilla_id']
            self.try_revision = row['try_revision']


class Library:
    def __init__(self, row=None):
        if row:
            self.id = row['id']
            self.shortname = row['shortname']
            self.yaml_path = row['yaml_path']
            self.bugzilla_product = row['bugzilla_product']
            self.bugzilla_component = row['bugzilla_component']
            self.maintainer = row['maintainer']
            self.fuzzy_query = row['fuzzy_query']
