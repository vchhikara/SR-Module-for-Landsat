# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove credentials from text before it leaves the process (logs, dialogs)."""
import re

_USERINFO = re.compile(r'(?<=://)[^/\s\'"]*@')
_QUERY = re.compile(r'(://[^\s\'"?]*\?)[^\s\'"]+')
_SECRET = re.compile(
    r'(?i)([\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|signature|authcfg|authorization)'
    r'[\w-]*|\bkey|\bsig|\buser(?:name)?)([\'"]?\s*[=:]\s*)'
    r'("[^"]*"|\'[^\']*\'|(?:bearer\s+|basic\s+)?[^\s&;,|]+)')


def redact(text):
    text = _USERINFO.sub('***@', str(text))
    text = _QUERY.sub(r'\1***', text)
    return _SECRET.sub(r'\1\2***', text)
