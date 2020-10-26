#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest


class Interface:
    def update(self, func):
        self._log_impl = func
        self._log_category = self.__class__.mro()[0].__name__

    def log(self, *args):
        self._log_impl(*args, category=self._log_category)


class Base(Interface):
    def __init__(self):
        pass


def log(*args, category=None):
    if args[0] == "No Category":
        assert category is None
    else:
        assert category is not None

    # if category:
    #    print("Category:", category)
    # print(*args)


class TestCommandRunner(unittest.TestCase):
    def testFunctionWrapping(self):
        x = Base()
        x.update(log)
        x.log("Hello", "World")
        log("No Category")


if __name__ == "__main__":
    unittest.main()
