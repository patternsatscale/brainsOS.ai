"""AWS ALB OIDC (`x-amzn-oidc-data`) ES256 JWT verification and EBS owner elevation.

Verifies ES256-signed OIDC assertion JWTs injected by an AWS Application Load
Balancer using AWS regional ELB public keys (`public-keys.auth.elb.<region>.amazonaws.com`),
and enforces per-VM EBS owner authorization (`BRAINSOS_USER_SUB`) without requiring
the user to hold global Cognito User Pool admin privileges.
"""

from __future__ import annotations

import os
import re
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import jwt

KID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
AWS_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d+$")
SIGNER_ARN_RE = re.compile(
    r"^arn:aws(?:-us-gov|-cn)?:elasticloadbalancing:([a-z]{2}(?:-[a-z]+)+-\d+):(\d{12}):loadbalancer/app/[^/\s]+/[a-f0-9]+$"
)
SAFE_USER_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")

DEFAULT_KEY_TTL_SECONDS = 3600
_PUBLIC_KEY_CACHE: Dict[Tuple[str, str], Tuple[str, float]] = {}


class AlbAuthError(Exception):
    """Raised when AWS ALB OIDC JWT verification or owner authorization fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_truthy(value: Optional[str], default: bool = False) -> bool:
    """Parse boolean strings consistently across `.env` and HTTP inputs."""
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def is_valid_https_issuer(url: str) -> bool:
    """Return True if `url` is a non-empty https:// URL with a valid hostname and port."""
    clean = (url or "").strip()
    if not clean.startswith("https://") or any(ch.isspace() for ch in clean):
        return False
    try:
        parsed = urlparse(clean)
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc) and bool(host)


def clear_key_cache() -> None:
    """Clear the cached AWS ELB public PEM keys (primarily for tests)."""
    _PUBLIC_KEY_CACHE.clear()


def fetch_alb_public_key(
    region: str,
    kid: str,
    *,
    timeout: float = 3.0,
    ttl_seconds: int = DEFAULT_KEY_TTL_SECONDS,
) -> str:
    """Fetch and cache the AWS ELB ES256 public key PEM for `(region, kid)`.

    Strictly validates `region` and `kid` syntax before constructing the HTTPS URL
    so untrusted JWT headers cannot trigger SSRF or path traversal.
    """
    if not AWS_REGION_RE.match(region):
        raise AlbAuthError(401, "Invalid AWS region in ALB JWT signer ARN")
    if not KID_RE.match(kid):
        raise AlbAuthError(401, "Invalid key ID (kid) in ALB JWT header")

    cache_key = (region, kid)
    now = time.time()
    cached = _PUBLIC_KEY_CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/x-pem-file, text/plain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise AlbAuthError(401, f"Failed retrieving ALB signing key (HTTP {status})")
            pem = resp.read().decode("utf-8", errors="strict").strip()
    except AlbAuthError:
        raise
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise AlbAuthError(503, f"Unable to fetch AWS ALB signing key: {exc}") from exc

    if "-----BEGIN PUBLIC KEY-----" not in pem:
        raise AlbAuthError(401, "Invalid PEM payload returned by AWS ELB key endpoint")

    _PUBLIC_KEY_CACHE[cache_key] = (pem, now + max(60, ttl_seconds))
    return pem


def _parse_claim_groups(claims: Mapping[str, Any]) -> List[str]:
    """Extract Cognito/OIDC groups list cleanly from JWT claims."""
    raw = claims.get("cognito:groups")
    if raw is None:
        raw = claims.get("groups")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in re.split(r"[|,]", raw) if part.strip()]
    return []


