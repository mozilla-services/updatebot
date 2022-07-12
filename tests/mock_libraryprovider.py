#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider
from components.libraryprovider import LibraryProvider, Library

from tests.mock_repository import test_repo_path_wrapper, default_test_repo


class MockLibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self.config = config

    def get_libraries(self, gecko_path):
        return [
            Library({
                "name": "dav1d",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "vendoring",
                        "enabled": True
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libdav1d/moz.yaml"
            }),
            Library({
                "name": "cubeb-query",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: cubeb",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "fuzzy_query": "media",
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "vendoring",
                        "enabled": True
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/cubeb-query/moz.yaml"
            }),
            Library({
                "name": "cubeb-path",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: cubeb",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "fuzzy_paths": ["media/"],
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "vendoring",
                        "enabled": True,
                        "blocking": 1234
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/cubeb-path/moz.yaml"
            }),
            Library({
                "name": "cube-2commits",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: cubeb",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "fuzzy_query": "media",
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "vendoring",
                        "enabled": True,
                        'frequency': '2 commits'
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/cubeb/moz.yaml"
            }),
            Library({
                "name": "aom",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('commitalert_revision_override', lambda: None)(),
                "repo_url": test_repo_path_wrapper((self.config.get('commitalert_repo_override', None) or default_test_repo)()),
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "commit-alert",
                        "enabled": True,
                        "branch": self.config.get('commitalert_branch_override', None)
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libaom/moz.yaml"
            }),
            Library({
                "name": "aom",
                "bugzilla_product": "Core",
                "bugzilla_component": "Audio/Video: Playback",
                "maintainer_phab": "nobody",
                "maintainer_bz": "nobody@mozilla.com",
                "revision": self.config.get('commitalert_revision_override', lambda: None)(),
                "repo_url": test_repo_path_wrapper((self.config.get('commitalert_repo_override', None) or default_test_repo)()),
                "has_patches": False,
                "tasks": [
                    LibraryProvider.validate_task({
                        "type": "commit-alert",
                        "enabled": True,
                        "branch": self.config.get('commitalert_branch_override', None)
                    }, "n/a")
                ],
                "yaml_path": "mozilla-central/source/media/libaom/moz.yaml"
            }),
            Library({
                'name': 'libpng',
                "revision": self.config.get('vendoring_revision_override', None),
                "repo_url": "https://example.invalid",
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
                'yaml_path': 'mozilla-central/source/media/libpng/moz.yaml'
            })]
