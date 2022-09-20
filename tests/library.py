#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest
import os

sys.path.append(".")
sys.path.append("..")

from components.libraryprovider import LibraryProvider, Library
from tests.mock_commandprovider import TestCommandProvider
from components.logging import SimpleLoggerConfig

LIBRARIES = [
    Library({
        "name": "cubeb-query",
        "revision": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1",
        "repo_url": "https://github.com/mozilla/cubeb",
        "has_patches": False,

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: cubeb",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "fuzzy_query": "media",
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libcubeb-query/moz.yaml".replace("/", os.path.sep)
    }),
    Library({
        "name": "cubeb-path",
        "revision": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1",
        "repo_url": "https://github.com/mozilla/cubeb",
        "has_patches": False,

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: cubeb",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "fuzzy_paths": ["media/"],
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True,
                        'blocking': '1234'
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libcubeb-path/moz.yaml".replace("/", os.path.sep)
    }),
    Library({
        "name": "dav1d",
        "revision": "0243c3ffb644e61848b82f24f5e4a7324669d76e",
        "repo_url": "https://code.videolan.org/videolan/dav1d.git",
        "has_patches": False,

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: Playback",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True,
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libdav1d/moz.yaml".replace("/", os.path.sep)
    }),
    Library({
        'name': 'libpng',
        'revision': 'v1.6.37',
        'repo_url': 'https://github.com/glennrp/libpng',
        "has_patches": True,

        'bugzilla_product': 'Core',
        'bugzilla_component': 'ImageLib',
        'maintainer_bz': 'aosmond@mozilla.com',
        'maintainer_phab': 'aosmond',
        'tasks': [
            LibraryProvider.validate_task({
                'type': 'vendoring',
                'enabled': True,
            }, "n/a")
        ],
        'yaml_path': '.github/gecko-test/libpng/moz.yaml'
    })
]

LIBRARY_FIND_OUTPUT = "\n".join([f.replace("/", os.path.sep) for f in [
    "{0}/.github/gecko-test/libcubeb-query/moz.yaml",
    "{0}/.github/gecko-test/libcubeb-path/moz.yaml",
    "{0}/.github/gecko-test/libaom/moz.yaml",
    "{0}/.github/gecko-test/libdav1d/moz.yaml",
    "{0}/.github/gecko-test/libnope/moz.yaml",
    "{0}/.github/gecko-test/libpng/moz.yaml"
]]).format(os.getcwd())


class TestLibraryProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We will need a CommandProvider, so instatiate that directly
        cls.commandProvider = TestCommandProvider({
            'test_mappings': {
                "find": lambda x: LIBRARY_FIND_OUTPUT,
                "dir": lambda x: LIBRARY_FIND_OUTPUT
            }
        })
        # And provide it with a logger
        cls.commandProvider.update_config(SimpleLoggerConfig)
        # Now instatiate a LibraryProvider (it doesn't need any config)
        cls.libraryprovider = LibraryProvider({})
        # Provide it with a logger and an instatiation of the CommandProvider
        additional_config = SimpleLoggerConfig
        additional_config.update({
            'CommandProvider': cls.commandProvider
        })
        cls.libraryprovider.update_config(additional_config)

    def testLibraryFindAndImport(self):
        libs = self.libraryprovider.get_libraries(os.getcwd())
        self.assertEqual(libs, LIBRARIES)

    def testLibraryExceptions(self):
        test_vectors = [
            ("Blank", ""),
            ("No name",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No product",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No revision",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-phab: bar
  maintainer-bz: bar
  tasks:
    - type: commit-alert
"""),
            ("No repo url",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
updatebot:
  maintainer-phab: bar
  maintainer-bz: bar
  tasks:
    - type: commit-alert
"""),
            ("No component",
             """
schema: 1
bugzilla:
  product: Core
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No maintainer bz",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-phab: bar
  tasks:
    - type: vendoring
    - type: commit-alert
"""),
            ("No maintainer phab",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  tasks:
    - type: vendoring
    - type: commit-alert
"""),
            ("Bad platform",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: foo
  tasks:
    - type: vendoring
      platform: mac
    - type: commit-alert
"""),
            ("Bad vendoring task",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
    - type: vendoring
      filter: none
    - type: commit-alert
"""),
            ("Invalid task type",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
    - type: vendoring
    - type: bob
"""),
        ]
        for vector in test_vectors:
            try:
                self.libraryprovider.validate_library(vector[1], "fake/path")
            except Exception:
                continue
            self.assertFalse(vector, "The test vector '%s' did not raise an expected exception." % vector[0])


if __name__ == "__main__":
    unittest.main(verbosity=0)
