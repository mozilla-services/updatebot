# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class VendorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def check_for_update(self, library):
        return self.run(["./mach", "vendor", "--check-for-update", library.yaml_path]).stdout.decode().strip()

    @logEntryExit
    def vendor(self, library):
        self.run(
            ["./mach", "vendor", library.yaml_path, "--ignore-modified"])
