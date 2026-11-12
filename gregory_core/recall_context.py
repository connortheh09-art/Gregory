"""Small routing/context helpers, not a second memory store or persona."""
import re


def request_kind(text):
    text=' '.join(text.lower().split())
    # Explicit write requests are not implemented yet. A question asking whether
    # Gregory remembers something must NOT be treated as a request to save it.
    if (re.search(r'\b(?:please|can you|could you|you should(?: probably)?) '
                  r'(?:save|store|jot|note|write down)\b',text) or
        re.search(r'\b(?:please|you should(?: probably)?) remember (?:my |that |this |i )',text) or
        re.search(r'\b(?:can|could) you remember (?:that .+|my name is .+)',text) or
        re.match(r'^(?:remember (?:my |that |this |i |the name)|save |store |jot .+ down)',text)):
        return 'write'
    if (re.fullmatch(r'what memories (?:do|can) you (?:actually )?(?:have|recall|remember)[?!.]*',text) or
        re.fullmatch(r'what (?:do|can) you (?:actually )?remember(?: (?:at all|so far|in general))?[?!.]*',text) or
        re.fullmatch(r'(?:list|show|tell me(?: about)?) (?:me )?(?:all )?(?:your|the) memories[?!.]*',text)):
        return 'overview'
    if re.search(r'\b(?:memor(?:y|ies)|remember|recall|experienced)\b|\bhave you ever\b',text):
        return 'recall'
    return 'conversation'
