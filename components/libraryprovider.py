#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import yaml

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


class LibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def get_libraries(self, gecko_path):
        libraries = []
        mozilla_central_yamls = self.run(["find", gecko_path, "-type", "f", "-name", "moz.yaml"]).stdout.decode().strip().split("\n")

        for file in mozilla_central_yamls:
            with open(file, "r") as mozyaml:
                # Only return libraries that have enabled tasks
                new_library_obj = LibraryProvider.validate_library(mozyaml.read(), file.replace(gecko_path + "/", ""))
                if new_library_obj.tasks:
                    libraries.append(new_library_obj)
        return libraries

    @staticmethod
    def validate_library(yaml_contents, yaml_path):
        library = yaml.safe_load(yaml_contents)

        validated_library = {
            'name': '',
            'bugzilla_product': '',
            'bugzilla_component': '',
            'revision': None,
            'maintainer_bz': '',
            'maintainer_phab': '',
            'tasks': [],
            'yaml_path': ''
        }

        validated_task = {
            'type':'',
            'enabled':'',
            'branch':'',
            'cc':''
        }

        # We assign this ourselves at import, so no need to check it
        validated_library['yaml_path'] = yaml_path

        def get_sub_key_or_raise(key, subkey, dict, yaml_path):
            if key in dict and subkey in dict[key]:
                return dict[key][subkey]
            else:
                raise AttributeError('library imported from {0} is missing {1}: {2} field'.format(yaml_path, key, subkey))

        validated_library['name'] = get_sub_key_or_raise('origin', 'name', library, yaml_path)
        validated_library['bugzilla_product'] = get_sub_key_or_raise('bugzilla', 'product', library, yaml_path)
        validated_library['bugzilla_component'] = get_sub_key_or_raise('bugzilla', 'component', library, yaml_path)

        # Attempt to get the revision (not required by moz.yaml) if present
        if 'origin' in library and 'revision' in library['origin']:
            validated_library['revision'] = library['origin']['revision']
        else:
            validated_library['revision'] = None

        # Updatebot keys aren't required by the schema, so if we don't have them
        # then we just leave it set to disabled
        if 'updatebot' in library:
            validated_library['maintainer_bz'] = get_sub_key_or_raise('updatebot', 'maintainer-bz', library, yaml_path)
            validated_library['maintainer_phab'] = get_sub_key_or_raise('updatebot', 'maintainer-phab', library, yaml_path)

            if 'tasks' in library['updatebot']:
                for t in library['updatebot']['tasks']:
                    validated_task = LibraryProvider.validate_task(t, library['origin']['name'])

                    if validated_task['enabled']:
                        validated_library['tasks'].append(validated_task)

        return Library(validated_library)

    @staticmethod
    def validate_task(task_dict, library_name):
        validated_task = {}
        if 'type' not in task_dict:
            raise AttributeError('library {0} task is missing type field'.format(library_name))
        if task_dict['type'] not in ['vendoring', 'commit-alert']:
            raise AttributeError('library {0} task has an invalid type field {1}'.format(library_name, task_dict['type']))

        validated_task['type'] = task_dict['type']

        validated_task['enabled'] = task_dict['enabled'] if 'enabled' in task_dict else False

        if 'branch' in task_dict:
            validated_task['branch'] = task_dict['branch']
        else:
            validated_task['branch'] = None

        if 'cc' in task_dict:
            validated_task['cc'] = task_dict['cc']
        else:
            validated_task['cc'] = []

        if task_dict['type'] == 'commit-alert':
            if 'filter' in task_dict:
                validated_task['filter'] = task_dict['filter']
            else:
                validated_task['filter'] = 'none'

            if 'source-extensions' in task_dict:
                validated_task['source-extensions'] = task_dict['source-extensions']
            else:
                validated_task['source-extensions'] = None

        else:
            if 'filter' in task_dict:
                raise AttributeError('library {0} task has a value for filter when type != commit-alert'.format(library_name))
            if 'source-extensions' in task_dict:
                raise AttributeError('library {0} task has a value for source-extensions when type != commit-alert'.format(library_name))

        return validated_task
