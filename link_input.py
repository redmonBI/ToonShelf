"""URL input shared by the desktop and dependency-free community worker."""
import re
from urllib.parse import urlsplit, urlunsplit

def normalize_url(value):
    if not isinstance(value,str):raise ValueError('사이트 주소를 입력하세요.')
    value=value.strip().strip('\ufeff\u200b').strip()
    # Chat/clipboard links can contain a Markdown label instead of a bare URL.
    match=re.fullmatch(r'\[[^\]\r\n]*\]\((https?://[^\s]+)\)',value,re.I)
    if match:value=match.group(1)
    if len(value)>1 and ((value[0],value[-1]) in [('<','>'),('"','"'),("'","'")]):value=value[1:-1].strip()
    if not value or len(value)>2000:raise ValueError('사이트 주소를 입력하세요. 예: https://example.com')
    bare_port=re.match(r'^[a-z0-9.-]+:\d+(?:[/?#]|$)',value,re.I)
    if bare_port or not re.match(r'^[a-z][a-z0-9+.-]*:',value,re.I):value='https://'+value
    try:
        p=urlsplit(value)
        valid=p.scheme.lower() in ('http','https') and p.hostname and not p.username and not p.password
        valid=valid and '@' not in p.netloc and not re.search(r'[\s\\\x00-\x1f\x7f]',value)
        p.port  # Reject malformed or out-of-range ports.
    except ValueError:valid=False
    if not valid:raise ValueError('http 또는 https 사이트 주소를 입력하세요. 예: https://example.com')
    return urlunsplit((p.scheme.lower(),p.netloc,p.path,p.query,p.fragment))
