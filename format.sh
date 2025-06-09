#!/bin/bash

poetry run autopep8 .
poetry run flake8 .

output=$(find . -type f -name '*.py' -exec awk '
    /^[ \t]*@retry[ \t]*$/ {
        getline a
        if (a ~ /^[ \t]*@logEntryExit[ \t]*$/) {
            getline b
            print FILENAME ":"
            print $0 "\n" a "\n" b "\n"
        }
    }
' {} +)

# Check if there was any output
if [[ -n "$output" ]]; then
    echo "@retry must always be the decorator right before a function. Please fix these:"
    echo "$output"
fi