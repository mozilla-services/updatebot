#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import yaml

from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider
from components.logging import LogLevel


# Library metadata from moz.yaml files that we care about and example values
# NOTE: yaml_path is provided at import and may change based on the gecko-path
#       given in the localconfig
# NOTE: this format mirrors the moz.yaml schema defined at
#       https://searchfox.org/mozilla-central/source/python/mozbuild/mozbuild/vendor/moz_yaml.py

# 'bugzilla': {
#     'product': 'Core',
#     'component': 'ImageLib'
# },
# 'origin': {
#     'name': 'dav1d'
# },
# 'updatebot': {
#     'maintainer-bz': 'nobody@mozilla.com',
#     'maintainer-phab': 'nobody',
#     'tasks': [
#         { 'type': 'vendoring',
#           ' enabled': True,
#         }
#     ]
# },
# 'yaml_path': '/Users/nobody/mozilla-central/media/libdav1d/moz.yaml'

class Library:
    def __init__(self, dict):
        self.name = dict['name']
        self.type = dict['type']
        self.bugzilla_product = dict['bugzilla_product']
        self.bugzilla_component = dict['bugzilla_component']
        self.revision = dict['revision']
        self.repo_url = dict['repo_url']
        self.maintainer_bz = dict['maintainer_bz']
        self.maintainer_phab = dict['maintainer_phab']
        self.yaml_path = dict['yaml_path']
        self.tasks = []

        for t in dict['tasks']:
            self.tasks.append(Task(t))

    def __eq__(self, other):
        if not isinstance(other, Library):
            return False

        for prop in dir(self):
            if not prop.startswith("__") and prop != "id":
                try:
                    if getattr(other, prop) != getattr(self, prop):
                        return False
                except AttributeError:
                    return False

        return True


class Task:
    def __init__(self, dict):
        self.type = dict['type']
        self.enabled = dict['enabled']
        self.branch = dict['branch']
        self.cc = dict['cc']
        self.needinfo = dict['needinfo']
        self.frequency = dict['frequency']

        if self.type == 'commit-alert':
            self.filter = dict['filter']
            self.source_extensions = dict['source-extensions']

    def __eq__(self, other):
        if not isinstance(other, Task):
            return False

        for prop in dir(self):
            if not prop.startswith("__") and prop != "id":
                try:
                    if getattr(other, prop) != getattr(self, prop):
                        return False
                except AttributeError:
                    return False

        return True


def get_sub_key_or_raise(key, subkey, dict, yaml_path):
    if key in dict and subkey in dict[key]:
        return dict[key][subkey]
    else:
        raise AttributeError('library imported from {0} is missing {1}: {2} field'.format(yaml_path, key, subkey))


def get_key_or_default(key, dict, default):
    return dict[key] if key in dict else default


class LibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._libraries = None

    def get_libraries(self, gecko_path):
        if self._libraries is None:
            self._libraries = []

            # Python packages
            python_updatebot_path = os.path.join(gecko_path, "third_party/python/updatebot.txt")
            if os.path.isfile(python_updatebot_path):
                with open(python_updatebot_path, "r") as python_updatebot:
                    self._libraries = LibraryProvider._validate_python_list(python_updatebot.read(), python_updatebot_path.replace(gecko_path + "/", ""))

                requirements_in_path = os.path.join(gecko_path, "third_party/python/requirements.in")
                with open(requirements_in_path, "r") as current_versions:
                    for line in current_versions:
                        if line and line[0] != "#" and "==" in line:
                            parts = line.split("==")
                            for lib in self._libraries:
                                if lib.name == parts[0]:
                                    lib.revision = parts[1].strip()
            else:
                self.logger.log("Could not find %s" % python_updatebot_path, level=LogLevel.Warning)

            # Other libraries
            mozilla_central_yamls = self.run(["find", gecko_path, "-type", "f", "-name", "moz.yaml"]).stdout.decode().strip().split("\n")

            for file in mozilla_central_yamls:
                with open(file, "r") as mozyaml:
                    # Only return libraries that have enabled tasks
                    new_library_obj = LibraryProvider._validate_moz_yaml(mozyaml.read(), file.replace(gecko_path + "/", ""))
                    if new_library_obj.tasks:
                        self._libraries.append(new_library_obj)

        return self._libraries

    @staticmethod
    def _shared_library_validation(yaml, yaml_path, validated_library):
        validated_library['bugzilla_product'] = get_sub_key_or_raise('bugzilla', 'product', yaml, yaml_path)
        validated_library['bugzilla_component'] = get_sub_key_or_raise('bugzilla', 'component', yaml, yaml_path)

        # Updatebot keys aren't required by the schema, so if we don't have them
        # then we just leave it set to disabled
        if 'updatebot' in yaml:
            validated_library['maintainer_bz'] = get_sub_key_or_raise('updatebot', 'maintainer-bz', yaml, yaml_path)
            validated_library['maintainer_phab'] = get_sub_key_or_raise('updatebot', 'maintainer-phab', yaml, yaml_path)

            if 'tasks' in yaml['updatebot']:
                for t in yaml['updatebot']['tasks']:
                    validated_task = LibraryProvider.validate_task(t, validated_library['name'])

                    if validated_task['enabled']:
                        validated_library['tasks'].append(validated_task)

    @staticmethod
    def _validate_python_list(yaml_contents, yaml_path):
        packages = yaml.safe_load(yaml_contents)

        libraries = []
        for package in packages.keys():
            validated_library = {
                'name': '',
                'type': 'python',
                'bugzilla_product': '',
                'bugzilla_component': '',
                'revision': None,
                'repo_url': '',
                'maintainer_bz': '',
                'maintainer_phab': '',
                'tasks': [],
                'yaml_path': ''
            }

            # We assign this ourselves at import, so no need to check it
            validated_library['yaml_path'] = yaml_path

            validated_library['name'] = package
            LibraryProvider._shared_library_validation(packages[package], yaml_path, validated_library)

            libraries.append(Library(validated_library))

        return libraries

    @staticmethod
    def _validate_moz_yaml(yaml_contents, yaml_path):
        library = yaml.safe_load(yaml_contents)

        validated_library = {
            'name': '',
            'type': 'manifest',
            'bugzilla_product': '',
            'bugzilla_component': '',
            'revision': None,
            'repo_url': '',
            'maintainer_bz': '',
            'maintainer_phab': '',
            'tasks': [],
            'yaml_path': ''
        }

        # We assign this ourselves at import, so no need to check it
        validated_library['yaml_path'] = yaml_path

        validated_library['name'] = get_sub_key_or_raise('origin', 'name', library, yaml_path)

        # Attempt to get the revision (not required by moz.yaml) if present
        if 'origin' in library and 'revision' in library['origin']:
            validated_library['revision'] = library['origin']['revision']
        else:
            validated_library['revision'] = None

        # Attempt to get the repository url (not required by moz.yaml) if present
        if 'vendoring' in library and 'url' in library['vendoring']:
            validated_library['repo_url'] = library['vendoring']['url']
        else:
            validated_library['repo_url'] = None

        LibraryProvider._shared_library_validation(library, yaml_path, validated_library)

        if validated_library['tasks']:
            if not validated_library['repo_url']:
                raise Exception("If a library has Updatebot Tasks, then it must specify an upstream repository url")
            if not validated_library['revision']:
                raise Exception("If a library has Updatebot Tasks, then it must specify a current revision")
        return Library(validated_library)

    @staticmethod
    def validate_task(task_dict, library_name):
        validated_task = {
            'type': '',
            'enabled': '',
            'branch': '',
            'cc': '',
            'needinfo': '',
            'frequency': ''
        }

        if 'type' not in task_dict:
            raise AttributeError('library {0} task is missing type field'.format(library_name))
        if task_dict['type'] not in ['vendoring', 'commit-alert']:
            raise AttributeError('library {0} task has an invalid type field {1}'.format(library_name, task_dict['type']))

        validated_task['type'] = task_dict['type']

        validated_task['enabled'] = get_key_or_default('enabled', task_dict, False)
        validated_task['branch'] = get_key_or_default('branch', task_dict, None)
        validated_task['cc'] = get_key_or_default('cc', task_dict, [])
        validated_task['needinfo'] = get_key_or_default('needinfo', task_dict, [])
        validated_task['frequency'] = get_key_or_default('frequency', task_dict, 'every')

        if task_dict['type'] == 'commit-alert':
            validated_task['filter'] = get_key_or_default('filter', task_dict, 'none')
            validated_task['source-extensions'] = get_key_or_default('source-extensions', task_dict, None)
        else:
            if 'filter' in task_dict:
                raise AttributeError('library {0} task has a value for filter when type != commit-alert'.format(library_name))
            if 'source-extensions' in task_dict:
                raise AttributeError('library {0} task has a value for source-extensions when type != commit-alert'.format(library_name))

        return validated_task
