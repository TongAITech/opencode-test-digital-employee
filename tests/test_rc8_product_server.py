import json
import threading
from urllib.request import urlopen

from rc8_center import CenterControlPlane
from rc8_control.models import ExecutionNode
from rc8_product import ProductApplication
from rc8_product.server import create_server


def _get(url):
    with urlopen(url, timeout=5) as response:
        return response.status, response.headers.get_content_type(), response.read()


def test_product_http_serves_live_node_projection_and_chinese_ui():
    center = CenterControlPlane(offline_after_seconds=300)
    center.register_node(
        ExecutionNode(
            node_id="NODE-HTTP-01",
            display_name="办公电脑-HTTP",
            platform="windows-git-bash",
            architecture="x86_64",
            operator="测试人员甲",
            package_version="rc8-dev",
        ),
        now=100,
    )
    server = create_server(ProductApplication(center), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        status, content_type, body = _get(base + "/api/nodes")
        assert status == 200
        assert content_type == "application/json"
        payload = json.loads(body.decode("utf-8"))
        assert payload["total"] == 1
        assert payload["items"][0]["display_name"] == "办公电脑-HTTP"

        status, content_type, body = _get(base + "/")
        assert status == 200
        assert content_type == "text/html"
        html = body.decode("utf-8")
        assert "节点查询与运行状态" in html
        assert "执行节点" in html
        assert "Dashboard" not in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
