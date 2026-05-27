"""Social provider integration (T6-02).

Provider plugin + OAuth + an ``athena search_x`` tool routed via
the T5-01 capability manifest (``social_search``). The
broker (T5-05) picks the social provider when an explicit
:func:`athena.social.search.run_search_x` call fires, even when
a different model is the primary chat backend; the result folds
back into the primary's context.

Vendor specifics (model name, OAuth endpoints, scopes, the
exact search API shape) are isolated to
:mod:`athena.social.oauth` + :mod:`athena.providers.social` so a
vendor change is a one-or-two-file edit.
"""

from .oauth import SocialOAuth, TokenStore
from .search import search_x
from .user_lookup import lookup_x_user

__all__ = ["SocialOAuth", "TokenStore", "lookup_x_user", "search_x"]
