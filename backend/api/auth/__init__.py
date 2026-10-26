# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Authentication API endpoints: Google OAuth tokens, and LAN sign-out."""
from .google import router as google_router
from .signout import router as signout_router

__all__ = ["google_router", "signout_router"]
