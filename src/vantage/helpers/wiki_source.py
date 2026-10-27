"""Bounded, passive HTML access to the public P99 Wiki mirror.

Only pages explicitly requested by the user are fetched. This module creates
no local database and never solves challenges or probes an upstream origin.
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

ORIGIN = 'https://p99.funcamp.net'
CANONICAL_ORIGIN = 'https://wiki.project1999.com'
PAGE_TEMPLATE = ORIGIN + '/{slug}'
SOURCE_NAME = 'Project 1999 Wiki · public mirror'
MAX_PAGE_BYTES = 2_000_000
_HOSTS = {'p99.funcamp.net', 'wiki.project1999.com'}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
         'link', 'meta', 'param', 'source', 'track', 'wbr'}
_DROP = {'script', 'style', 'iframe', 'object', 'embed', 'form', 'input',
         'button', 'textarea', 'select', 'svg', 'math', 'link', 'meta', 'base'}
_ALLOWED = {'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'center', 'code',
            'col', 'colgroup', 'dd', 'del', 'div', 'dl', 'dt', 'em', 'h1',
            'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol',
            'p', 'pre', 's', 'small', 'span', 'strong', 'sub', 'sup',
            'table', 'tbody', 'td', 'th', 'thead', 'tfoot', 'tr', 'u', 'ul'}


def title_from_url(value):
    """Resolve article links from either known site; reject active/foreign URLs."""
    value = str(value or '').strip()
    if not value or value.startswith('#'):
        return ''
    try:
        parsed = urlsplit(urljoin(ORIGIN + '/', value))
        trusted = (parsed.scheme == 'https' and parsed.hostname in _HOSTS and
                   not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        trusted = False
    if not trusted:
        return ''
    path = unquote(parsed.path).lstrip('/')
    if path == 'index.php':
        path = parse_qs(parsed.query).get('title', [''])[0]
    elif path.startswith('index.php_title='):
        path = path[len('index.php_title='):].split('&', 1)[0]
    if not path or path in {'api.php', 'index.php'}:
        return ''
    return path.replace('_', ' ').strip()[:300]


def page_url(title):
    title = str(title or '').strip()
    if re.match(r'^[a-z][a-z0-9+.-]*:', title, re.I) and '://' in title:
        title = title_from_url(title)
    title = title.replace('_', ' ').strip()
    if not title or len(title) > 300 or any(ord(c) < 32 for c in title):
        raise ValueError('Invalid Wiki page name')
    return ORIGIN + '/' + quote(title.replace(' ', '_'), safe="()'-")


def image_url(value):
    try:
        parsed = urlsplit(urljoin(ORIGIN + '/', str(value or '').strip()))
        trusted = (parsed.scheme == 'https' and parsed.hostname in _HOSTS and
                   not parsed.username and not parsed.password and parsed.port in (None, 443) and
                   parsed.path.startswith(('/images/', '/w/images/')))
    except ValueError:
        trusted = False
    if not trusted:
        return ''
    return ORIGIN + parsed.path


def reference_url(value):
    """Normalize article links and the mirror's static quest pagination."""
    title = title_from_url(value)
    if not title:
        return ''
    parsed = urlsplit(urljoin(ORIGIN + '/', str(value).strip()))
    if title == 'Category:Quests':
        query = parsed.query
        if parsed.path.startswith('/index.php_title=') and '&' in parsed.path:
            query = parsed.path.split('&', 1)[1]
        cursor = parse_qs(query).get('pagefrom', [''])[0]
        raw_cursor = next((part.split('=', 1)[1] for part in query.split('&')
                           if part.startswith('pagefrom=')), '')
        if (cursor and len(cursor) <= 300 and not any(ord(c) < 32 for c in cursor)
                and re.fullmatch(r"[A-Za-z0-9%+_.~!'()*,:@/-]{1,900}", raw_cursor)):
            # These are literal snapshot filenames: + and %27 are not
            # interchangeable with %20 and ' on the static mirror.
            return ORIGIN + '/index.php_title=Category:Quests&pagefrom=' + raw_cursor
    result = page_url(title)
    if parsed.fragment:
        result += '#' + quote(unquote(parsed.fragment)[:300], safe='_-')
    return result


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.parent = parent
        self.children = []

    def find_all(self, tag=None, **attrs):
        for child in self.children:
            if not isinstance(child, Node):
                continue
            matches = tag is None or child.tag == tag
            for key, expected in attrs.items():
                key = key.rstrip('_')
                actual = child.attrs.get(key, '')
                matches = matches and (expected in actual.split() if key == 'class'
                                       else actual == expected)
            if matches:
                yield child
            yield from child.find_all(tag, **attrs)

    def find(self, tag=None, **attrs):
        return next(self.find_all(tag, **attrs), None)

    def text(self, separator=' '):
        values = []
        for child in self.children:
            value = child.text(separator) if isinstance(child, Node) else child
            value = ' '.join(value.split())
            if value:
                values.append(value)
        return separator.join(values)

    def inner_html(self):
        return ''.join(child.html() if isinstance(child, Node)
                       else html.escape(child, quote=False) for child in self.children)

    def html(self):
        if not self.tag:
            return self.inner_html()
        attrs = ''.join(f' {key}="{html.escape(str(value), quote=True)}"'
                        for key, value in self.attrs.items())
        start = f'<{self.tag}{attrs}>'
        return start if self.tag in _VOID else start + self.inner_html() + f'</{self.tag}>'


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 60000 or len(self.stack) > 128:
            raise ValueError('Wiki page structure is too large')
        if tag in {'td', 'th', 'tr', 'li', 'p'} and self.stack[-1].tag == tag:
            self.stack.pop()
        node = Node(tag, dict(attrs), self.stack[-1])
        node.attrs = {key: value or '' for key, value in node.attrs.items()}
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(value):
    value = str(value or '')
    if len(value.encode('utf-8')) > MAX_PAGE_BYTES:
        raise ValueError('Wiki page is larger than the safe limit')
    parser = _Tree()
    parser.feed(value)
    parser.close()
    return parser.root


