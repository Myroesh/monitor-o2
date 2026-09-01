"""Integration tests for monitor page routes."""


class TestMonitorRoutes:
    def test_monitor_returns_200(self, client):
        response = client.get("/monitor/")
        assert response.status_code == 200

    def test_monitor_contains_heading(self, client):
        response = client.get("/monitor/")
        assert b"Monitor en tiempo real" in response.data

    def test_root_redirects_to_monitor(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert "/monitor" in response.headers["Location"]

    def test_root_redirect_follows_to_200(self, client):
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200
        assert b"Monitor en tiempo real" in response.data

    def test_monitor_page_loads_chart_script(self, client):
        response = client.get("/monitor/")
        assert b"chart.min.js" in response.data

    def test_monitor_page_loads_monitor_script(self, client):
        response = client.get("/monitor/")
        assert b"monitor.js" in response.data

    def test_old_monitor_api_path_not_found(self, client):
        """The API must NOT be reachable under /monitor/api/telemetry."""
        response = client.get("/monitor/api/telemetry")
        assert response.status_code == 404

    def test_monitor_page_contains_all_three_chart_canvases(self, client):
        response = client.get("/monitor/")
        assert b'id="pressure-chart"' in response.data
        assert b'id="o2-chart"' in response.data
        assert b'id="flow-chart"' in response.data
