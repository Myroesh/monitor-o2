"""Integration tests for configuration routes and /api/config REST API endpoints."""


class TestConfigurationRoutes:
    def test_configuration_returns_200(self, client):
        response = client.get("/configuration/")
        assert response.status_code == 200

    def test_configuration_contains_heading(self, client):
        response = client.get("/configuration/")
        assert "Configuración".encode() in response.data

    def test_configuration_nav_link_present(self, client):
        response = client.get("/configuration/")
        assert b"/configuration" in response.data

    def test_configuration_page_loads_script(self, client):
        response = client.get("/configuration/")
        assert b"configuration.js" in response.data


class TestConfigurationApi:
    def test_get_config_api(self, client):
        res = client.get("/api/config")
        assert res.status_code == 200
        assert res.content_type.startswith("application/json")
        data = res.get_json()
        assert "firmware_version" in data
        assert "gain" in data
        assert "offset" in data
        assert "ratio_ain0" in data

    def test_post_config_api_success(self, client):
        payload = {
            "gain": 1.85,
            "offset": 2.5,
            "rtop_ain0": 30000.0,
            "rbottom_ain0": 10000.0,
        }
        res = client.post("/api/config", json=payload)
        assert res.status_code == 200
        data = res.get_json()
        assert data["gain"] == 1.85
        assert data["offset"] == 2.5
        assert data["rtop_ain0"] == 30000.0
        # 10000 / (30000 + 10000) = 0.25
        assert data["ratio_ain0"] == 0.25

    def test_post_config_api_validation_failure(self, client):
        payload = {"gain": -10.0}
        res = client.post("/api/config", json=payload)
        assert res.status_code == 400
        data = res.get_json()
        assert "error" in data
        assert "GAIN" in data["error"]