def sanitize_html(rendered, *, keep_images=False):
    """Keep passive article markup and safe mirror links, never active embeds."""
    root = parse_html(rendered)

    def clean(node):
        output = []
        for child in node.children:
            if isinstance(child, str):
                output.append(html.escape(child, quote=False))
                continue
            if child.tag in _DROP or child.tag == 'img' and not keep_images:
                continue
            inner = clean(child)
            if child.tag not in _ALLOWED:
                output.append(inner)
                continue
            attrs = {}
            for key in ('class', 'id', 'title', 'colspan', 'rowspan'):
                if key in child.attrs:
                    attrs[key] = str(child.attrs[key])[:400]
            if child.tag == 'a':
                href = child.attrs.get('href', '').strip()
                if href.startswith('#'):
                    attrs['href'] = href[:300]
                else:
                    target = reference_url(href)
                    if target:
                        attrs['href'] = target
            if child.tag == 'img':
                src = image_url(child.attrs.get('src'))
                if not src:
                    continue
                attrs['src'] = src
                attrs['alt'] = child.attrs.get('alt', '')[:300]
            encoded = ''.join(f' {key}="{html.escape(value, quote=True)}"'
                              for key, value in attrs.items())
            output.append(f'<{child.tag}{encoded}>' + ('' if child.tag in _VOID
                          else inner + f'</{child.tag}>'))
        return ''.join(output)

    return clean(root)


def section_html(rendered, names):
    """Return a heading's content, including subsections until the next peer."""
    if isinstance(names, str):
        names = (names,)
    wanted = {' '.join(str(name).replace('_', ' ').casefold().split()) for name in names}
    headings = list(re.finditer(r'<h([1-6])\b[^>]*>(.*?)</h\1\s*>',
                                str(rendered or ''), re.I | re.S))
    for index, heading in enumerate(headings):
        label = parse_html(heading.group(2)).text().replace('[ edit ]', '').replace('[edit]', '').strip()
        if ' '.join(label.replace('_', ' ').casefold().split()) not in wanted:
            continue
        level = int(heading.group(1))
        end = len(rendered)
        for following in headings[index + 1:]:
            if int(following.group(1)) <= level:
                end = following.start()
                break
        return rendered[heading.end():end]
    return ''


def parse_page(raw, title_hint=''):
    if isinstance(raw, bytes):
        if len(raw) > MAX_PAGE_BYTES:
            raise ValueError('Wiki response is larger than the safe limit')
        source = raw.decode('utf-8', errors='replace')
    else:
        source = str(raw or '')
    if any(marker in source[:20000].casefold() for marker in
           ('cf-chl-', 'challenge-platform', '<title>just a moment', '<title>403')):
        raise ValueError('Wiki mirror is temporarily unavailable')
    root = parse_html(source)
    body = root.find(id='mw-content-text')
    if (body is None or not body.text() or body.find(class_='noarticletext') or
            'noarticletext' in body.attrs.get('class', '').split()):
        raise ValueError('The Wiki mirror does not have this page')
    heading = root.find(id='firstHeading') or root.find('h1')
    title = heading.text() if heading else str(title_hint or '').strip()
    if not title:
        raise ValueError('Wiki mirror returned an incomplete page')
    rendered = sanitize_html(body.inner_html(), keep_images=True)
    article = parse_html(rendered)
    if not article.text():
        raise ValueError('Wiki mirror returned no readable article content')
    images = [node.attrs['src'] for node in article.find_all('img')]
    return {'parse': {'title': title, 'text': {'*': rendered},
                      'wikitext': {'*': ''}, 'images': images},
            '_mirror': True, '_source': SOURCE_NAME, '_source_url': page_url(title)}
