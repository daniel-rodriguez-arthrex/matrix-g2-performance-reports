import re

path = "core/matrix_client.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

old_init = """        self.passcode = passcode
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = False"""
new_init = """        self.passcode = passcode
        self.token: Optional[str] = None  # deprecated
        self.access_token: Optional[str] = None  # room/pair token for read endpoints
        self.auth_token: Optional[str] = None    # admin token from getAuthToken
        self.session = requests.Session()
        self.session.verify = False"""
text = text.replace(old_init, new_init)

old_auth = """    def authenticate(self, pair_key: Optional[str] = None) -> str:
        \"\"\"Authenticate and return an access token.

        Prefers the admin getAuthToken endpoint (used by the app for
        state-changing actions), falling back to legacy login or room pairing.
        \"\"\"
        # Try admin auth first (required for state-changing POST endpoints)
        if self.username and self.password:
            try:
                response = self.session.post(
                    self._url("api/app/getAuthToken"),
                    json={"username": self.username, "password": self.password},
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                self.token = data.get("token") or data.get("accessToken")
                if self.token:
                    return self.token
            except Exception:
                pass

        # Fallback to legacy login
        try:
            response = self.session.post(
                self._url("api/auth/login"),
                json={"username": self.username, "password": self.password},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("token") or data.get("accessToken")
            if self.token:
                return self.token
        except Exception:
            pass

        # Last resort: room pairing token (read-only access for many endpoints)
        pair_key = pair_key or self.passcode or self.room_id
        if pair_key:
            response = self.session.post(
                self._url("api/app/getAccessToken"),
                json={"pairKey": pair_key, "pairHash": "", "roomUrl": self.base_url},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("accessToken") or data.get("token")
            return self.token

        return self.token"""
new_auth = """    def authenticate(self, pair_key: Optional[str] = None) -> str:
        \"\"\"Authenticate and obtain both room access token and admin auth token.

        The app uses two JWT tokens: a room access token (from getAccessToken)
        for read endpoints and an admin token (from getAuthToken) for state-
        changing POST endpoints.
        \"\"\"
        # 1) Room pair token (for GET /api/devices/displays, etc.)
        pair_key = pair_key or self.passcode or self.room_id
        if pair_key:
            try:
                response = self.session.post(
                    self._url("api/app/getAccessToken"),
                    json={"pairKey": pair_key, "pairHash": "", "roomUrl": self.base_url},
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                self.access_token = data.get("accessToken") or data.get("token")
            except Exception:
                pass

        # 2) Admin auth token (for POST /api/room/route, /api/devices/.../changeLayout, etc.)
        if self.username and self.password:
            try:
                response = self.session.post(
                    self._url("api/app/getAuthToken"),
                    json={"username": self.username, "password": self.password},
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                self.auth_token = data.get("token") or data.get("accessToken")
            except Exception:
                pass

            # Fallback legacy login
            if not self.auth_token:
                try:
                    response = self.session.post(
                        self._url("api/auth/login"),
                        json={"username": self.username, "password": self.password},
                        timeout=30,
                    )
                    response.raise_for_status()
                    data = response.json()
                    self.auth_token = data.get("token") or data.get("accessToken")
                except Exception:
                    pass

        # Backwards compatibility: prefer admin token, then access token
        self.token = self.auth_token or self.access_token
        return self.token"""
text = text.replace(old_auth, new_auth)

old_headers = """    def headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers"""
new_headers = """    def headers(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers"""
text = text.replace(old_headers, new_headers)

old_get = """    def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        response = self.session.get(
            self._url(path), headers=self.headers(), timeout=30, **kwargs
        )
        response.raise_for_status()
        return response.json()"""
new_get = """    def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        token = self.access_token or self.auth_token or self.token
        response = self.session.get(
            self._url(path), headers=self.headers(token), timeout=30, **kwargs
        )
        response.raise_for_status()
        return response.json()"""
text = text.replace(old_get, new_get)

old_post = """    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.post(
            self._url(path), json=payload, headers=self.headers(), timeout=30
        )
        response.raise_for_status()
        return response.json()"""
new_post = """    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = self.auth_token or self.access_token or self.token
        response = self.session.post(
            self._url(path), json=payload, headers=self.headers(token), timeout=30
        )
        response.raise_for_status()
        return response.json()"""
text = text.replace(old_post, new_post)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("patched matrix_client.py")
