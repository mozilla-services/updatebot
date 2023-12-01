#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import argparse

from automation import Updatebot
from components.utilities import Struct



# ====================================================================
# ====================================================================

def die(msg):
    print(msg)
    sys.exit(-1)

if __name__ == "__main__":
    import argparse
    try:
        from localconfig import localconfig
    except ImportError as e:
        print("Execution requires a local configuration to be defined.")
        print(e)
        sys.exit(1)

    parser = argparse.ArgumentParser()

    parser.add_argument('mode', type=str, help='Debug command')
    parser.add_argument('--revision', default="", required=False)

    args = parser.parse_args()

    u = Updatebot(localconfig)

    if args.mode == "try-comments":
        if not args.revision:
            die("--revision is required")

        import tests.library
        fake_library = tests.library.LIBRARIES[0]
        from components.dbmodels import Job
        fake_job = Job()
        fake_job.id = 1
        fake_job.library_shortname = fake_library.shortname
        fake_job.try_runs = [Struct(**{'revision': args.revision})]

        (no_build_failures, results, comment_lines) = u.taskRunners['vendoring']._get_comments_on_push(fake_library, fake_job)

        if not no_build_failures:
            print("Build failures")
        else:
            for l in comment_lines:
                print(l)

    else:
        die("Unknown mode provided")
