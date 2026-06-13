import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

import src.config as config


def main() -> None:
    original_streamlit = config.st

    try:
        fake_streamlit = SimpleNamespace(
            secrets={
                "environment": {"name": "testing"},
                "database": {
                    "engine": "motherduck",
                    "token": "shared_token",
                },
                "tenants": {
                    "pronto": {
                        "name": "Pronto",
                        "database": "scry_test_pronto",
                    },
                    "client_b": {
                        "name": "Client B",
                        "database": "scry_test_client_b",
                    },
                },
            },
            session_state={},
        )
        config.st = fake_streamlit

        assert config.get_environment_name() == "testing"
        assert config.get_active_tenant_id() == "pronto"
        assert config.get_database_config()["database"] == "scry_test_pronto"
        assert config.get_database_config()["token"] == "shared_token"

        config.set_active_tenant_id("client_b")
        assert config.get_active_tenant_id() == "client_b"
        assert config.get_database_config()["database"] == "scry_test_client_b"

        fake_streamlit.secrets = {
            "database": {
                "engine": "motherduck",
                "token": "shared_token",
            },
            "tenants": {
                "pronto": {
                    "name": "Pronto",
                    "database": {
                        "engine": "motherduck",
                        "database": "scry_prod_pronto",
                        "token": "tenant_token",
                    },
                },
            },
        }
        fake_streamlit.session_state.clear()

        assert config.get_active_tenant_id() == "pronto"
        assert config.get_database_config()["database"] == "scry_prod_pronto"
        assert config.get_database_config()["token"] == "tenant_token"

        print("tenant config smoke passed")
    finally:
        config.st = original_streamlit


if __name__ == "__main__":
    main()
