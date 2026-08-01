# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Shared state for the api.knowledge.rag package.

Sub-modules import the logger from here (never from the package
__init__) so its identity stays ``api.knowledge.rag`` across the split.
"""
import logging

logger = logging.getLogger("api.knowledge.rag")
