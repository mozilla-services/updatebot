#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import time
import copy
import random
import unittest

sys.path.append(".")
sys.path.append("..")
from components.dbmodels import JOBSTATUS, JOBOUTCOME, JOBTYPE
from components.dbc import DatabaseProvider
from components.logging import SimpleLoggerConfig, log
from components.utilities import Struct

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)


def transform_db_config_to_tmp_db(config):
    database_name = 'updatebot_test_' \
        + str(int(time.time() * 1000000)) \
        + "_" \
        + str(random.randint(0, 10000))

    # Without deepcopy, we would be editing the original localconfig
    #     which would be stored in the Database's instance.
    # One test would finish, but not del the DB; and a second DB would be
    #     created which would edit the localconfig. When we went to del
    #     the first DB, it would use the db value from the shared localconfig
    config = copy.deepcopy(localconfig['Database'])
    config['db'] = database_name
    config['use_tmp_db'] = True

    return config


class TestDatabaeQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])

        cls.db = DatabaseProvider(db_config)
        cls.db.update_config(SimpleLoggerConfig)
        cls.db.check_database()

    def testJobs(self):
        library = Struct(**{
            'name': 'test_library',
            'yaml_path': 'path/to/moz.yaml',
        })
        version = "test_new_version"
        bugid = 50
        phab_revision = 30
        try_link = "test_try_link"

        try:
            self.assertEqual(None, self.db.get_job(library, version))

            self.db.create_job(JOBTYPE.VENDORING, 78, library, version, 'db test',
                               JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS, JOBOUTCOME.PENDING, bugid, phab_revision, try_link)

            newJob = self.db.get_job(library, version)
            self.assertNotEqual(None, newJob)
            self.assertEqual(newJob.type, JOBTYPE.VENDORING)
            self.assertEqual(newJob.ff_version, 78)
            self.assertEqual(newJob.library_shortname, library.name)
            self.assertEqual(newJob.version, version)
            self.assertEqual(newJob.status, JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS)
            self.assertEqual(newJob.outcome, JOBOUTCOME.PENDING)
            self.assertEqual(newJob.bugzilla_id, bugid)
            self.assertEqual(newJob.phab_revision, phab_revision)
            self.assertEqual(len(newJob.try_runs), 1)
            self.assertEqual(newJob.try_runs[0].revision, try_link)
            self.assertEqual(newJob.try_runs[0].job_id, newJob.id)
            self.assertEqual(newJob.try_runs[0].purpose, 'db test')
        finally:
            self.db.delete_job(job_id=newJob.id)


if __name__ == '__main__':
    unittest.main(verbosity=0)
