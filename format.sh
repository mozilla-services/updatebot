#!/bin/bash

poetry run autopep8 --in-place --recursive --ignore E501,E402 .
poetry run flake8 --ignore=E501,E402 .