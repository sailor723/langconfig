# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared logging for the execution event emitter.

Extracted from the former monolithic emitter.py so the mixin modules
(callbacks, internal) reuse one logger without importing the package
``__init__`` (which would create a circular import).
"""

import logging

# Preserve the original logger identity so log filters keyed on
# "core.workflows.events.emitter" keep working after the split.
logger = logging.getLogger("core.workflows.events.emitter")
