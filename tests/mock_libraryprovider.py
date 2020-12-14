#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

from components.utilities import Struct
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class MockLibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def get_libraries(self, gecko_path):
        return [Struct(**{
            "bugzilla": {"product": "Core", "component": "Audio/Video: Playback"},
            "origin": {
                "name": "dav1d",
            },
            "updatebot": {
                "enabled": True,
                "maintainer-phab": "nobody",
                "maintainer-bz": "nobody@mozilla.com"
            },
            "yaml_path": "mozilla-central/source/media/libdav1d/moz.yaml"
        })]

    def validate_library(self, library):
        pass
