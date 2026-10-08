import base64

from fastapi.testclient import TestClient

from gbox.server import create_app


def test_issue_keeps_subject_details_and_arbitrary_attachment_bytes(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    files = [
        ("steps.md", "text/markdown", "# Reproduction\nMove the stick up.\n".encode()),
        ("capture.png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("save.bin", "application/octet-stream", bytes([0, 255, 1, 128, 0])),
    ]
    response = client.post("/api/requests/issue", json={
        "title": "Movement is reversed", "what": "Report issue (Capture icon)",
        "note": "Moving up makes the character run down.",
        "attachments": [{"name": name, "type": kind, "b64": base64.b64encode(data).decode()}
                        for name, kind, data in files],
    })
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["title"] == "Movement is reversed"
    assert "Moving up makes the character run down." in report["body"]
    attachments = report["messages"][0]["attachments"]
    assert len(attachments) == len(files)
    for attachment, (name, kind, original) in zip(attachments, files):
        assert (attachment["name"], attachment["type"]) == (name, kind)
        downloaded = client.get(f"/api/artifacts/{attachment['sha256']}")
        assert downloaded.status_code == 200
        assert downloaded.content == original
