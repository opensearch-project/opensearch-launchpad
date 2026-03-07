from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opensearch_launchpad.opensearch_ops_tools as tools


class _FakeIndices:
    def __init__(self, index_exists=False):
        self._index_exists = index_exists
        self.created = []
        self.deleted = []
        self.settings = []

    def exists(self, index):
        return self._index_exists

    def create(self, index, body):
        if self._index_exists:
            raise Exception("resource_already_exists_exception")
        self.created.append((index, body))
        self._index_exists = True

    def delete(self, index, ignore=None):
        self.deleted.append((index, tuple(ignore or [])))
        self._index_exists = False

    def get_mapping(self, index):
        return {
            index: {
                "mappings": {
                    "properties": {
                        "title": {"type": "text"},
                        "isAdult": {"type": "keyword"},
                    }
                }
            }
        }

    def put_settings(self, index, body):
        self.settings.append((index, body))


class _FakeIngest:
    def __init__(self, existing_pipeline_name=""):
        self._pipelines = {}
        if existing_pipeline_name:
            self._pipelines[existing_pipeline_name] = {"processors": []}
        self.deleted = []
        self.puts = []

    def get_pipeline(self, id):
        if id in self._pipelines:
            return {id: self._pipelines[id]}
        raise Exception("404")

    def delete_pipeline(self, id):
        self.deleted.append(id)
        self._pipelines.pop(id, None)

    def put_pipeline(self, id, body):
        self.puts.append((id, body))
        self._pipelines[id] = body


class _FakeTransport:
    def __init__(self, existing_search_pipeline_name=""):
        self.requests = []
        self._search_pipelines = {}
        if existing_search_pipeline_name:
            self._search_pipelines[existing_search_pipeline_name] = {"phase_results_processors": []}

    def perform_request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if path.startswith("/_search/pipeline/"):
            pipeline_name = path.rsplit("/", 1)[-1]
            if method == "GET":
                if pipeline_name in self._search_pipelines:
                    return {pipeline_name: self._search_pipelines[pipeline_name]}
                raise Exception("404")
            if method == "DELETE":
                self._search_pipelines.pop(pipeline_name, None)
                return {}
            if method == "PUT":
                self._search_pipelines[pipeline_name] = body
                return {}
        return {}


class _FakeClient:
    def __init__(self, index_exists=False, existing_pipeline_name="", existing_search_pipeline_name=""):
        self.indices = _FakeIndices(index_exists=index_exists)
        self.ingest = _FakeIngest(existing_pipeline_name=existing_pipeline_name)
        self.transport = _FakeTransport(existing_search_pipeline_name=existing_search_pipeline_name)


def _create_body(field_type):
    return {
        "mappings": {
            "properties": {
                "isAdult": {"type": field_type},
                "title": {"type": "text"},
            }
        }
    }


def test_create_index_recreates_when_replace_enabled(monkeypatch):
    fake_client = _FakeClient(index_exists=True)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)
    monkeypatch.setattr(
        tools,
        "get_sample_docs_payload",
        lambda limit=200, sample_doc_json="", source_local_file="": [{"isAdult": "0", "title": "Carmencita"}],
    )

    response = tools.create_index("imdb_titles", _create_body("keyword"), replace_if_exists=True)

    assert "recreated successfully" in response.lower()
    assert fake_client.indices.deleted
    assert fake_client.indices.created


def test_create_and_attach_pipeline_recreates_and_reattaches_ingest(monkeypatch):
    fake_client = _FakeClient(index_exists=False, existing_pipeline_name="imdb_pipeline")
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_pipeline",
        pipeline_body={
            "processors": [
                {
                    "text_embedding": {
                        "model_id": "test-model-id",
                        "field_map": {"title": "title_vector"},
                    }
                }
            ]
        },
        index_name="imdb_titles",
        pipeline_type="ingest",
        replace_if_exists=True,
    )

    lowered = response.lower()
    assert "recreated and attached" in lowered
    assert fake_client.ingest.deleted == ["imdb_pipeline"]
    assert fake_client.ingest.puts
    assert fake_client.indices.settings
    assert fake_client.indices.settings[-1][1] == {"index.default_pipeline": "imdb_pipeline"}


