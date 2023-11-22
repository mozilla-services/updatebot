#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
import sys
from components.logging import LoggingProvider, SimpleLogger, LogLevel
from components.commandprovider import CommandProvider
from components.dbc import DatabaseProvider
from components.libraryprovider import LibraryProvider
from components.mach_vendor import VendorProvider
from components.bugzilla import BugzillaProvider
from components.scmprovider import SCMProvider
from components.hg import MercurialProvider, reset_repository
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider
from tasktypes.vendoring import VendorTaskRunner
from tasktypes.commitalert import CommitAlertTaskRunner

DEFAULT_OBJECTS = {
    'Command': CommandProvider,
    'Logging': LoggingProvider,
    'Database': DatabaseProvider,
    'Vendor': VendorProvider,
    'Bugzilla': BugzillaProvider,
    'Library': LibraryProvider,
    'Mercurial': MercurialProvider,
    'Taskcluster': TaskclusterProvider,
    'Phabricator': PhabricatorProvider,
    'SCM': SCMProvider,
    'VendorTaskRunner': VendorTaskRunner,
    'CommitAlertTaskRunner': CommitAlertTaskRunner
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
        self.config_dictionary = self._validate(self.config_dictionary)

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
        but we also turn them into member variables for easier access (Step 7).

        Besides Providers, we also have TaskRunners. TaskRunners use Providers to run a
        job. TaskRunners do not talk to other TaskRunners; and an instance of a TaskRunner
        is capable of running multiple different jobs (of a single type.)

        Because we want to support the same mocking ability for TaskRunners as Providers,
        we support specifying TaskRunners in the object_dictionary (Step 8); however, they
        do not receive any configuration - there should be no state like that in a
        TaskRunner.
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
                'libraryProvider': getOr('Library'),
                'mercurialProvider': getOr('Mercurial'),
                'taskclusterProvider': getOr('Taskcluster'),
                'phabricatorProvider': getOr('Phabricator'),
                'scmProvider': getOr('SCM'),
            })
            # Step 6
            self.runOnProviders(lambda x: x.update_config(additional_config))
            # Step 7
            self.__dict__.update(self.provider_dictionary)
            # And check the database
            self.dbProvider.check_database()

            # Step 8
            self.taskRunners = {
                'vendoring': _getObjOr('VendorTaskRunner')(self.provider_dictionary, self.config_dictionary),
                'commit-alert': _getObjOr('CommitAlertTaskRunner')(self.provider_dictionary, self.config_dictionary)
            }
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)

    def runOnProviders(self, func):
        for v in self.provider_dictionary.values():
            func(v)

    def _validate(self, config_dictionary):
        # In this function we have not set up our robust logging facilities yet. We are using SimpleLogger()
        # which is just a Localogger. So even if we are running in automation, we won't be outputting anything
        # here to Sentry. Therefore, if we do need to abort here; we should exit(1) so Taskcluster will report
        # the job as failed (and we'll get an email.)
        if 'General' not in config_dictionary:
            self.logger.log("'General' is a required config dictionary to supply.", level=LogLevel.Fatal)
            sys.exit(1)

        if 'gecko-path' not in config_dictionary['General']:
            self.logger.log("['General']['gecko-path'] probably should be defined in the config dictionary.", level=LogLevel.Warning)
            if 'ff_version' not in config_dictionary['General']:
                self.logger.log("If ['General']['gecko-path'] is not defined, then ff_version must be - but it is not.", level=LogLevel.Fatal)
                sys.exit(1)

        if 'env' not in config_dictionary['General']:
            self.logger.log("['General']['env'] must be defined in the config dictionary with a value of prod or dev.", level=LogLevel.Fatal)
            sys.exit(1)

        if 'ff-version' not in config_dictionary['General'] or not config_dictionary['General']['ff-version']:
            ff_version = 0
            try:
                with open(os.path.join(config_dictionary['General']['gecko-path'], "browser", "config", "version.txt")) as version_file:
                    version = version_file.read()
                    ff_version = int(version.split(".")[0])
            except Exception as e:
                self.logger.log("Encountered an error trying to read the version from version.txt", level=LogLevel.Fatal)
                raise e

            if ff_version < 87:
                # 87 is the version of Firefox currently on Beta when this code was written. If we get a number lower than that
                # (e.g. 0), then something is wrong and bears investigating.
                self.logger.log("The FF version we pulled from the repo is < 87: %s" % ff_version, level=LogLevel.Fatal)
                sys.exit(1)
            config_dictionary['General']['ff-version'] = ff_version

        if 'GECKO_HEAD_REPOSITORY' not in os.environ and 'repo' not in config_dictionary['General']:
            self.logger.log("I cannot tell what repository I'm running from. Add 'repo' to the config dictionary or ensure GECKO_HEAD_REPOSITORY is in the environment.", level=LogLevel.Fatal)
            sys.exit(1)
        elif 'GECKO_HEAD_REPOSITORY' in os.environ:
            config_dictionary['General']['repo'] = os.environ['GECKO_HEAD_REPOSITORY']

        if re.match(r"https://hg.mozilla.org/projects/(\w+)", config_dictionary['General']['repo']):
            config_dictionary['General']['repo'] = config_dictionary['General']['repo'].replace("https://hg.mozilla.org/projects/", "")
        elif re.match(r"https://hg.mozilla.org/mozilla-(\w+)", config_dictionary['General']['repo']):
            config_dictionary['General']['repo'] = config_dictionary['General']['repo'].replace("https://hg.mozilla.org/", "")
        else:
            self.logger.log("The repository specified in the config dictionary was not of the form https://hg.mozilla.org/mozilla-foo.", level=LogLevel.Fatal)
            sys.exit(1)

        return config_dictionary

    def run(self, library_filter=""):
        try:
            updatebot_version = self.cmdProvider.run(["git", "log", "-1", "--oneline"], shell=False, clean_return=True).stdout.decode().strip()
            python_version = sys.version.replace("\n", " ")
            self.logger.log("Running Updatebot version: {0} on Python {1}".format(updatebot_version, python_version), level=LogLevel.Info)
            self.logger.log("Python prefix: {0}".format(sys.prefix), level=LogLevel.Debug)
            self.logger.log("Python modules loaded from {0}".format(", ".join(sys.path)), level=LogLevel.Debug)

            if not self.dbProvider.updatebot_is_enabled():
                self.logger.log_exception(Exception("Updatebot is disabled per the config database, not doing anything and ending execution."))
                return

            if 'gecko-path' in self.config_dictionary['General']:
                self.logger.log("Changing to gecko directory '%s'" % (self.config_dictionary['General']['gecko-path']), level=LogLevel.Info)
                os.chdir(self.config_dictionary['General']['gecko-path'])
            else:
                self.logger.log("Staying in current directory '%s'" % (os.getcwd()), level=LogLevel.Info)

            if 'separate-platforms' not in self.config_dictionary['General']:
                self.config_dictionary['General']['separate-platforms'] = False

            libraries = self.libraryProvider.get_libraries(self.config_dictionary['General']['gecko-path'])
            for lib in libraries:
                if library_filter and library_filter not in lib.name:
                    self.logger.log("Skipping %s because it doesn't meet the filter '%s'" % (lib.name, library_filter), level=LogLevel.Info)
                    continue

                for task in lib.tasks:
                    try:
                        taskRunner = self.taskRunners[task.type]

                        self.runOnProviders(lambda x: x.initialize())
                        taskRunner.process_task(lib, task)
                        self.runOnProviders(lambda x: x.reset())
                    except Exception as e:
                        # Clean up any changes to the repo we may have made
                        reset_repository(self.cmdProvider)
                        self.logger.log("Caught an exception while processing library %s task type %s" % (lib.name, task.type), level=LogLevel.Error)
                        self.logger.log_exception(e)
        except Exception as e:
            self.logger.log_exception(e)
            raise(e)


