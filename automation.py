#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.dbc import DefaultDatabaseProvider
from components.dbmodels import JOBSTATUS
from components.mach_vendor import DefaultVendorProvider
from components.bugzilla import DefaultBugzillaProvider
from components.hg import DefaultMercurialProvider
from apis.taskcluster import DefaultTaskclusterProvider
from apis.phabricator import DefaultPhabricatorProvider


class Updatebot:
    def __init__(self, database_config, object_dictionary={}):
        def getOr(name, ctor, config_arg=None):
            return object_dictionary[name](config_arg) if name in object_dictionary else ctor(config_arg)

        self.dbProvider = getOr('DatabaseProvider', DefaultDatabaseProvider, database_config)
        self.vendorProvider = getOr('VendorProvider', DefaultVendorProvider)
        self.bugzillaProvider = getOr('BugzillaProvider', DefaultBugzillaProvider)
        self.mercurialProvider = getOr('MercurialProvider', DefaultMercurialProvider)
        self.taskclusterProvider = getOr('TaskclusterProvider', DefaultTaskclusterProvider)
        self.phabricatorProvider = getOr('PhabricatorProvider', DefaultPhabricatorProvider)

    def run(self):
        self.dbProvider.check_database()
        libraries = self.dbProvider.get_libraries()
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

        existing_job = self.dbProvider.get_job(library, new_version)
        if existing_job:
            self.process_existing_job(existing_job)
        else:
            self.process_new_job(library, new_version)

    def process_new_job(self, library, new_version):
        bug_id = self.bugzillaProvider.file_bug(library, new_version)

        status = None
        try:
            self.vendorProvider.vendor(library)
            status = JOBSTATUS.VENDORED
        except:
            # Handle `./mach vendor` failing
            status = JOBSTATUS.COULD_NOT_VENDOR
            self.dbProvider.save_job(library, new_version, status, bug_id)
            self.bugzillaProvider.comment_on_bug(bug_id, status)
            return

        self.mercurialProvider.commit(library, bug_id, new_version)
        try_run = self.taskclusterProvider.submit_to_try(library)

        status = JOBSTATUS.SUBMITTED_TRY
        self.bugzillaProvider.comment_on_bug(bug_id, status, try_run)
        self.phabricatorProvider.submit_patch()
        self.dbProvider.save_job(library, new_version, status, bug_id, try_run)

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
        db = DefaultDatabaseProvider(database_config)
        db.print()
    elif args.delete_database:
        db = DefaultDatabaseProvider(database_config)
        db.delete_database()
    elif args.check_database:
        db = DefaultDatabaseProvider(database_config)
        db.check_database()
    else:
        run(database_config)
