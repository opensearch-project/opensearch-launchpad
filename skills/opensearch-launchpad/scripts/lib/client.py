"""OpenSearch client creation, connectivity checks, and Docker bootstrap."""

import os
import platform
import re
import shutil
import subprocess
import sys
import time

from opensearchpy import OpenSearch

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_DEFAULT_USER = "admin"
OPENSEARCH_DEFAULT_PASSWORD = "myStrongPassword123!"
OPENSEARCH_DOCKER_IMAGE = os.getenv(
    "OPENSEARCH_DOCKER_IMAGE", "opensearchproject/opensearch:latest"
)
OPENSEARCH_DOCKER_CONTAINER = os.getenv("OPENSEARCH_DOCKER_CONTAINER", "opensearch-local")
OPENSEARCH_DOCKER_START_TIMEOUT = int(os.getenv("OPENSEARCH_DOCKER_START_TIMEOUT", "120"))

_AUTH_FAILURE_TOKENS = (
    "401", "403", "unauthorized", "forbidden",
    "authentication", "security_exception",
    "missing authentication credentials",
)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split())


def resolve_http_auth() -> tuple[str, str] | None:
    mode = os.getenv("OPENSEARCH_AUTH_MODE", "default").strip().lower()
    if mode == "none":
        return None
    if mode == "custom":
        user = os.getenv("OPENSEARCH_USER", "").strip()
        password = os.getenv("OPENSEARCH_PASSWORD", "").strip()
        if not user or not password:
            raise RuntimeError(
                "OPENSEARCH_AUTH_MODE=custom requires OPENSEARCH_USER and OPENSEARCH_PASSWORD."
            )
        return user, password
    return OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD


def build_client(use_ssl: bool, http_auth: tuple[str, str] | None = None) -> OpenSearch:
    kwargs = {
        "hosts": [{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        "use_ssl": use_ssl,
        "verify_certs": False,
        "ssl_show_warn": False,
    }
    if http_auth is not None:
        kwargs["http_auth"] = http_auth
    return OpenSearch(**kwargs)


def can_connect(client: OpenSearch) -> tuple[bool, bool]:
    try:
        client.info()
        return True, False
    except Exception as e:
        lowered = normalize_text(e).lower()
        if "404" in lowered or "notfounderror" in lowered:
            try:
                client.cat.indices(format="json")
                return True, False
            except Exception:
                pass
            try:
                client.search(index="*", body={"size": 0}, params={"timeout": "5s"})
                return True, False
            except Exception as se:
                sl = normalize_text(se).lower()
                if "403" in sl or "forbidden" in sl:
                    return True, False
        auth_failure = any(t in lowered for t in _AUTH_FAILURE_TOKENS)
        return False, auth_failure


def _resolve_docker() -> str:
    system = platform.system().lower()
    candidates = {
        "darwin": [
            "/usr/local/bin/docker",
            "/opt/homebrew/bin/docker",
            "/Applications/Docker.app/Contents/Resources/bin/docker",
        ],
        "linux": ["/usr/bin/docker", "/usr/local/bin/docker", "/snap/bin/docker"],
    }.get(system, [])

    from_env = os.getenv("OPENSEARCH_DOCKER_CLI_PATH", "").strip()
    if from_env:
        candidates.insert(0, from_env)

    from_path = shutil.which("docker")
    if from_path:
        candidates.insert(0, from_path)

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    raise RuntimeError(
        "Docker CLI not found. Install Docker or set OPENSEARCH_DOCKER_CLI_PATH."
    )


def _run_docker(command: list[str]) -> subprocess.CompletedProcess:
    docker = _resolve_docker()
    return subprocess.run(
        [docker] + command,
        capture_output=True, text=True, timeout=60,
    )


def _start_local_container() -> None:
    result = _run_docker(["ps", "--format", "{{.Names}}"])
    if OPENSEARCH_DOCKER_CONTAINER in (result.stdout or "").split():
        print(f"Container '{OPENSEARCH_DOCKER_CONTAINER}' already running.", file=sys.stderr)
        return

    _run_docker(["rm", "-f", OPENSEARCH_DOCKER_CONTAINER])

    password = os.getenv("OPENSEARCH_PASSWORD", OPENSEARCH_DEFAULT_PASSWORD).strip() or OPENSEARCH_DEFAULT_PASSWORD
    print(f"Starting OpenSearch container '{OPENSEARCH_DOCKER_CONTAINER}'...", file=sys.stderr)
    result = _run_docker([
        "run", "-d",
        "--name", OPENSEARCH_DOCKER_CONTAINER,
        "-p", f"{OPENSEARCH_PORT}:9200",
        "-p", "9600:9600",
        "-e", "discovery.type=single-node",
        "-e", "DISABLE_SECURITY_PLUGIN=true",
        "-e", f"OPENSEARCH_INITIAL_ADMIN_PASSWORD={password}",
        OPENSEARCH_DOCKER_IMAGE,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container: {result.stderr}")


def _wait_for_cluster() -> OpenSearch:
    http_auth = resolve_http_auth()
    secure = build_client(use_ssl=True, http_auth=http_auth)
    insecure = build_client(use_ssl=False, http_auth=http_auth)
    deadline = time.time() + OPENSEARCH_DOCKER_START_TIMEOUT

    while time.time() < deadline:
        ok, _ = can_connect(secure)
        if ok:
            return secure
        ok, _ = can_connect(insecure)
        if ok:
            return insecure
        time.sleep(2)

    raise RuntimeError(
        f"OpenSearch did not become ready within {OPENSEARCH_DOCKER_START_TIMEOUT}s."
    )


def create_client() -> OpenSearch:
    http_auth = resolve_http_auth()

    secure = build_client(use_ssl=True, http_auth=http_auth)
    ok, _ = can_connect(secure)
    if ok:
        return secure

    insecure = build_client(use_ssl=False, http_auth=http_auth)
    ok, auth_fail = can_connect(insecure)
    if ok:
        return insecure

    if auth_fail:
        raise RuntimeError(
            f"Authentication failed connecting to OpenSearch at {OPENSEARCH_HOST}:{OPENSEARCH_PORT}."
        )

    _start_local_container()
    return _wait_for_cluster()


def create_remote_client(
    endpoint: str,
    port: int = 443,
    use_ssl: bool = True,
    username: str = "",
    password: str = "",
    aws_region: str = "",
    aws_service: str = "",
) -> OpenSearch:
    kwargs: dict = {
        "hosts": [{"host": endpoint, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": use_ssl,
        "ssl_show_warn": False,
    }

    if aws_region and aws_service:
        import boto3
        from opensearchpy import AWSV4SignerAuth, RequestsHttpConnection
        session = boto3.Session()
        credentials = session.get_credentials()
        kwargs["http_auth"] = AWSV4SignerAuth(credentials, aws_region, aws_service)
        kwargs["connection_class"] = RequestsHttpConnection
    elif username and password:
        kwargs["http_auth"] = (username, password)

    return OpenSearch(**kwargs)
