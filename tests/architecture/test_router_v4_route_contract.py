from packages.document_routing import MultiSignalRoute


def test_unknown_structured_is_a_distinct_first_class_route():
    assert MultiSignalRoute.UNKNOWN_STRUCTURED.value == "UNKNOWN_STRUCTURED"
    assert MultiSignalRoute.UNKNOWN_STRUCTURED is not MultiSignalRoute.UNKNOWN_UNSTRUCTURED


def test_router_v4_is_disabled_by_default():
    from packages.settings import Settings
    assert Settings().enable_router_v4 is False

