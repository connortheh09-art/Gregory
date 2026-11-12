"""Categorisable provider-output failure; never includes model response text."""


class ProviderReplyError(ValueError):
    """The local model did not produce a bounded, complete dialogue object."""
