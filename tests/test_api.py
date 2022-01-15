import json
import os
from io import BytesIO
from operator import itemgetter
from pathlib import Path
from urllib.parse import urlencode

import click
import pytest

from lektor.admin import WebAdmin
from lektor.admin.utils import eventstream
from lektor.constants import PRIMARY_ALT
from lektor.environment import Environment
from lektor.project import Project
from lektor.publisher import PublishError


# FIXME: move this sorting test to test_editor
# See #969
@pytest.fixture
def children_records_data():
    """Returns test values for children records' `id`, `title`, and `pub_date` fields."""
    return (
        {"id": "1", "title": "1 is the first number", "pub_date": "2016-07-11"},
        {
            "id": "2",
            "title": "Must be the Second item in a row",
            "pub_date": "2017-05-03",
        },
        {"id": "3", "title": "Z is the last letter", "pub_date": "2017-05-03"},
        {"id": "4", "title": "Some random string", "pub_date": "2018-05-21"},
    )


@pytest.fixture(scope="function", autouse=True)
def prepare_stub_data(scratch_project, children_records_data):
    """Creates folders, models, test object and its children records."""
    tree = scratch_project.tree
    with open(os.path.join(tree, "models", "mymodel.ini"), "w", encoding="utf-8") as f:
        f.write("[children]\n" "order_by = -pub_date, title\n")
    with open(
        os.path.join(tree, "models", "mychildmodel.ini"), "w", encoding="utf-8"
    ) as f:
        f.write(
            "[fields.title]\n" "type = string\n" "[fields.pub_date]\n" "type = date"
        )
    os.mkdir(os.path.join(tree, "content", "myobj"))
    with open(
        os.path.join(tree, "content", "myobj", "contents.lr"), "w", encoding="utf-8"
    ) as f:
        f.write("_model: mymodel\n" "---\n" "title: My Test Object\n")
    for record in children_records_data:
        os.mkdir(os.path.join(tree, "content", "myobj", record["id"]))
        with open(
            os.path.join(tree, "content", "myobj", record["id"], "contents.lr"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "_model: mychildmodel\n"
                "---\n"
                "title: %s\n"
                "---\n"
                "pub_date: %s" % (record["title"], record["pub_date"])
            )


@pytest.fixture
def scratch_client(scratch_env, scratch_project):
    webadmin = WebAdmin(scratch_env, output_path=scratch_project.tree)
    with webadmin.test_client() as client:
        yield client


@pytest.fixture
def scratch_content_path(scratch_project):
    return Path(scratch_project.tree) / "content"


@pytest.fixture(scope="session")
def project_path():
    return Path(__file__).parent / "demo-project"


@pytest.fixture(scope="session")
def webadmin(tmp_path_factory, project_path):
    project = Project.from_path(project_path)
    env = Environment(project, load_plugins=False)
    app = WebAdmin(env, output_path=tmp_path_factory.mktemp("webadmin-output"))
    builder = app.lektor_info.get_builder()
    builder.update_all_source_infos()
    return app


@pytest.fixture
def test_client(webadmin):
    with webadmin.test_client() as client:
        yield client


def test_children_sorting_via_api(scratch_client, children_records_data):
    data = json.loads(scratch_client.get("/admin/api/recordinfo?path=/myobj").data)
    children_records_ids_provided_by_api = list(map(itemgetter("id"), data["children"]))

    records_ordered_by_title = sorted(children_records_data, key=itemgetter("title"))
    ordered_records = sorted(
        records_ordered_by_title, key=itemgetter("pub_date"), reverse=True
    )

    assert (
        list(map(itemgetter("id"), ordered_records))
        == children_records_ids_provided_by_api
    )


def test_recordinfo_children_sort_limited_alts(project, env):
    # This excercises the bug described in #962, namely that
    # if a page has a child that only has content in a subset of the
    # configured alts, get_record_info throws an exception.
    webadmin = WebAdmin(env, output_path=project.tree)
    data = json.loads(
        webadmin.test_client().get("/admin/api/recordinfo?path=/projects").data
    )
    child_data = data["children"]
    assert list(sorted(child_data, key=itemgetter("label"))) == child_data


def test_eventstream_yield_bytes():
    count = 0

    @eventstream
    def testfunc():
        yield "string"
        yield 5

    for data in testfunc().response:  # pylint: disable=no-member
        count += 1
        assert isinstance(data, bytes)
    assert count >= 2


def test_recordinfo(test_client):
    resp = test_client.get("/admin/api/recordinfo?path=%2F")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(att["id"] == "hello.txt" for att in data["attachments"])
    assert any(page["id"] == "blog" for page in data["children"])
    assert any(alt["alt"] == "de" for alt in data["alts"])


def test_recordinfo_invalid_params(test_client):
    resp = test_client.get("/admin/api/recordinfo?notpath=%2Fmyobj")
    assert resp.status_code == 400
    rv = resp.get_json()
    assert rv["error"]["title"] == "Invalid parameters"
    assert "path" in rv["error"]["messages"]


def test_delete_field(scratch_client, scratch_content_path):
    # None in page data means to delete the field
    # Test that that works
    contents_lr = scratch_content_path / "contents.lr"

    assert "\nbody:" in contents_lr.read_text()
    resp = scratch_client.put(
        "/admin/api/rawrecord?path=%2F", json={"path": "/", "data": {"body": None}}
    )
    assert resp.status_code == 200
    assert "\nbody:" not in contents_lr.read_text()


def test_get_path_info(test_client):
    resp = test_client.get("/admin/api/pathinfo?path=%2Fblog%2Fpost2")
    assert resp.get_json() == {
        "segments": [
            {
                "can_have_children": True,
                "exists": True,
                "id": "",
                "label_i18n": {"en": "Welcome"},
                "path": "/",
            },
            {
                "can_have_children": True,
                "exists": True,
                "id": "blog",
                "label_i18n": {"en": "Blog"},
                "path": "/blog",
            },
            {
                "can_have_children": True,
                "exists": True,
                "id": "post2",
                "label_i18n": {"en": "Post 2"},
                "path": "/blog/post2",
            },
        ],
    }


@pytest.mark.parametrize(
    "path, expect",
    [
        (
            "/blog/post1/hello.txt",
            {
                "exists": True,
                "url": "/blog/2015/12/post1/hello.txt",
                "is_hidden": False,
            },
        ),
        (
            "/extra/container",
            {
                "exists": True,
                "url": "/extra/container/",
                "is_hidden": True,
            },
        ),
        (
            "/missing",
            {
                "exists": False,
                "url": None,
                "is_hidden": True,
            },
        ),
    ],
)
def test_previewinfo(test_client, path, expect):
    resp = test_client.get(f"/admin/api/previewinfo?{urlencode({'path': path})}")
    assert resp.status_code == 200
    assert resp.get_json() == expect


@pytest.mark.parametrize("use_json", [True, False])
def test_find(test_client, use_json):
    # Test that we can pass params in JSON body, rather than in the query
    params = {"q": "hello", "alt": "_primary", "lang": "en"}
    if use_json:
        resp = test_client.post("/admin/api/find", json=params)
    else:
        resp = test_client.post(f"/admin/api/find?{urlencode(params)}")
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert any(result["title"] == "Hello" for result in results)
    assert len(results) == 1


@pytest.mark.parametrize(
    "path, alt, srcfile",
    [
        ("/projects/bagpipe", "de", "projects/bagpipe/contents+de.lr"),
        ("/hello.txt", "de", "hello.txt"),
    ],
)
def test_browsefs(test_client, mocker, project_path, path, alt, srcfile):
    mocker.patch("click.launch")
    params = {"path": path, "alt": alt}
    resp = test_client.post("/admin/api/browsefs", json=params)
    assert resp.status_code == 200
    assert resp.get_json()["okay"]
    assert click.launch.mock_calls == [
        mocker.call(str(project_path / "content" / srcfile), locate=True),
    ]


@pytest.mark.parametrize(
    "path, alt, can_have_children",
    [
        ("/test.jpg", "de", False),
        ("/projects", "de", True),
    ],
)
def test_get_new_record_info(test_client, path, alt, can_have_children):
    params = {"path": path, "alt": alt}
    resp = test_client.get(f"/admin/api/newrecord?{urlencode(params)}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["can_have_children"] is bool(can_have_children)


@pytest.mark.parametrize(
    "path, alt, can_upload",
    [
        ("/test.jpg", "de", False),
        ("/projects", "de", True),
    ],
)
def test_get_new_attachment_info(test_client, path, alt, can_upload):
    params = {"path": path}
    resp = test_client.get(f"/admin/api/newattachment?{urlencode(params)}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["can_upload"] is bool(can_upload)


def test_upload_new_attachment(scratch_client, scratch_content_path):
    params = {
        "path": "/myobj",
        "file": (BytesIO(b"foo data"), "foo.txt"),
    }
    resp = scratch_client.post("/admin/api/newattachment", data=params)
    assert resp.status_code == 200
    assert not resp.get_json()["bad_upload"]
    dstpath = scratch_content_path / "myobj/foo.txt"
    assert dstpath.read_bytes() == b"foo data"


@pytest.mark.parametrize(
    "path, alt",
    [
        ("/test.txt", PRIMARY_ALT),
        ("/missing", PRIMARY_ALT),
        ("/missing", "de"),
    ],
)
def test_upload_new_attachment_failure(scratch_client, scratch_content_path, path, alt):
    scratch_content_path.joinpath("test.txt").write_bytes(b"test")
    params = {
        "path": path,
        "alt": alt,
        "file": (BytesIO(b"foo data"), "foo.txt"),
    }
    resp = scratch_client.post("/admin/api/newattachment", data=params)
    assert resp.status_code == 200
    assert resp.get_json()["bad_upload"]
    dstpath = scratch_content_path / "test.txt/foo.txt"
    assert not dstpath.exists()


@pytest.mark.parametrize(
    "path, id, expect, creates",
    [
        (
            "/myobj",
            "new",
            {"valid_id": True, "exists": False, "path": "/myobj/new"},
            "myobj/new/contents.lr",
        ),
        ("/myobj", ".new", {"valid_id": False, "exists": False, "path": None}, None),
        ("/", "myobj", {"valid_id": True, "exists": True, "path": "/myobj"}, None),
    ],
)
def test_add_new_record(
    scratch_client, scratch_content_path, path, id, expect, creates
):
    params = {"path": path, "id": id, "data": {}}
    resp = scratch_client.post("/admin/api/newrecord", json=params)
    assert resp.status_code == 200
    assert resp.get_json() == expect
    if creates is not None:
        dstpath = scratch_content_path / creates
        assert dstpath.exists()


def test_delete_record(scratch_client, scratch_content_path):
    dstfile = scratch_content_path / "myobj/contents.lr"
    assert dstfile.exists()
    params = {"path": "/myobj", "delete_master": "1"}
    resp = scratch_client.post("/admin/api/deleterecord", json=params)
    assert resp.status_code == 200
    assert resp.get_json()["okay"]
    assert not dstfile.exists()


@pytest.mark.parametrize(
    "url_path, expect",
    [
        (
            "/blog/2015/12/post1/hello.txt",
            {
                "exists": True,
                "path": "/blog/post1/hello.txt",
                "alt": PRIMARY_ALT,
            },
        ),
        (
            "/missing",
            {
                "exists": False,
                "path": None,
                "alt": None,
            },
        ),
    ],
)
def test_match_url(test_client, url_path, expect):
    params = {"url_path": url_path}
    resp = test_client.get(f"/admin/api/matchurl?{urlencode(params)}")
    assert resp.status_code == 200
    assert resp.get_json() == expect


def test_get_raw_records(test_client):
    resp = test_client.get("/admin/api/rawrecord?path=%2F")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["title"] == "Welcome"
    assert "datamodel" in data


def test_servers(test_client):
    resp = test_client.get("/admin/api/servers")
    assert resp.status_code == 200
    assert any(server["id"] == "production" for server in resp.get_json()["servers"])


def test_build(test_client, webadmin, mocker):
    builder = mocker.patch.object(webadmin.lektor_info, "get_builder").return_value
    resp = test_client.post("/admin/api/build")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["okay"]
    assert builder.mock_calls == [
        mocker.call.build_all(),
        mocker.call.prune(),
    ]


def test_clean(test_client, webadmin, mocker):
    builder = mocker.patch.object(webadmin.lektor_info, "get_builder").return_value
    resp = test_client.post("/admin/api/clean")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["okay"]
    assert mocker.call.prune(all=True) in builder.mock_calls


def test_publish(test_client, mocker):
    def dummy_publish(env, target, output_path, credentials=None, **extra):
        yield "line1"
        raise PublishError("wups")

    mocker.patch("lektor.admin.modules.api.publish", side_effect=dummy_publish)

    # FIXME: should require POST
    resp = test_client.get("/admin/api/publish?server=production")
    assert resp.status_code == 200
    assert list(resp.response) == [
        b'data: {"msg": "line1"}\n\n',
        b'data: {"msg": "Error: wups"}\n\n',
        b"data: null\n\n",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"server": "bogus"},
        {},
    ],
)
def test_publish_bad_params(test_client, params):
    # FIXME: should require POST
    resp = test_client.get(f"/admin/api/publish?{urlencode(params)}")
    assert resp.status_code == 400
    assert "server" in resp.get_json()["error"]["messages"]


def test_ping(test_client):
    resp = test_client.get("/admin/api/ping")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["okay"]
