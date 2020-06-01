#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
from components.utilities import DefaultCommandProvider
from components.dbc import DefaultDatabaseProvider
from components.dbmodels import JOBSTATUS
from components.mach_vendor import DefaultVendorProvider
from components.bugzilla import DefaultBugzillaProvider
from components.hg import DefaultMercurialProvider
from apis.taskcluster import DefaultTaskclusterProvider
from apis.phabricator import DefaultPhabricatorProvider

DEFAULT_OBJECTS = {
    'Command': DefaultCommandProvider,
    'Database': DefaultDatabaseProvider,
    'Vendor': DefaultVendorProvider,
    'Bugzilla': DefaultBugzillaProvider,
    'Mercurial': DefaultMercurialProvider,
    'Taskcluster': DefaultTaskclusterProvider,
    'Phabricator': DefaultPhabricatorProvider,
}


class Updatebot:
    def __init__(self, config_dictionary={}, object_dictionary={}):
        def _getOrImpl(dictionary, name, default):
            return dictionary[name] if name in dictionary else default

        def _getObjOr(name):
            assert(name in DEFAULT_OBJECTS)
            return _getOrImpl(object_dictionary, name, DEFAULT_OBJECTS[name])

        def _getConfigOr(name):
            result = _getOrImpl(config_dictionary, name, {})
            if name != 'Command':
                result.update({'CommandProvider': self.cmdProvider})
            result.update({'General': config_dictionary['General']})
            return result

        def getOr(name):
            return _getObjOr(name)(_getConfigOr(name))

        self.validate(config_dictionary)
        self.cmdProvider = getOr('Command')
        self.dbProvider = getOr('Database')
        self.vendorProvider = getOr('Vendor')
        self.bugzillaProvider = getOr('Bugzilla')
        self.mercurialProvider = getOr('Mercurial')
        self.taskclusterProvider = getOr('Taskcluster')
        self.phabricatorProvider = getOr('Phabricator')

    def validate(self, config_dictionary):
        if 'General' not in config_dictionary:
            print("'General' is a required config dictionary to supply.")
            sys.exit(1)
        if 'env' not in config_dictionary['General']:
            print("['General']['env'] must be defined in the config dictionary with a value of prod or dev.")
            sys.exit(1)

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
        except Exception:
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


def run(configs):
    u = Updatebot(configs)
    u.run()


if __name__ == "__main__":
    import sys
    import argparse
    try:
        from localconfig import localconfigs
    except ImportError:
        print("Unit tests require a local configuration to be defined.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('--check-database',
                        help="Check the config level of the database",
                        action="store_true")
    parser.add_argument('--print-database',
                        help="Print the database", action="store_true")
    parser.add_argument('--delete-database',
                        help="Delete the database", action="store_true")
    args = parser.parse_args()

    if args.print_database:
        db = DefaultDatabaseProvider(localconfigs['Database'])
        db.print()
    elif args.delete_database:
        db = DefaultDatabaseProvider(localconfigs['Database'])
        db.delete_database()
    elif args.check_database:
        db = DefaultDatabaseProvider(localconfigs['Database'])
        db.check_database()
    else:
        run(localconfigs)
