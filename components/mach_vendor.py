# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import string_date_to_uniform_string_date
from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class VendorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def check_for_update(self, library):
        result = self.run(["./mach", "vendor", "--check-for-update", library.yaml_path]).stdout.decode().strip()

        # ./mach vendor produces no output when no update is available
        if not result:
            return (None, None)

        if "Creating default state directory" in result:
            # If no ~/.mozbuild directory was present this gets output unfortunately.
            result_lines = result.split("\n")
            result_lines = [l.strip() for l in result_lines if l.strip() and "state directory" not in l]
            result = result_lines[0]

        parts = result.split(" ")
        return (parts[0], string_date_to_uniform_string_date(parts[1]))

    @logEntryExit
    def vendor(self, library):
        self.run(
            ["./mach", "vendor", library.yaml_path, "--ignore-modified"])
