#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest
from datetime import datetime, timedelta

sys.path.append(".")
sys.path.append("..")
from tasktypes.base import BaseTaskRunner
from components.logging import simpleLogger
from components.utilities import Struct
from components.dbmodels import JOBTYPE

from tests.mock_commandprovider import TestCommandProvider
from tests.mock_libraryprovider import MockLibraryProvider


class TestTaskFrequency(unittest.TestCase):
    def testFrequency(self):
        bt = BaseTaskRunner()
        bt.logger = simpleLogger
        bt.jobType = JOBTYPE.VENDORING
        bt.dbProvider = Struct(**{
            "get_all_jobs_for_library": lambda a, b: []})
        bt.scmProvider = Struct(**{
            "check_for_update": lambda a, b, c, d: (['a', 'b'], ['a', 'b'])})

        mlp = MockLibraryProvider({})
        tcp = TestCommandProvider({})

        config = {
            'CommandProvider': tcp,
            'LoggingProvider': simpleLogger
        }
        mlp.update_config(config)

        libraries = mlp.get_libraries("")

        library = libraries[0]
        task = libraries[0].tasks[0]

        self.assertTrue(bt._should_process_new_job(library, task))

        task.frequency = 'release'
        self.assertTrue(bt._should_process_new_job(library, task))

        bt.config = {'General': {'ff-version': 79}}
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"ff_versions": set([80]), "version": "whatever"})]
        self.assertTrue(bt._should_process_new_job(library, task))

        bt.config = {'General': {'ff-version': 79}}
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"ff_versions": set([79]), "version": "whatever"})]
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '1 week'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=1, hours=1)})]
        self.assertTrue(bt._should_process_new_job(library, task))

        task.frequency = '2 weeks'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=2, hours=1)})]
        self.assertTrue(bt._should_process_new_job(library, task))

        task.frequency = '1 week'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(days=5)})]
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '21 weeks'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=20)})]
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '1 week, 3 commits'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: []
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '1 week, 3 commits'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=1, hours=1)})]
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '2 weeks, 2 commits'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=1, hours=1)})]
        self.assertFalse(bt._should_process_new_job(library, task))

        task.frequency = '1 week, 2 commits'
        bt.dbProvider.get_all_jobs_for_library = lambda a, b: [Struct(**{"created": datetime.now() - timedelta(weeks=1, hours=1)})]
        self.assertTrue(bt._should_process_new_job(library, task))


if __name__ == '__main__':
    unittest.main(verbosity=0)
