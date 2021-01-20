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
#     'enabled': True,
#     'maintainer-bz': 'nobody@mozilla.com',
#     'maintainer-phab': 'nobody'
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
                new_library = yaml.safe_load(mozyaml.read())
                new_library['yaml_path'] = file.replace(gecko_path + "/", "")

                # Only process libraries that are enabled for processing
                if 'updatebot' in new_library and 'enabled' in new_library['updatebot'] and new_library['updatebot']['enabled']:
                    libraries.append(self.validate_library(new_library))
        return libraries

    def validate_library(self, library):
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
                'enabled': False,
                'maintainer-bz': '',
                'maintainer-phab': ''
            },
            'yaml_path': ''
        })

        # We assign this ourselves at import, so no need to check it
        validated_library.yaml_path = library['yaml_path']

        # This isn't required by the moz.yaml schema, but we need it to do
        # anything with the library, so we pretend like it is required
        if 'origin' in library and 'name' in library['origin']:
            validated_library.origin['name'] = library['origin']['name']
        else:
            # Clarify exception by name of file imported since we assign that
            # ourselves at import
            raise AttributeError('library imported from {0} is missing origin: name field'.format(library['yaml_path']))

        # Attempt to get the revision (not required by moz.yaml) if present
        if 'origin' in library and 'revision' in library['origin']:
            validated_library.origin['revision'] = library['origin']['revision']

        # From here on we can use the library's name in the exception since we
        # know it exists
        if 'bugzilla' in library and 'product' in library['bugzilla']:
            validated_library.bugzilla['product'] = library['bugzilla']['product']
        else:
            raise AttributeError('library {0} is missing bugzilla: product field'.format(library['origin']['name']))

        if 'bugzilla' in library and 'component' in library['bugzilla']:
            validated_library.bugzilla['component'] = library['bugzilla']['component']
        else:
            raise AttributeError('library {0} is missing bugzilla: component field'.format(library['origin']['name']))

        # Updatebot keys aren't required by the schema, so if we don't have them
        # then we just leave it set to disabled
        if 'updatebot' in library and 'enabled' in library['updatebot']:
            validated_library.updatebot['enabled'] = library['updatebot']['enabled']

            # These updatebot keys are required if the updatebot section exists
            # in the moz.yaml file, so we report an error if they're missing
            if 'maintainer-bz' in library['updatebot']:
                validated_library.updatebot['maintainer-bz'] = library['updatebot']['maintainer-bz']
            else:
                raise AttributeError('library {0} is missing updatebot: maintainer-bz field'.format(library['origin']['name']))
            if 'maintainer-phab' in library['updatebot']:
                validated_library.updatebot['maintainer-phab'] = library['updatebot']['maintainer-phab']
            else:
                raise AttributeError('library {0} is missing updatebot: maintainer-phab field'.format(library['origin']['name']))

        return validated_library
