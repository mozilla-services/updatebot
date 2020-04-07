#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.dbc import Database
from components.dbmodels import JOBSTATUS
from components.mach_vendor import DefaultVendorProvider
from components.bugzilla import file_bug, comment_on_bug
from components.hg import commit
from apis.taskcluster import submit_to_try
from apis.phabricator import submit_patch


class Updatebot:
    def __init__(self, database_config, object_dictionary):
        def getOr(name, obj):
            return object_dictionary[name] if name in object_dictionary else obj

        self.db = Database(database_config)
        self.vendorProvider = getOr('VendorProvider', DefaultVendorProvider())

    def run(self):
        self.db.check_database()
        libraries = self.db.get_libraries()
        for l in libraries:
            try:
                self.process_library(l)
            except Exception as e:
                print(e)
                # For now, re-raise the exception so the job fails and can be re-triggered.
                # In the future we will log the exception and continue to the next library.
                raise e
                pass
                # Output some information here....


    def process_library(self, library):
        new_version = self.vendorProvider.check_for_update(library)
        if not new_version:
            return

        existing_job = self.db.get_job(library, new_version)
        if existing_job:
            self.process_existing_job(existing_job)
        else:
            self.process_new_job(library, new_version)

    def process_new_job(self, library, new_version):
        bug_id = file_bug(library, new_version)

        status = None
        try:
            self.vendorProvider.vendor(library)
            status = JOBSTATUS.VENDORED
        except:
            # Handle `./mach vendor` failing
            status = JOBSTATUS.COULD_NOT_VENDOR
            self.db.save_job(library, new_version, status, bug_id)
            comment_on_bug(bug_id, status)
            return

        commit(library, bug_id, new_version)
        try_run = submit_to_try(library)

        status = JOBSTATUS.SUBMITTED_TRY
        comment_on_bug(bug_id, status, try_run)
        submit_patch()
        self.db.save_job(library, new_version, status, bug_id, try_run)

    def process_existing_job(self, existing_job):
        pass


def run(database_config=None):
    u = Updatebot(database_config)
    u.run()


if __name__ == "__main__":
    import sys
    import argparse
    try:
        from localconfig import database_config
    except ImportError:
        print("Unit tests require a local database configuration to be defined.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--check-database', help="Check the config level of the database", action="store_true")
    parser.add_argument('--print-database',
                        help="Print the database", action="store_true")
    parser.add_argument('--delete-database',
                        help="Delete the database", action="store_true")
    args = parser.parse_args()

    if args.print_database:
        db = Database(database_config)
        db.print()
    elif args.delete_database:
        db = Database(database_config)
        db.delete_database()
    elif args.check_database:
        db = Database(database_config)
        db.check_database()
    else:
        run(database_config)
