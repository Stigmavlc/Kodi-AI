import json
import pytest


def test_flat_id_parser_settings_xml():
    from lib.tools.extract_keys import flat_id_parser
    xml = b'<?xml version="1.0"?><settings><setting id="a" value="1"/><setting id="b" value="2"/></settings>'
    out = flat_id_parser(xml)
    assert out == {"a": "1", "b": "2"}


def test_path_flatten_advancedsettings():
    from lib.tools.extract_keys import path_flatten_parser
    xml = b'<advancedsettings><network><buffermode>1</buffermode></network></advancedsettings>'
    out = path_flatten_parser(xml)
    assert out["advancedsettings/network/buffermode"] == "1"


def test_path_flatten_with_repeated_sibling_indexing():
    from lib.tools.extract_keys import path_flatten_parser
    xml = (
        b'<sources><video>'
        b'<source><name>Movies</name><path>/mnt/a</path></source>'
        b'<source><name>TV</name><path>/mnt/b</path></source>'
        b'</video></sources>'
    )
    out = path_flatten_parser(xml)
    assert out["sources/video/source[0]/name"] == "Movies"
    assert out["sources/video/source[0]/path"] == "/mnt/a"
    assert out["sources/video/source[1]/name"] == "TV"
    assert out["sources/video/source[1]/path"] == "/mnt/b"


def test_json_walker():
    from lib.tools.extract_keys import json_walker
    raw = json.dumps({"a": {"b": 1, "c": [10, 20]}}).encode()
    out = json_walker(raw)
    assert out["a.b"] == 1
    assert out["a.c[0]"] == 10
    assert out["a.c[1]"] == 20


def test_parser_for_path_dispatch():
    from lib.tools.extract_keys import parser_for_path
    assert parser_for_path("/x/settings.xml").__name__ == "flat_id_parser"
    assert parser_for_path("/x/advancedsettings.xml").__name__ == "path_flatten_parser"
    assert parser_for_path("/x/config.json").__name__ == "json_walker"
    assert parser_for_path("/x/binary.bin") is None
