#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import time
import copy
import random
import unittest
from unittest import mock

import pymysql

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


def transform_db_config_to_tmp_db(oldconfig):
    database_name = 'updatebot_test_' \
        + str(int(time.time() * 1000000)) \
        + "_" \
        + str(random.randint(0, 10000))

    # Without deepcopy, we would be editing the original localconfig
    #     which would be stored in the Database's instance.
    # One test would finish, but not del the DB; and a second DB would be
    #     created which would edit the localconfig. When we went to del
    #     the first DB, it would use the db value from the shared localconfig
    config = copy.deepcopy(oldconfig)
    config['db'] = database_name
    config['use_tmp_db'] = True

    return config


class TestDatabaeQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        # Replicate the ['General'] assignment that occurs in automation.py
        db_config['General'] = localconfig['General']
        db_config['General']['ff-version'] = 88

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

        try:
            self.assertEqual(None, self.db.get_job(library, version))

            with mock.patch.dict(os.environ, {'TASK_ID': 'abc123'}):
                self.db.create_job(JOBTYPE.VENDORING, library, version,
                                   JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING, bugid)

            newJob = self.db.get_job(library, version)
            self.assertNotEqual(None, newJob)
            self.assertEqual(newJob.type, JOBTYPE.VENDORING)
            self.assertEqual(newJob.library_shortname, library.name)
            self.assertEqual(newJob.version, version)
            self.assertEqual(newJob.status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS)
            self.assertEqual(newJob.outcome, JOBOUTCOME.PENDING)
            self.assertEqual(newJob.bugzilla_id, bugid)
            self.assertEqual(newJob.task_id, 'abc123')
        finally:
            self.db.delete_job(job_id=newJob.id)

    def testJobWithoutTaskId(self):
        # Outside of Taskcluster there's no task to record
        library = Struct(**{
            'name': 'test_library_local',
            'yaml_path': 'path/to/moz.yaml',
        })
        version = "test_local_version"
        with mock.patch.dict(os.environ):
            os.environ.pop('TASK_ID', None)
            self.db.create_job(JOBTYPE.VENDORING, library, version,
                               JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING, 50)
        job = self.db.get_job(library, version)
        try:
            self.assertIsNone(job.task_id)
        finally:
            self.db.delete_job(job_id=job.id)

    def testUpgradeAddsTaskId(self):
        # Put the database back to version 16, before jobs had a task_id
        mysql = self.db.db
        mysql._query_execute("ALTER TABLE jobs DROP COLUMN task_id")
        mysql._query_execute("UPDATE config SET v=16 WHERE k = 'database_version'")

        self.assertEqual(self.db.check_database(), 17)
        columns = [r['COLUMN_NAME'] for r in mysql._query_get_rows(
            "SELECT COLUMN_NAME FROM information_schema.columns WHERE table_schema = %s AND table_name = 'jobs'",
            (mysql.database_config['db'],))]
        self.assertIn('task_id', columns)


class TestDatabaseConnection(unittest.TestCase):
    def testRetriesWhileTheServerIsNotUpYet(self):
        # Like cloud_sql_proxy not listening yet: the first attempts are refused.
        real_connect = pymysql.connect
        calls = []

        def connect(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise pymysql.err.OperationalError(2003, "Can't connect to MySQL server on '127.0.0.1' ([Errno 111] Connection refused)")
            return real_connect(*args, **kwargs)

        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        with mock.patch("components.db.pymysql.connect", side_effect=connect), mock.patch("components.utilities.time.sleep"):
            db = DatabaseProvider(db_config)
        db.update_config(SimpleLoggerConfig)
        self.assertEqual(len(calls), 3)
        db.check_database()
        self.assertTrue(db.updatebot_is_enabled())
        del db


if __name__ == '__main__':
    unittest.main(verbosity=0)
