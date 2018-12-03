#!/usr/bin/env bash

# Copyright (c) 2018 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

set -o errexit;

TRAVIS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PRJ_DIR="$( cd "${TRAVIS_DIR}/.." && pwd )"

source "${PRJ_DIR}/.venv/bin/activate"

export MYPYPATH="${PRJ_DIR}:${TRAVIS_DIR}/unit-e/test/functional:${MYPYPATH}"
export PYTHONPATH="${PRJ_DIR}:${TRAVIS_DIR}/unit-e/test/functional:${PYTHONPATH}"

pytest

deactivate
