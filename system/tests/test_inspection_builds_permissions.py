"""The inspection_builds wrapper only issues HTTP GET/POST to the local control
plane; the actual ROM rebuild runs through the characters tool (P.EXECUTE).
It must not demand P.FILE_MUTATION, which the operator's granted_permissions
does not include and which the build itself does not require."""

from gbox.models import Permission as P


def test_inspection_builds_permissions_match_the_build_tool():
    import gbox.inspection_builds  # noqa: F401  (registers the tool)
    from gbox.registry import REGISTRY

    info = REGISTRY["inspection_builds"].info()
    perms = {p.value for p in info.permissions}
    assert P.EXECUTE.value in perms, "inspection_builds must be runnable with the granted execute permission"
    assert P.FILE_MUTATION.value not in perms, "inspection_builds must not demand an ungranted file_mutation gate"
