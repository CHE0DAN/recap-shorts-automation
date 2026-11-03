from recap_shorts.collect.robots import Robots

DC_LIKE = """User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /
Disallow: /kcaptcha/
Disallow: /board/lists/?id=stock_new
Disallow: /board/view/?id=stock_new
"""


def test_allow_first_does_not_hide_specific_disallow():
    r = Robots(DC_LIKE)
    assert r.can_fetch("https://x/board/lists/?id=programming&page=1")
    assert not r.can_fetch("https://x/board/lists/?id=stock_new&page=1")
    assert not r.can_fetch("https://x/board/view/?id=stock_new&no=3")
    assert not r.can_fetch("https://x/kcaptcha/a")


def test_ai_bot_group_does_not_apply_to_us():
    assert Robots(DC_LIKE).can_fetch("https://x/anything")


def test_longest_match_and_allow_tie():
    r = Robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c\nAllow: /c\n")
    assert r.can_fetch("https://x/a/b/1") and not r.can_fetch("https://x/a/z") and r.can_fetch("https://x/c")


def test_wildcards_and_anchor():
    r = Robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /x*?recommend=\n")
    assert not r.can_fetch("https://x/a/b.pdf") and r.can_fetch("https://x/a/b.pdf2")
    assert not r.can_fetch("https://x/x/y?recommend=1")


def test_specific_agent_group_wins():
    r = Robots("User-agent: recap-shorts-collector\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not r.can_fetch("https://x/a")


def test_empty_disallow_allows():
    assert Robots("User-agent: *\nDisallow:\n").can_fetch("https://x/a")
