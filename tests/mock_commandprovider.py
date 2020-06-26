#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")

from components.utilities import Struct, BaseProvider


class TestCommandProvider(BaseProvider):
    def __init__(self, config, mappings={}):
        if 'test_mappings' in config:
            self.mappings = config['test_mappings']

    def run(self, args, shell=False, clean_return=True):
        argument_string = " ".join(args)
        print("Mocked Command executed", argument_string)

        stdout = ""
        for m in self.mappings:
            if argument_string.startswith(m):
                stdout = self.mappings[m]
                break
        return Struct(**{'stdout':
                         Struct(**{'decode': lambda: stdout})})
