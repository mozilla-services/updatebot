#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

"""
For this file, we have test-repo.bundle which contains the below commits.

We also have bundles that culminate in each of the revisions, for use when
the library 'updates upstream'.

* 870617305a0d3441eab0828965d138be7c99d1bc - Change our message  (HEAD -> anotherbranch)
| * 504e1236e462f8f6c265d61d1fcb9d8f6f943eac - Add functionality  (somebranch)
| * d7e508c874ce09bd18604bbf811e0f695ee9d143 - Skeleton for some functionality
|/
* ed0a50224caf390bb56a6e14fdeb8f21c6655c22 - Maybe just remove this function completely  (master)
* 916683659e77a0f7c9b0cefece3da481737c4026 - Update readme for CVE-2021-1  (tag: v0.0.3)
* 882bdfe3a66a3b8146998c5e443e5d63e4a9b7fd - Rename file
* d8075f3fdda87c1d1fa1972051c242ef54cf7395 - Fix a potential bufer overflow  (tag: v0.0.2)
* f3a8ab9f06708869691e4951b5b48ebddb3f7fad - Utility function for printing strings
* 6fc8909aa69765ac2eee8ad235b603718f80f32c - main() should ahve arguments  (tag: v0.0.1)
* 160b522f2860768935f132fb68050cedbc619e38 - Add main.c
* 0bec03444917e0df10a812131843aae7df7e980c - Add README file

"""

# We use this to determine how many commits we expect to find, which lets us validate
# we saw the correct number (in the bugzillaprovider)
COMMITS_BRANCH1 = [
    "504e1236e462f8f6c265d61d1fcb9d8f6f943eac",
    "d7e508c874ce09bd18604bbf811e0f695ee9d143",
    "ed0a50224caf390bb56a6e14fdeb8f21c6655c22",
    "916683659e77a0f7c9b0cefece3da481737c4026",
    "882bdfe3a66a3b8146998c5e443e5d63e4a9b7fd",
    "d8075f3fdda87c1d1fa1972051c242ef54cf7395",
    "f3a8ab9f06708869691e4951b5b48ebddb3f7fad",
    "6fc8909aa69765ac2eee8ad235b603718f80f32c",
    "160b522f2860768935f132fb68050cedbc619e38",
    "0bec03444917e0df10a812131843aae7df7e980c",
]
COMMITS_BRANCH2 = [
    "870617305a0d3441eab0828965d138be7c99d1bc",
    "ed0a50224caf390bb56a6e14fdeb8f21c6655c22",
    "916683659e77a0f7c9b0cefece3da481737c4026",
    "882bdfe3a66a3b8146998c5e443e5d63e4a9b7fd",
    "d8075f3fdda87c1d1fa1972051c242ef54cf7395",
    "f3a8ab9f06708869691e4951b5b48ebddb3f7fad",
    "6fc8909aa69765ac2eee8ad235b603718f80f32c",
    "160b522f2860768935f132fb68050cedbc619e38",
    "0bec03444917e0df10a812131843aae7df7e980c",
]
COMMITS_MAIN = [
    "ed0a50224caf390bb56a6e14fdeb8f21c6655c22",
    "916683659e77a0f7c9b0cefece3da481737c4026",
    "882bdfe3a66a3b8146998c5e443e5d63e4a9b7fd",
    "d8075f3fdda87c1d1fa1972051c242ef54cf7395",
    "f3a8ab9f06708869691e4951b5b48ebddb3f7fad",
    "6fc8909aa69765ac2eee8ad235b603718f80f32c",
    "160b522f2860768935f132fb68050cedbc619e38",
    "0bec03444917e0df10a812131843aae7df7e980c",
]


def test_repo_path_wrapper(p):
    return os.path.join(os.getcwd(), "tests/" if not os.getcwd().endswith("tests") else "", "test-repo", p)


def default_test_repo():
    return "test-repo.bundle"