def verify_alb_oidc_jwt(
    token: str,
    env: Mapping[str, str],
    *,
    key_fetcher: Optional[Callable[[str, str], str]] = None,
    leeway: int = 30,
) -> Dict[str, Any]:
    """Verify an AWS ALB `x-amzn-oidc-data` ES256 JWT and return decoded claims."""
    if not is_truthy(env.get("AUTH_ALB_OIDC_ENABLED"), default=False):
        raise AlbAuthError(401, "AWS ALB OIDC pass-through is disabled")

    allowed_signers_raw = str(env.get("AUTH_ALB_SIGNER_ARN") or "").strip()
    allowed_signers = [s.strip() for s in allowed_signers_raw.split(",") if s.strip()]
    if not allowed_signers or not all(SIGNER_ARN_RE.match(s) for s in allowed_signers):
        raise AlbAuthError(403, "ALB OIDC signer ARN allowlist (AUTH_ALB_SIGNER_ARN) is not configured")

    required_issuers_raw = str(env.get("AUTH_ALB_ISSUER") or "").strip()
    expected_issuers = [s.strip() for s in required_issuers_raw.split(",") if s.strip()]
    if not expected_issuers or not all(is_valid_https_issuer(iss) for iss in expected_issuers):
        raise AlbAuthError(403, "ALB OIDC issuer allowlist (AUTH_ALB_ISSUER) is not configured")

    clean_token = (token or "").strip()
    if not clean_token:
        raise AlbAuthError(401, "Missing x-amzn-oidc-data header")

    try:
        header = jwt.get_unverified_header(clean_token)
    except jwt.PyJWTError as exc:
        raise AlbAuthError(401, f"Malformed ALB OIDC JWT header: {exc}") from exc

    alg = str(header.get("alg") or "").strip()
    if alg != "ES256":
        raise AlbAuthError(401, f"Unsupported ALB OIDC JWT algorithm '{alg}' (expected ES256)")

    kid = str(header.get("kid") or "").strip()
    if not KID_RE.match(kid):
        raise AlbAuthError(401, "Invalid or missing kid in ALB OIDC JWT header")

    signer = str(header.get("signer") or "").strip()
    signer_match = SIGNER_ARN_RE.match(signer)
    if not signer_match:
        raise AlbAuthError(401, "Invalid or missing signer ARN in ALB OIDC JWT header")
    region, account_id = signer_match.group(1), signer_match.group(2)

    allowed_region = str(env.get("AUTH_ALB_REGION") or "").strip()
    if allowed_region and not secrets.compare_digest(region, allowed_region):
        raise AlbAuthError(403, f"ALB OIDC region '{region}' rejected by policy")

    allowed_account = str(env.get("AUTH_ALB_AWS_ACCOUNT") or "").strip()
    if allowed_account and not secrets.compare_digest(account_id, allowed_account):
        raise AlbAuthError(403, "ALB OIDC AWS account ID rejected by policy")

    if not any(secrets.compare_digest(signer, allowed) for allowed in allowed_signers):
        raise AlbAuthError(403, "ALB OIDC signer ARN is not allowlisted")

    fetcher = key_fetcher or fetch_alb_public_key
    public_pem = fetcher(region, kid)

    try:
        claims = jwt.decode(
            clean_token,
            key=public_pem,
            algorithms=["ES256"],
            leeway=leeway,
            options={
                "require": ["exp", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise AlbAuthError(401, "Expired ALB OIDC token") from exc
    except jwt.PyJWTError as exc:
        raise AlbAuthError(401, f"Invalid ALB OIDC token signature or claims: {exc}") from exc

    actual_iss = str(claims.get("iss") or "").strip()
    if not actual_iss or not any(secrets.compare_digest(actual_iss, expected) for expected in expected_issuers):
        raise AlbAuthError(403, "ALB OIDC issuer mismatch")

    return dict(claims)


def evaluate_owner_and_roles(
    claims: Mapping[str, Any],
    env: Mapping[str, str],
) -> Dict[str, Any]:
    """Resolve local RBAC headers (`authentik Admins` vs viewer) from Cognito claims and EBS owner binding."""
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise AlbAuthError(401, "Missing sub claim in ALB OIDC token")

    owner_sub = str(env.get("BRAINSOS_USER_SUB") or "").strip()
    owner_only = is_truthy(env.get("BRAINSOS_OWNER_ONLY"), default=True)
    admin_group = str(env.get("AUTH_COGNITO_ADMIN_GROUP") or "brainsos-admins").strip()
    claim_groups = _parse_claim_groups(claims)

    is_owner = bool(owner_sub and secrets.compare_digest(sub, owner_sub))
    is_group_admin = bool(
        admin_group and any(g.lower() == admin_group.lower() for g in claim_groups)
    )
    is_admin = is_owner or is_group_admin

    if not is_admin and owner_only:
        raise AlbAuthError(
            403,
            "Forbidden: authenticated identity does not own this appliance volume (BRAINSOS_USER_SUB)",
        )

    raw_username = str(
        claims.get("preferred_username")
        or claims.get("cognito:username")
        or claims.get("username")
        or claims.get("email")
        or sub
    ).strip()
    if not SAFE_USER_RE.match(raw_username):
        raw_username = re.sub(r"[^A-Za-z0-9_.@+-]", "_", raw_username)[:128] or sub

    email = str(claims.get("email") or "").strip()
    if not email or "\n" in email or "\r" in email:
        email = f"{raw_username}@cognito.local"

    display_name = str(claims.get("name") or raw_username).replace("\n", " ").replace("\r", " ").strip()

    groups_header = "authentik Admins" if is_admin else "brainsos-viewers"

    headers = {
        "X-Authentik-Username": raw_username,
        "Remote-User": raw_username,
        "X-Authentik-Email": email,
        "Remote-Email": email,
        "X-Authentik-Name": display_name,
        "X-Authentik-Uid": sub,
        "X-Authentik-Groups": groups_header,
        "X-BrainsOS-Owner": "true" if is_owner else "false",
    }

    return {
        "sub": sub,
        "username": raw_username,
        "email": email,
        "name": display_name,
        "is_owner": is_owner,
        "is_group_admin": is_group_admin,
        "is_admin": is_admin,
        "groups": groups_header,
        "headers": headers,
    }


def authenticate_alb_headers(
    headers: Mapping[str, str],
    env: Mapping[str, str],
    *,
    key_fetcher: Optional[Callable[[str, str], str]] = None,
) -> Dict[str, Any]:
    """End-to-end verification helper for Caddy forward-auth requests carrying `X-Amzn-Oidc-Data`."""
    oidc_data = headers.get("x-amzn-oidc-data") or headers.get("X-Amzn-Oidc-Data") or ""
    if not oidc_data:
        for k, v in headers.items():
            if k.lower() == "x-amzn-oidc-data" and v:
                oidc_data = v
                break
    claims = verify_alb_oidc_jwt(oidc_data, env, key_fetcher=key_fetcher)
    return evaluate_owner_and_roles(claims, env)


def validate_breakglass_toggle(
    enabled: bool,
    env: Mapping[str, str],
) -> Optional[str]:
    """Validate whether Break-Glass recovery can safely be set to `enabled`.

    Returns an error detail string if unsafe (preventing admin lockout), or None if valid.
    """
    if enabled:
        return None

    superuser = str(
        env.get("BRAINSOS_SUPERUSER_USERNAME")
        or env.get("BRAINSOS_ADMIN_USERNAME")
        or ""
    ).strip()
    has_named_superuser = bool(superuser and superuser.lower() not in ("admin", "akadmin"))

    user_sub = str(env.get("BRAINSOS_USER_SUB") or "").strip()
    cognito_enabled = is_truthy(env.get("AUTH_COGNITO_ENABLED"), default=False)
    alb_enabled = is_truthy(env.get("AUTH_ALB_OIDC_ENABLED"), default=False)
    has_owner_sso = bool(user_sub and (cognito_enabled or alb_enabled))

    if not has_named_superuser and not has_owner_sso:
        return (
            "Refusing to disable EC2 Instance-ID Break-Glass without another configured "
            "admin login path (set a named BRAINSOS_SUPERUSER_USERNAME or bind BRAINSOS_USER_SUB "
            "with Cognito/ALB OIDC enabled first)."
        )
    return None


def compute_cognito_redirect_uri(env: Mapping[str, str]) -> str:
    """Return the exact Authentik callback URI registered in Cognito App Client."""
    domain = str(env.get("BRAINSOS_DOMAIN") or "local.brainsos.ai").strip()
    domain = domain.removeprefix("https://").removeprefix("http://").split("/")[0] or "local.brainsos.ai"
    return f"https://{domain}/source/oauth/callback/cognito/"


def sanitize_env_value(value: Optional[str]) -> str:
    """Reject CR/LF/NUL/single-quote characters before writing values into `.env`."""
    raw = str(value or "").strip()
    if any(ch in raw for ch in ("\n", "\r", "\x00", "'")):
        raise ValueError("Environment value contains forbidden control or quote characters")
    return raw


def has_configured_cognito(env: Mapping[str, str]) -> bool:
    """Check whether minimum Cognito parameters are configured."""
    return bool(
        is_truthy(env.get("AUTH_COGNITO_ENABLED"), default=False)
        and (env.get("AUTH_COGNITO_REGION") or "").strip()
        and (env.get("AUTH_COGNITO_USER_POOL_ID") or "").strip()
        and (env.get("AUTH_COGNITO_CLIENT_ID") or "").strip()
    )


def build_cognito_well_known_url(region: str, pool_id: str) -> str:
    """Construct validated AWS Cognito OIDC discovery document URL."""
    clean_region = region.strip()
    clean_pool = pool_id.strip()
    if not AWS_REGION_RE.match(clean_region):
        raise ValueError(f"Invalid AWS Cognito region '{region}'")
    if not re.match(r"^[a-z]{2}(?:-[a-z]+)+-\d+_[A-Za-z0-9]+$", clean_pool):
        raise ValueError(f"Invalid Cognito User Pool ID '{pool_id}'")
    return f"https://cognito-idp.{clean_region}.amazonaws.com/{clean_pool}/.well-known/openid-configuration"


def current_env_for_repo(file_env: Mapping[str, str], proc_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Merge file `.env` overrides with host environment cleanly for ALB/Cognito helpers."""
    merged: Dict[str, str] = {}
    if proc_env is None:
        proc_env = os.environ
    merged.update({k: v for k, v in proc_env.items()})
    merged.update({k: v for k, v in file_env.items() if v != ""})
    return merged