# ====================================================================
# ====================================================================

if __name__ == "__main__":
    import argparse
    try:
        from localconfig import localconfig
    except ImportError as e:
        print("Execution requires a local configuration to be defined.")
        print(e)
        sys.exit(1)

    parser = argparse.ArgumentParser()

    parser.add_argument('--library-filter',
                        help="Pass a filter when running Updatebot fully",
                        default="")

    parser.add_argument('--find-libraries',
                        help="Print libraries available in gecko-path", action="store_true")

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
        db.update_config({
            'LoggingProvider': SimpleLogger({'local': True, 'level': 5})
        })
        try:
            db.print()
        except Exception as e:
            print("Error printing database:")
            print(e)
    elif args.delete_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config({
            'LoggingProvider': SimpleLogger({'local': True, 'level': 5})
        })
        try:
            db.delete_database()
        except Exception as e:
            print("Error deleting database:")
            print(e)
    elif args.check_database:
        db = DatabaseProvider(localconfig['Database'])
        db.update_config({
            'LoggingProvider': SimpleLogger({'local': True, 'level': 5})
        })
        try:
            db.check_database()
        except Exception as e:
            print("Error checking database:")
            print(e)
    elif args.find_libraries:
        # We will need a CommandProvider, so instatiate that directly
        commandProvider = CommandProvider({})
        # And provide it with a logger that won't log
        commandProvider.update_config({
            'LoggingProvider': SimpleLogger({'local': False})
        })
        # Now instatiate a LibraryProvider (it doesn't need any config)
        libraryprovider = LibraryProvider({})
        additional_config = {
            'LoggingProvider': SimpleLogger({'local': False}),
            'CommandProvider': commandProvider
        }
        libraryprovider.update_config(additional_config)
        libs = libraryprovider.get_libraries(localconfig['General']['gecko-path'])
        for lib in libs:
            print(lib.pretty_str())
            for t in lib.tasks:
                print("\t", t)
    else:
        u = Updatebot(localconfig)
        u.run(library_filter=args.library_filter)
