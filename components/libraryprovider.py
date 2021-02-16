#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import yaml

from components.utilities import Struct
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
#     'jobs': [
#         { 'type': 'vendoring',
#           ' enabled': True,
#         }
#     ]
# },
# 'yaml_path': '/Users/nobody/mozilla-central/media/libdav1d/moz.yaml'


class LibraryProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def get_libraries(self, gecko_path):
        libraries = []
        mozilla_central_yamls = self.run(["find", gecko_path, "-type", "f", "-name", "moz.yaml"]).stdout.decode().strip().split("\n")

        for file in mozilla_central_yamls:
            with open(file, "r") as mozyaml:
                # Only return libraries that have enabled jobs
                new_library_obj = self.validate_library(mozyaml.read(), file.replace(gecko_path + "/", ""))
                if new_library_obj.updatebot['jobs']:
                    libraries.append(new_library_obj)
        return libraries

    def validate_library(self, yaml_contents, yaml_path):
        library = yaml.safe_load(yaml_contents)

        validated_library = Struct(**{
            'bugzilla': {
                'product': '',
                'component': ''
            },
            'origin': {
                'name': '',
                'revision': ''
            },
            'updatebot': {
                'maintainer-bz': '',
                'maintainer-phab': '',
                'jobs': []
            },
            'yaml_path': ''
        })

        # We assign this ourselves at import, so no need to check it
        validated_library.yaml_path = yaml_path

        def get_sub_key_or_raise(key, subkey, dict, yaml_path):
            if key in dict and subkey in dict[key]:
                return dict[key][subkey]
            else:
                raise AttributeError('library imported from {0} is missing {1}: {2} field'.format(yaml_path, key, subkey))

        validated_library.origin['name'] = get_sub_key_or_raise('origin', 'name', library, yaml_path)
        validated_library.bugzilla['product'] = get_sub_key_or_raise('bugzilla', 'product', library, yaml_path)
        validated_library.bugzilla['component'] = get_sub_key_or_raise('bugzilla', 'component', library, yaml_path)

        # Attempt to get the revision (not required by moz.yaml) if present
        if 'origin' in library and 'revision' in library['origin']:
            validated_library.origin['revision'] = library['origin']['revision']

        # Updatebot keys aren't required by the schema, so if we don't have them
        # then we just leave it set to disabled
        if 'updatebot' in library:
            validated_library.updatebot['maintainer-bz'] = get_sub_key_or_raise('updatebot', 'maintainer-bz', library, yaml_path)
            validated_library.updatebot['maintainer-phab'] = get_sub_key_or_raise('updatebot', 'maintainer-phab', library, yaml_path)

            if 'jobs' in library['updatebot']:
                indx = 0
                for j in library['updatebot']['jobs']:
                    validated_job = {}
                    if 'type' not in j:
                        raise AttributeError('library {0}, job {1} is missing type field'.format(library['origin']['name'], indx))
                    if j['type'] not in ['vendoring', 'commit-alert']:
                        raise AttributeError('library {0}, job {1} has an invalid type field {2}'.format(library['origin']['name'], indx, j['type']))
                    validated_job['type'] = j['type']

                    validated_job['enabled'] = j['enabled'] if 'enabled' in j else False

                    if 'branch' in j:
                        validated_job['branch'] = j['branch']
                    if 'cc' in j:
                        validated_job['cc'] = j['cc']

                    if 'filter' in j:
                        if j['type'] != 'commit-alert':
                            raise AttributeError('library {0}, job {1} has an invalid value for filter when type != commit-alert'.format(library['origin']['name'], indx))
                        validated_job['filter'] = j['filter']

                    if 'source-extensions' in j:
                        if j['type'] != 'commit-alert':
                            raise AttributeError('library {0}, job {1} has an invalid value for source-extensions when type != commit-alert'.format(library['origin']['name'], indx))
                        validated_job['source-extensions'] = j['source-extensions']

                    if validated_job['enabled']:
                        validated_library.updatebot['jobs'].append(validated_job)
                    indx += 1

        return validated_library
