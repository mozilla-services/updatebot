#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
from components.logging import LoggingProvider, SimpleLogger, LogLevel, SimpleLoggerConfig
from components.commandprovider import CommandProvider
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS
from components.mach_vendor import VendorProvider
from components.bugzilla import BugzillaProvider
from components.hg import MercurialProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

DEFAULT_OBJECTS = {
    'Command': CommandProvider,
    'Logging': LoggingProvider,
    'Database': DatabaseProvider,
    'Vendor': VendorProvider,
    'Bugzilla': BugzillaProvider,
    'Mercurial': MercurialProvider,
    'Taskcluster': TaskclusterProvider,
    'Phabricator': PhabricatorProvider,
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
            result.update({'General': config_dictionary['General']})
            return result

        def getOr(name):
            return _getObjOr(name)(_getConfigOr(name))

        # Pre-initialize this with a print-based logger for validation error output.
        self.logger = SimpleLogger()
        self.config_dictionary = config_dictionary
        self._validate(config_dictionary)

        """
        Provider initialization is complicated.

        Any provider may inherit from one or more INeeds interfaces. These interfaces
        provide access to other providers (called 'utility providers'.)

        If a utility provider never needed access to any other utility provider, it would
        be simple - but a utility provider may need access to other utility providers.
        And if the graph of utility provider dependencies had no cycles, it would also be
        simple. But we want to support that. So we do a phased initialization.

        Step 1: Instantiate the utility providers, passing them their configuration data
        Step 2: Create an additional_config that contains all the information any utility
                provider may need
        Step 3: Call update_config on all utility providers. For utility providers that
                subclass an INeeds class, this will populate their needed information.

        At this point we have set up all the utility providers and populated any cyclic
        dependencies.

        Step 4: Set up the logger, so we can capture exceptions
        Step 5: Instantiate the other providers (we call them functionality providers.)
                These providers should never depend on each other.
        Step 6: Call update_config on them as well to populate their INeeds superclasses.

        We store all providers in a provider_dictionary so its easy to iterate over them,
        but we also turn them into member variables for easier access (Step 7)
        """
        # Step 1
        self.provider_dictionary = {
            'cmdProvider': getOr('Command'),
            'loggingProvider': getOr('Logging')
        }
        # Step 2
        additional_config = {
            'LoggingProvider': self.provider_dictionary['loggingProvider'],
            'CommandProvider': self.provider_dictionary['cmdProvider']
        }
        # Step 3
        self.runOnProviders(lambda x: x.update_config(additional_config))

        # Step 4
        self.logger = self.provider_dictionary['loggingProvider']

        try:
            # Step 5
            self.provider_dictionary.update({
                'dbProvider': getOr('Database'),
                'vendorProvider': getOr('Vendor'),
                'bugzillaProvider': getOr('Bugzilla'),
                'mercurialProvider': getOr('Mercurial'),
                'taskclusterProvider': getOr('Taskcluster'),
                'phabricatorProvider': getOr('Phabricator'),
            })
            # Step 6
            self.runOnProviders(lambda x: x.update_config(additional_config))
            # Step 7
            self.__dict__.update(self.provider_dictionary)
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)

    def runOnProviders(self, func):
        for v in self.provider_dictionary.values():
            func(v)

    def _validate(self, config_dictionary):
        if 'General' not in config_dictionary:
            self.logger.log("'General' is a required config dictionary to supply.", level=LogLevel.Fatal)
            sys.exit(1)
        if 'gecko-path' not in config_dictionary['General']:
            self.logger.log("['General']['gecko-path'] probably should be defined in the config dictionary.", level=LogLevel.Warning)
        if 'env' not in config_dictionary['General']:
            self.logger.log("['General']['env'] must be defined in the config dictionary with a value of prod or dev.", level=LogLevel.Fatal)
            sys.exit(1)

    def run(self):
        try:
            if 'gecko-path' in self.config_dictionary['General']:
                os.chdir(self.config_dictionary['General']['gecko-path'])

            self.dbProvider.check_database()
            libraries = self.dbProvider.get_libraries()
            for l in libraries:
                try:
                    self._process_library(l)
                except Exception as e:
                    self.logger.log("Caught an exception while processing a library.", level=LogLevel.Error)
                    self.logger.log_exception(e)
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)

    def _process_library(self, library):
        new_version = self.vendorProvider.check_for_update(library)
        if not new_version:
            return

        existing_job = self.dbProvider.get_job(library, new_version)
        if existing_job:
            self._process_existing_job(existing_job)
        else:
            self._process_new_job(library, new_version)

    def _process_new_job(self, library, new_version):
        bug_id = self.bugzillaProvider.file_bug(library, new_version)

        status = None
        try:
            self.vendorProvider.vendor(library)
            status = JOBSTATUS.VENDORED
        except Exception:
            # Handle `./mach vendor` failing
            status = JOBSTATUS.COULD_NOT_VENDOR
            self.dbProvider.save_job(library, new_version, status, bug_id, phab_revision=None)
            self.bugzillaProvider.comment_on_bug(bug_id, status)
            return

        self.mercurialProvider.commit(library, bug_id, new_version)
        try_run = self.taskclusterProvider.submit_to_try(library)

        status = JOBSTATUS.AWAITING_TRY_RESULTS
        self.bugzillaProvider.comment_on_bug(bug_id, status, try_run)
        phab_revision = self.phabricatorProvider.submit_patch()
        self.dbProvider.save_job(library, new_version, status, bug_id, phab_revision, try_run)

    def _process_existing_job(self, existing_job):
        pass


if __name__ == "__main__":
    import argparse
    try:
        from localconfig import localconfig
    except ImportError as e:
        print("Execution requires a local configuration to be defined.")
        print(e)
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
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.print()
    elif args.delete_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.delete_database()
    elif args.check_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config(SimpleLoggerConfig)
        db.check_database()
    else:
        u = Updatebot(localconfig)
        u.run()
