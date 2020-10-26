#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from apis.phabricator import PhabricatorProvider
from components.commandprovider import CommandProvider
from components.logging import SimpleLoggerConfig


class TestCommandRunner(unittest.TestCase):
    def testCommand(self):
        runner = CommandProvider({})

        phab = PhabricatorProvider({})
        additional_config = SimpleLoggerConfig
        additional_config.update({"CommandProvider": runner})

        phab.update_config(additional_config)
        runner.update_config(additional_config)

        phab.set_reviewer("D3643", "jewilde")
        phab.abandon("D3646")


if __name__ == "__main__":
    unittest.main()
