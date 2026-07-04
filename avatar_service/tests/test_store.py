from avatar_service.store import JobStore, AssetStore


def test_jobstore_create_get_update():
    js = JobStore()
    jid = js.create()
    job = js.get(jid)
    assert job["status"] == "pending"
    assert job["job_id"] == jid
    js.update(jid, status="running", progress="generating_image")
    assert js.get(jid)["status"] == "running"
    assert js.get(jid)["progress"] == "generating_image"
    assert js.get("nope") is None


def test_assetstore_save_and_path(tmp_path):
    store = AssetStore(tmp_path)
    fn = store.save("abc", "glb", b"GLBDATA")
    assert fn == "abc.glb"
    assert (tmp_path / "abc.glb").read_bytes() == b"GLBDATA"
    assert store.path("abc.glb") == tmp_path / "abc.glb"
