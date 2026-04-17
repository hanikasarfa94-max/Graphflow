from workgraph_worker import boot


def test_worker_boots_cleanly():
    assert boot([]) == 0
