"""Create the local development tenant and its API key when absent.

This helper is deliberately for local development only. Production tenants and
keys should be provisioned through an administrative workflow, not this module.
"""

from acil.config import get_settings
from acil.db import Base, SessionLocal, engine
from acil.main import bootstrap_dev_data


def main() -> None:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        tenant = bootstrap_dev_data(db)
    print(f"Development tenant ready: {tenant.name}")
    print("API key: configured ACIL_API_KEY (default: acil-dev-key)")


if __name__ == "__main__":
    main()
