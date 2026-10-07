from gbox.tools import _vtt_text


def test_vtt_rolling_auto_captions():
    v = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n\n"
         "00:00:02.500 --> 00:00:04.000\nhello there\n<c>general</c> kenobi\n\n01:02.000 --> 01:04.000\nbye")
    r = _vtt_text(v)
    assert [x["text"] for x in r] == ["hello there", "general kenobi", "bye"] and r[2]["t"] == 62.0
