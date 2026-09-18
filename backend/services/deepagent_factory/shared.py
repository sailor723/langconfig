# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared logging for the deep agent factory.

Extracted from the former monolithic deepagent_factory.py so the mixin
modules (preflight, assembly, support) reuse one logger without importing
the package ``__init__`` (which would create a circular import).
"""

import logging

# Preserve the original logger identity so log filters keyed on
# "services.deepagent_factory" keep working after the split.
logger = logging.getLogger("services.deepagent_factory")
