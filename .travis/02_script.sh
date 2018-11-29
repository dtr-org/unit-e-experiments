#!/usr/bin/env bash

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

TRAVIS_SCRIPTS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "${TRAVIS_SCRIPTS_DIR}/.." && pwd )"

source "${PROJECT_DIR}/.venv/bin/activate"
export $(egrep -v '^#' .env | xargs -d '\n')

pytest

deactivate
