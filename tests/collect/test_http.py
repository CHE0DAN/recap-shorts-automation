from recap_shorts.collect.http import Blocked
from tests.collect.conftest import FakeResp

PAGE = "<html><body><p>" + "시험용 본문입니다. " * 20 + "</p></body></html>"

U = "https://a.example/x"


def test_robots_disallow_blocks(make_client):
    c = make_client({"https://a.example/robots.txt": FakeResp(200, "User-agent: *\nDisallow: /x\n"),
                     U: FakeResp(200, PAGE)})
    r = c.fetch(U)
    assert isinstance(r, Blocked) and r.reason == "robots"
    assert U not in c.sess.calls  # 본문 요청은 하지 않음


def test_robots_missing_allows(make_client):
    c = make_client({U: FakeResp(200, PAGE)})
    assert c.fetch(U).status == 200


def test_robots_403_is_conservative(make_client):
    c = make_client({"https://a.example/robots.txt": FakeResp(403), U: FakeResp(200, PAGE)})
    assert c.fetch(U).reason == "robots"


def test_user_agent_is_honest(make_client):
    c = make_client({U: FakeResp(200, PAGE)})
    assert c.sess.headers["User-Agent"].startswith("recap-shorts-collector/0.1")
    assert "Mozilla" not in c.sess.headers["User-Agent"]


def test_403_429_401_skipped(make_client):
    for code, reason in [(403, "forbidden_403"), (429, "rate_limited_429"), (401, "auth_401")]:
        c = make_client({U: FakeResp(code)})
        r = c.fetch(U)
        assert isinstance(r, Blocked) and r.reason == reason
        assert c.sess.calls.count(U) == 1  # 재시도 안 함(5xx만 재시도)


def test_captcha_page_skipped(make_client):
    c = make_client({U: FakeResp(200, "<html><div class='g-recaptcha'></div>자동입력 방지 " + "문자 " * 10 + "</html>")})
    assert c.fetch(U).reason == "captcha"


def test_retry_once_on_5xx_then_ok(make_client):
    c = make_client({U: [FakeResp(503), FakeResp(200, PAGE)]})
    assert c.fetch(U).status == 200
    assert c.sess.calls.count(U) == 2


def test_5xx_twice_gives_up(make_client):
    c = make_client({U: FakeResp(500)})
    r = c.fetch(U)
    assert r.reason == "http_500" and c.sess.calls.count(U) == 2


def test_rate_limit_same_domain_3s(make_client):
    c = make_client({U: FakeResp(200, PAGE), "https://a.example/y": FakeResp(200, PAGE)})
    c.fetch(U)
    t0 = c.clock.t
    c.fetch("https://a.example/y")
    assert c.clock.t - t0 >= 3.0 - 1e-6


def test_rate_limit_other_domain_no_wait(make_client):
    c = make_client({U: FakeResp(200, PAGE), "https://b.example/y": FakeResp(200, PAGE)})
    c.fetch(U)
    c.clock.sleeps.clear()
    c.fetch("https://b.example/y")
    # 다른 도메인은 a 요청 때문에 기다리지 않는다. b 안에서 robots.txt와 본문 사이의 3초만 있다.
    assert c.clock.sleeps == [3.0]


def test_cache_prevents_refetch(make_client):
    c = make_client({U: FakeResp(200, PAGE)})
    c.fetch(U)
    r = c.fetch(U)
    assert r.from_cache and c.sess.calls.count(U) == 1
    assert list(c.cache_dir.glob("*.body"))


def test_redirect_followed_with_robots_each_hop(make_client):
    routes = {U: FakeResp(302, b"", {"Location": "https://b.example/final"}),
              "https://b.example/robots.txt": FakeResp(200, "User-agent: *\nDisallow: /final\n"),
              "https://b.example/final": FakeResp(200, PAGE)}
    r = make_client(routes).fetch(U)
    assert isinstance(r, Blocked) and r.reason == "robots"
    routes["https://b.example/robots.txt"] = FakeResp(404)
    r = make_client(routes).fetch(U)
    assert r.final_url == "https://b.example/final"


def test_soft_block_tiny_page_skipped(make_client):
    c = make_client({U: FakeResp(200, "<body><div class='con'><p><img src='403.jpg'></p></div></body>")})
    assert c.fetch(U).reason == "soft_block"


def test_soft_block_with_style_block(make_client):
    c = make_client({U: FakeResp(200, "<head><style>\nbody{text-align:center}\n</style></head><body><img src='403.jpg'></body>")})
    assert c.fetch(U).reason == "soft_block"