def test_create_and_attach_pipeline_builds_default_hybrid_search_pipeline(monkeypatch):
    fake_client = _FakeClient(index_exists=False)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_hybrid_search_pipeline",
        index_name="imdb_titles",
        pipeline_type="search",
        is_hybrid_search=True,
        hybrid_weights=[0.2, 0.8],
        replace_if_exists=True,
    )

    lowered = response.lower()
    assert "created and attached" in lowered
    assert fake_client.indices.settings
    assert fake_client.indices.settings[-1][1] == {
        "index.search.default_pipeline": "imdb_hybrid_search_pipeline"
    }
    put_requests = [
        item for item in fake_client.transport.requests
        if item[0] == "PUT" and item[1] == "/_search/pipeline/imdb_hybrid_search_pipeline"
    ]
    assert put_requests
    body = put_requests[-1][2]
    assert body["phase_results_processors"][0]["normalization-processor"]["normalization"]["technique"] == "min_max"
    assert body["phase_results_processors"][0]["normalization-processor"]["combination"]["technique"] == "arithmetic_mean"
    assert body["phase_results_processors"][0]["normalization-processor"]["combination"]["parameters"]["weights"] == [0.2, 0.8]


def test_create_and_attach_pipeline_accepts_body_alias_for_hybrid_search(monkeypatch):
    fake_client = _FakeClient(index_exists=False)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_hybrid_search_pipeline_alias",
        body={},
        index_name="imdb_titles",
        pipeline_type="search",
        is_hybrid_search=True,
        hybrid_weights=[0.4, 0.6],
        replace_if_exists=True,
    )

    lowered = response.lower()
    assert "created and attached" in lowered
    put_requests = [
        item for item in fake_client.transport.requests
        if item[0] == "PUT" and item[1] == "/_search/pipeline/imdb_hybrid_search_pipeline_alias"
    ]
    assert put_requests
    body = put_requests[-1][2]
    assert body["phase_results_processors"][0]["normalization-processor"]["combination"]["parameters"]["weights"] == [0.4, 0.6]


def test_create_and_attach_pipeline_rejects_missing_ingest_body(monkeypatch):
    fake_client = _FakeClient(index_exists=False)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_ingest_pipeline",
        index_name="imdb_titles",
        pipeline_type="ingest",
        replace_if_exists=True,
    )

    assert "pipeline_body is required for ingest pipelines" in response


def test_create_and_attach_pipeline_rejects_invalid_hybrid_search_pipeline_body(monkeypatch):
    fake_client = _FakeClient(index_exists=False)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_hybrid_search_pipeline",
        pipeline_body={"description": "missing normalization processor"},
        index_name="imdb_titles",
        pipeline_type="search",
        is_hybrid_search=True,
        hybrid_weights=[0.5, 0.5],
        replace_if_exists=True,
    )

    assert "normalization-processor" in response


def test_create_and_attach_pipeline_passes_through_non_hybrid_search_pipeline(monkeypatch):
    fake_client = _FakeClient(index_exists=False)
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)
    custom_body = {
        "phase_results_processors": [
            {"custom-processor": {"some": "value"}}
        ]
    }

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_custom_search_pipeline",
        pipeline_body=custom_body,
        index_name="imdb_titles",
        pipeline_type="search",
        is_hybrid_search=False,
        replace_if_exists=True,
    )

    lowered = response.lower()
    assert "created and attached" in lowered
    put_requests = [
        item for item in fake_client.transport.requests
        if item[0] == "PUT" and item[1] == "/_search/pipeline/imdb_custom_search_pipeline"
    ]
    assert put_requests
    assert put_requests[-1][2] == custom_body


def test_create_and_attach_pipeline_recreates_and_reattaches_search(monkeypatch):
    fake_client = _FakeClient(index_exists=False, existing_search_pipeline_name="imdb_search_pipeline")
    monkeypatch.setattr(tools, "_create_client", lambda: fake_client)

    response = tools.create_and_attach_pipeline(
        pipeline_name="imdb_search_pipeline",
        pipeline_body={"phase_results_processors": []},
        index_name="imdb_titles",
        pipeline_type="search",
        is_hybrid_search=False,
        replace_if_exists=True,
    )

    lowered = response.lower()
    assert "recreated and attached" in lowered
    assert ("DELETE", "/_search/pipeline/imdb_search_pipeline", None) in fake_client.transport.requests
    assert any(
        req[0] == "PUT" and req[1] == "/_search/pipeline/imdb_search_pipeline"
        for req in fake_client.transport.requests
    )
    assert fake_client.indices.settings
    assert fake_client.indices.settings[-1][1] == {"index.search.default_pipeline": "imdb_search_pipeline"}
