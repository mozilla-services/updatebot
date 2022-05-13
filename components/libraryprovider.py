#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import yaml
import platform
import functools

from components.logging import LogLevel
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


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
        self.bugzilla_product = dict['bugzilla_product']
        self.bugzilla_component = dict['bugzilla_component']
        self.revision = dict['revision']
        self.repo_url = dict['repo_url']
        self.has_patches = dict['has_patches']
        self.maintainer_bz = dict['maintainer_bz']
        self.maintainer_phab = dict['maintainer_phab']
        self.fuzzy_query = dict.get('fuzzy_query', None)
        self.fuzzy_paths = dict.get('fuzzy_paths', None)
        self.yaml_path = dict['yaml_path']
        self.tasks = []

        for t in dict['tasks']:
            self.tasks.append(Task(t))

    def __eq__(self, other):
        if not isinstance(other, Library):
            print("not a library")
            return False

        for prop in dir(self):
            if not prop.startswith("__") and prop != "id":
                try:
                    if getattr(other, prop) != getattr(self, prop):
                        print(self.name, prop, "other:", getattr(other, prop), "self:", getattr(self, prop))
                        return False
                except AttributeError:
                    print(prop, "attributeerror")
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
        self.platform = dict['platform']

        if self.type == 'commit-alert':
            self.filter = dict['filter']
            self.source_extensions = dict['source-extensions']

    def __eq__(self, other):
        if not isinstance(other, Task):
            print("not a task")
            return False

        for prop in dir(self):
            if not prop.startswith("__") and prop != "id":
                try:
                    if getattr(other, prop) != getattr(self, prop):
                        print(prop, getattr(other, prop), getattr(self, prop))
                        return False
                except AttributeError:
                    print(prop, "attributeerror")
                    return False

        return True


def get_sub_key_or_none(key, subkey, dict, yaml_path):
    if key in dict and subkey in dict[key]:
        return dict[key][subkey]
    return None


def get_sub_key_or_raise(key, subkey, dict, yaml_path):
    ret = get_sub_key_or_none(key, subkey, dict, yaml_path)
    if ret is None:
        raise AttributeError('library imported from {0} is missing {1}: {2} field'.format(yaml_path, key, subkey))
    return ret


def get_key_or_default(key, dict, default):
    return dict[key] if key in dict else default


class LibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._libraries = None

    def get_libraries(self, gecko_path):
        if self._libraries is None:
            libraries = []
            if platform.system() == 'Windows':
                # dir is not an executable but a built-in of the Windows shell, so we need to run
                # this with shell=True
                command = ["dir", "/B", "/S", os.path.join(gecko_path, "moz.yaml")]
                mozilla_central_yamls = self.run(" ".join(command), shell=True).stdout.decode()
            else:
                command = ["find", gecko_path, "-type", "f", "-name", "moz.yaml"]
                mozilla_central_yamls = self.run(command).stdout.decode()

            mozilla_central_yamls = mozilla_central_yamls.strip().split("\n")
            for file in mozilla_central_yamls:
                file = file.strip()  # Needed to remove the Windows trailing \r
                if not file:
                    continue
                with open(file, "r") as mozyaml:
                    self.logger.log("Processing", file, level=LogLevel.Info)
                    # Only return libraries that have enabled tasks
                    new_library_obj = LibraryProvider.validate_library(mozyaml.read(), file.replace(gecko_path + os.path.sep, ""))
                    if new_library_obj.tasks:
                        self.logger.log("%s had %s Updatebot tasks" % (file, len(new_library_obj.tasks)), level=LogLevel.Info)
                        libraries.append(new_library_obj)

            self._libraries = libraries

        return self._libraries

    @staticmethod
    def validate_library(yaml_contents, yaml_path):
        library = yaml.safe_load(yaml_contents)

        validated_library = {
            'name': '',
            'bugzilla_product': '',
            'bugzilla_component': '',
            'revision': None,
            'repo_url': '',
            'has_patches': False,
            'maintainer_bz': '',
            'maintainer_phab': '',
            'fuzzy_query': '',
            'fuzzy_paths': [],
            'tasks': [],
            'yaml_path': ''
        }

        validated_task = {
            'type': '',
            'enabled': '',
            'branch': '',
            'cc': '',
            'needinfo': '',
            'frequency': '',
            'platform': ''
        }

        get_or_none = functools.partial(get_sub_key_or_none, dict=library, yaml_path=yaml_path)
        get_or_raise = functools.partial(get_sub_key_or_raise, dict=library, yaml_path=yaml_path)

        # We assign this ourselves at import, so no need to check it
        validated_library['yaml_path'] = yaml_path

        validated_library['name'] = get_or_raise('origin', 'name')
        validated_library['bugzilla_product'] = get_or_raise('bugzilla', 'product')
        validated_library['bugzilla_component'] = get_or_raise('bugzilla', 'component')

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

        if 'vendoring' in library and 'patches' in library['vendoring']:
            validated_library['has_patches'] = not not library['vendoring']['patches']
        else:
            validated_library['has_patches'] = False

        # Updatebot keys aren't required by the schema, so if we don't have them
        # then we just leave it set to disabled
        if 'updatebot' in library:
            validated_library['maintainer_bz'] = get_or_raise('updatebot', 'maintainer-bz')
            validated_library['maintainer_phab'] = get_or_raise('updatebot', 'maintainer-phab')
            validated_library['fuzzy_query'] = get_or_none('updatebot', 'fuzzy-query')
            validated_library['fuzzy_paths'] = get_or_none('updatebot', 'fuzzy-paths')

            if 'tasks' in library['updatebot']:
                for t in library['updatebot']['tasks']:
                    validated_task = LibraryProvider.validate_task(t, library['origin']['name'])

                    if validated_task['enabled'] and validated_task['platform'] == platform.system().lower():
                        validated_library['tasks'].append(validated_task)

        if validated_library['tasks']:
            if not validated_library['repo_url']:
                raise Exception("If a library has Updatebot Tasks, then it must specify an upstream repository url")
            if not validated_library['revision']:
                raise Exception("If a library has Updatebot Tasks, then it must specify a current revision")
        return Library(validated_library)

    @staticmethod
    def validate_task(task_dict, library_name):
        validated_task = {}

        if 'type' not in task_dict:
            raise AttributeError('library {0} task is missing type field'.format(library_name))
        if task_dict['type'] not in ['vendoring', 'commit-alert']:
            raise AttributeError('library {0} task has an invalid type field {1}'.format(library_name, task_dict['type']))

        validated_task['type'] = task_dict['type']

        validated_task['enabled'] = get_key_or_default('enabled', task_dict, False)
        validated_task['branch'] = get_key_or_default('branch', task_dict, None)
        validated_task['platform'] = get_key_or_default('platform', task_dict, 'linux').lower()
        validated_task['cc'] = get_key_or_default('cc', task_dict, [])
        validated_task['needinfo'] = get_key_or_default('needinfo', task_dict, [])
        validated_task['frequency'] = get_key_or_default('frequency', task_dict, 'every')

        if validated_task['platform'] not in ('windows', 'linux'):
            raise AttributeError('library {0} task has an invalid value for a platform: {1}'.format(library_name, validated_task['platform']))

        if task_dict['type'] == 'commit-alert':
            validated_task['filter'] = get_key_or_default('filter', task_dict, 'none')
            validated_task['source-extensions'] = get_key_or_default('source-extensions', task_dict, None)
        else:
            if 'filter' in task_dict:
                raise AttributeError('library {0} task has a value for filter when type != commit-alert'.format(library_name))
            if 'source-extensions' in task_dict:
                raise AttributeError('library {0} task has a value for source-extensions when type != commit-alert'.format(library_name))

        return validated_task
