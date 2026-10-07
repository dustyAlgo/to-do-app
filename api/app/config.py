from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All values come from environment variables (see docker-compose.yml / .env.example)."""

    # Browser-facing base URL, e.g. http://13.233.10.20.nip.io (no trailing slash)
    public_base_url: str = "http://localhost"

    # Keycloak
    oidc_realm: str = "todo"
    keycloak_internal_url: str = "http://keycloak:8080/auth"  # server-to-server only
    oidc_client_id: str = "todo-app"
    oidc_client_secret: str = "change-me"
    api_audience: str = "todo-api"

    database_url: str = "sqlite:///./dev.db"
    rust_api_url: str = "http://rust-api:8080"

    # Cookies / timings
    session_cookie_name: str = "todo_session"
    state_cookie_name: str = "todo_oidc_state"
    cookie_secure: bool = False  # TODO: set True once the site is served over HTTPS
    login_state_ttl_seconds: int = 300
    refresh_margin_seconds: int = 30
    jwt_leeway_seconds: int = 30

    # --- derived URLs -------------------------------------------------------
    @property
    def oidc_issuer(self) -> str:
        """Public issuer: must equal the "iss" claim Keycloak puts in tokens (KC_HOSTNAME)."""
        return f"{self.public_base_url}/auth/realms/{self.oidc_realm}"

    @property
    def oidc_auth_url(self) -> str:  # browser
        return f"{self.oidc_issuer}/protocol/openid-connect/auth"

    @property
    def oidc_logout_url(self) -> str:  # browser
        return f"{self.oidc_issuer}/protocol/openid-connect/logout"

    @property
    def _internal_oidc_base(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.oidc_realm}/protocol/openid-connect"

    @property
    def oidc_token_url(self) -> str:  # server-to-server
        return f"{self._internal_oidc_base}/token"

    @property
    def oidc_jwks_url(self) -> str:  # server-to-server
        return f"{self._internal_oidc_base}/certs"

    @property
    def oidc_redirect_uri(self) -> str:
        return f"{self.public_base_url}/api/auth/callback"


settings = Settings()
