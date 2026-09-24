"""Authentication service for OAuth2 + JWT with Argon2id password hashing."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import ROLE_PERMISSIONS, Permission
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.models.audit import AuditEvent
from apps.api.models.organization import Organization, User, organization_users
from apps.api.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    sub: str  # User ID
    email: str
    exp: int  # Expiration timestamp
    iat: int  # Issued at timestamp
    type: str  # "access" or "refresh"


class AuthToken(BaseModel):
    """Authentication token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class OrganizationMembershipSummary(BaseModel):
    """Organization membership summary for session and admin views."""

    organization_id: UUID
    organization_name: str
    role: UserRole
    joined_at: datetime


class OrganizationMemberSummary(BaseModel):
    """Member row for admin management views."""

    user_id: UUID
    email: str
    role: UserRole
    joined_at: datetime
    created_at: datetime


class AuthService:
    """Service for authentication, token generation, and password management."""

    def __init__(
        self,
        db: AsyncSession,
        redis_client: aioredis.Redis,
        jwt_secret_key: str,
        jwt_algorithm: str = "HS256",
        access_token_expire_minutes: int = 60,
        refresh_token_expire_days: int = 30,
    ) -> None:
        """Initialize AuthService.

        Args:
            db: Database session
            redis_client: Redis client for refresh token storage
            jwt_secret_key: Secret key for JWT signing (HS256 string or RS256 PEM private key)
            jwt_algorithm: JWT signing algorithm (HS256 typical for dev; RS256 for production PEM keys)
            access_token_expire_minutes: Access token expiration in minutes
            refresh_token_expire_days: Refresh token expiration in days
        """
        self.db = db
        self.redis = redis_client
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self.audit = AuditService(db)

        # Argon2id password hashing context
        self.pwd_context = CryptContext(
            schemes=["argon2"],
            deprecated="auto",
            argon2__memory_cost=65536,  # 64 MB
            argon2__time_cost=3,  # 3 iterations
            argon2__parallelism=4,  # 4 parallel threads
        )

    async def register_user(
        self,
        email: str,
        password: str,
        organization_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, Organization]:
        """Create a new user with a default organization membership.

        Raises:
            ValueError: if the email is already registered.
        """
        normalized_email = email.strip().lower()

        existing_stmt = select(User).where(User.email == normalized_email)
        existing_result = await self.db.execute(existing_stmt)
        existing_user = existing_result.scalar_one_or_none()
        if existing_user is not None:
            raise ValueError("An account with this email already exists.")

        settings = get_settings()
        default_org_name = organization_name or self._default_organization_name(normalized_email)

        user = User(
            id=uuid4(),
            email=normalized_email,
            hashed_password=self.hash_password(password),
            created_at=datetime.utcnow(),
        )
        organization = Organization(
            id=uuid4(),
            name=default_org_name,
            storage_quota_gb=settings.default_storage_quota_gb,
            compute_quota_runs=settings.default_compute_quota_runs,
            created_at=datetime.utcnow(),
        )

        self.db.add(user)
        self.db.add(organization)
        await self.db.flush()

        await self.db.execute(
            organization_users.insert().values(
                organization_id=organization.id,
                user_id=user.id,
                role=UserRole.ADMIN,
                joined_at=datetime.utcnow(),
            )
        )
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(organization)

        await self.audit.audit_log(
            org_id=organization.id,
            user_id=user.id,
            action_type="auth.signup.success",
            resource_type="user",
            resource_id=user.id,
            after_state={
                "email": normalized_email,
                "organization_name": organization.name,
                "ip_address": ip_address,
                "user_agent": user_agent,
            },
        )
        await self.db.commit()

        return user, organization

    @staticmethod
    def _default_organization_name(email: str) -> str:
        """Generate a readable default organization name from an email address."""
        local_part = email.split("@", 1)[0].strip() or "user"
        cleaned = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip()
        if not cleaned:
            cleaned = "User"
        return f"{cleaned.title()} Workspace"

    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2id.

        Args:
            password: Plain text password

        Returns:
            Hashed password string
        """
        return cast(str, self.pwd_context.hash(password))

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to compare against

        Returns:
            True if password matches, False otherwise
        """
        return cast(bool, self.pwd_context.verify(plain_password, hashed_password))

    def create_access_token(self, user: User) -> str:
        """Create a JWT access token.

        Args:
            user: User object

        Returns:
            Encoded JWT access token
        """
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.access_token_expire_minutes)

        payload = {
            "sub": str(user.id),
            "email": user.email,
            "exp": int(expire.timestamp()),
            "iat": int(now.timestamp()),
            "type": "access",
        }

        return cast(str, jwt.encode(payload, self.jwt_secret_key, algorithm=self.jwt_algorithm))

    def create_refresh_token(self, user: User) -> str:
        """Create a JWT refresh token.

        Args:
            user: User object

        Returns:
            Encoded JWT refresh token
        """
        now = datetime.utcnow()
        expire = now + timedelta(days=self.refresh_token_expire_days)

        payload = {
            "sub": str(user.id),
            "email": user.email,
            "exp": int(expire.timestamp()),
            "iat": int(now.timestamp()),
            "type": "refresh",
        }

        return cast(str, jwt.encode(payload, self.jwt_secret_key, algorithm=self.jwt_algorithm))

    def verify_token(self, token: str, token_type: str = "access") -> TokenPayload | None:
        """Verify and decode a JWT token.

        Args:
            token: JWT token string
            token_type: Expected token type ("access" or "refresh")

        Returns:
            TokenPayload if valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret_key,
                algorithms=[self.jwt_algorithm],
                options={"verify_exp": True},
            )

            # Verify token type
            if payload.get("type") != token_type:
                return None

            exp = payload.get("exp")
            if not isinstance(exp, int) or exp <= int(datetime.utcnow().timestamp()):
                return None

            return TokenPayload(**payload)
        except JWTError:
            return None

    async def store_refresh_token(self, user_id: UUID, refresh_token: str) -> None:
        """Store refresh token in Redis with TTL.

        Args:
            user_id: User ID
            refresh_token: Refresh token to store
        """
        key = f"refresh_token:{user_id}"
        ttl_seconds = self.refresh_token_expire_days * 24 * 60 * 60

        try:
            await self.redis.setex(key, ttl_seconds, refresh_token)
        except Exception:
            logger.warning("Redis unavailable, refresh token not stored")

    async def verify_refresh_token(self, user_id: UUID, refresh_token: str) -> bool:
        """Verify refresh token against stored value in Redis.

        Args:
            user_id: User ID
            refresh_token: Refresh token to verify

        Returns:
            True if token is valid and matches stored value, False otherwise
        """
        key = f"refresh_token:{user_id}"
        stored_token = await self.redis.get(key)

        if stored_token is None:
            return False

        # Compare tokens (stored_token is bytes in redis-py)
        if isinstance(stored_token, bytes):
            stored_token = stored_token.decode("utf-8")

        return secrets.compare_digest(stored_token, refresh_token)

    async def revoke_refresh_token(self, user_id: UUID) -> None:
        """Revoke refresh token by deleting from Redis.

        Args:
            user_id: User ID
        """
        key = f"refresh_token:{user_id}"
        await self.redis.delete(key)

    async def check_rate_limit(self, email: str) -> tuple[bool, int | None]:
        """Check if user is rate limited for failed login attempts.

        Args:
            email: User email

        Returns:
            Tuple of (is_allowed, seconds_until_unlock)
            - is_allowed: True if user can attempt login, False if locked out
            - seconds_until_unlock: Seconds remaining in lockout, None if not locked
        """
        settings = get_settings()
        if not settings.auth_login_lockout_enabled:
            return True, None

        lockout_key = f"auth_lockout:{email}"

        # Check if user is locked out
        try:
            lockout_ttl = await self.redis.ttl(lockout_key)
            if lockout_ttl > 0:
                return False, lockout_ttl
        except Exception:
            pass  # Redis unavailable, allow the attempt

        return True, None

    async def record_failed_attempt(self, email: str) -> tuple[bool, int | None]:
        """Record a failed login attempt and apply rate limiting.

        After 5 failed attempts, user is locked out for 15 minutes.

        Args:
            email: User email

        Returns:
            Tuple of (is_locked_out, seconds_until_unlock)
            - is_locked_out: True if user is now locked out
            - seconds_until_unlock: Seconds in lockout, None if not locked
        """
        settings = get_settings()
        if not settings.auth_login_lockout_enabled:
            return False, None

        attempts_key = f"auth_attempts:{email}"
        lockout_key = f"auth_lockout:{email}"

        try:
            # Increment failed attempts counter
            attempts = await self.redis.incr(attempts_key)

            # Set TTL on first attempt (5 minutes window)
            if attempts == 1:
                await self.redis.expire(attempts_key, 300)

            # Check if threshold exceeded (5 attempts)
            if attempts >= 5:
                # Lock out for 15 minutes
                lockout_seconds = 15 * 60
                await self.redis.setex(lockout_key, lockout_seconds, "1")
                # Clear attempts counter
                await self.redis.delete(attempts_key)
                return True, lockout_seconds
        except Exception:
            pass  # Redis unavailable, skip rate limiting

        return False, None

    async def clear_failed_attempts(self, email: str) -> None:
        """Clear failed login attempts counter on successful login.

        Args:
            email: User email
        """
        attempts_key = f"auth_attempts:{email}"
        try:
            await self.redis.delete(attempts_key)
        except Exception:
            pass  # Redis unavailable

    async def create_audit_event(
        self,
        user_id: UUID | None,
        organization_id: UUID | None,
        action_type: str,
        resource_type: str,
        resource_id: UUID,
        before_state: dict | None = None,
        after_state: dict | None = None,
    ) -> AuditEvent:
        """Create an audit event for authentication actions.

        Args:
            user_id: User ID (None for failed login attempts)
            organization_id: Organization ID (None for failed login attempts)
            action_type: Action type (e.g., "auth.login.success", "auth.login.failure")
            resource_type: Resource type (e.g., "user")
            resource_id: Resource ID
            before_state: State before action
            after_state: State after action (includes IP, user agent)

        Returns:
            Created AuditEvent
        """
        # For failed login attempts, use a placeholder organization_id
        # In production, this should be handled differently or use a system org
        if organization_id is None:
            organization_id = uuid4()  # Placeholder for failed attempts

        audit_event = AuditEvent(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id or uuid4(),  # Placeholder for failed attempts
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            timestamp=datetime.utcnow(),
        )

        self.db.add(audit_event)
        await self.db.commit()
        await self.db.refresh(audit_event)

        return audit_event

    async def authenticate(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> User | None:
        """Authenticate user with email and password.

        Includes rate limiting and audit logging.

        Args:
            email: User email
            password: Plain text password
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            User object if authentication successful, None otherwise
        """
        # Check rate limit
        is_allowed, _ = await self.check_rate_limit(email)
        if not is_allowed:
            return None

        # Query user by email
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            # Record failed attempt
            await self.record_failed_attempt(email)

            # Skip audit for unknown users — we have no valid org_id and
            # inserting a random UUID violates the organizations FK.
            logger.info("Login failed: user not found for email=%s", email)
            return None

        # Verify password
        if not self.verify_password(password, user.hashed_password):
            # Record failed attempt
            await self.record_failed_attempt(email)

            # Get user's first organization for audit event
            orgs = await self.get_user_organizations(user.id)
            if orgs:
                org_id = orgs[0][0]
                # Audit: failed login (wrong password)
                await self.audit.audit_log(
                    org_id=org_id,
                    user_id=user.id,
                    action_type="auth.login.failure",
                    resource_type="user",
                    resource_id=user.id,
                    after_state={
                        "email": email,
                        "ip_address": ip_address,
                        "user_agent": user_agent,
                        "reason": "invalid_password",
                    },
                )
                await self.db.commit()
            else:
                logger.info("Login failed (invalid password) for email=%s, no org for audit", email)
            return None

        # Clear failed attempts on successful login
        await self.clear_failed_attempts(email)

        # Get user's first organization for audit event
        orgs = await self.get_user_organizations(user.id)
        if orgs:
            org_id = orgs[0][0]
            # Audit: successful login
            await self.audit.audit_log(
                org_id=org_id,
                user_id=user.id,
                action_type="auth.login.success",
                resource_type="user",
                resource_id=user.id,
                after_state={
                    "email": email,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                },
            )
            await self.db.commit()

        return user

    async def create_auth_tokens(self, user: User) -> AuthToken:
        """Create access and refresh tokens for a user.

        Args:
            user: User object

        Returns:
            AuthToken with access and refresh tokens
        """
        access_token = self.create_access_token(user)
        refresh_token = self.create_refresh_token(user)

        # Store refresh token in Redis
        await self.store_refresh_token(user.id, refresh_token)

        return AuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.access_token_expire_minutes * 60,
        )

    async def refresh_access_token(self, refresh_token: str) -> AuthToken | None:
        """Refresh access token using a valid refresh token.

        Args:
            refresh_token: Refresh token

        Returns:
            New AuthToken if refresh successful, None otherwise
        """
        # Verify refresh token
        payload = self.verify_token(refresh_token, token_type="refresh")
        if payload is None:
            return None

        user_id = UUID(payload.sub)

        # Verify refresh token is stored in Redis
        if not await self.verify_refresh_token(user_id, refresh_token):
            return None

        # Get user from database
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            return None

        # Create new tokens
        return await self.create_auth_tokens(user)

    async def get_user_organizations(self, user_id: UUID) -> list[tuple[UUID, UserRole]]:
        """Get all organizations a user belongs to with their roles.

        Caches the result for CacheTTL.USER_ORG_MEMBERSHIPS seconds.

        Args:
            user_id: User ID

        Returns:
            List of tuples (organization_id, role)
        """
        stmt = select(organization_users.c.organization_id, organization_users.c.role).where(
            organization_users.c.user_id == user_id
        )

        result = await self.db.execute(stmt)
        return [(row.organization_id, row.role) for row in result]

    async def get_user_organization_memberships(
        self, user_id: UUID
    ) -> list[OrganizationMembershipSummary]:
        """Get detailed organization memberships for one user."""
        stmt = (
            select(
                organization_users.c.organization_id.label("organization_id"),
                Organization.name.label("organization_name"),
                organization_users.c.role.label("role"),
                organization_users.c.joined_at.label("joined_at"),
            )
            .join(Organization, Organization.id == organization_users.c.organization_id)
            .where(organization_users.c.user_id == user_id)
            .order_by(organization_users.c.joined_at.asc(), Organization.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return [
            OrganizationMembershipSummary(
                organization_id=row.organization_id,
                organization_name=row.organization_name,
                role=row.role,
                joined_at=row.joined_at,
            )
            for row in result
        ]

    async def get_primary_organization_membership(
        self, user_id: UUID
    ) -> OrganizationMembershipSummary | None:
        """Return the organization membership used as the current app context."""
        memberships = await self.get_user_organization_memberships(user_id)
        return memberships[0] if memberships else None

    async def get_user_role_in_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> UserRole | None:
        """Get user's role in a specific organization.

        Args:
            user_id: User ID
            organization_id: Organization ID

        Returns:
            UserRole if user is member of organization, None otherwise
        """
        stmt = select(organization_users.c.role).where(
            organization_users.c.user_id == user_id,
            organization_users.c.organization_id == organization_id,
        )

        result = await self.db.execute(stmt)
        row = result.first()

        return row.role if row else None

    async def is_member_of_organization(self, user_id: UUID, organization_id: UUID) -> bool:
        """Check if user is a member of an organization.

        Args:
            user_id: User ID
            organization_id: Organization ID

        Returns:
            True if user is a member, False otherwise
        """
        role = await self.get_user_role_in_organization(user_id, organization_id)
        return role is not None

    async def list_organization_members(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMemberSummary]:
        """List members in one organization ordered by join time."""
        stmt = (
            select(
                User.id.label("user_id"),
                User.email.label("email"),
                organization_users.c.role.label("role"),
                organization_users.c.joined_at.label("joined_at"),
                User.created_at.label("created_at"),
            )
            .join(organization_users, organization_users.c.user_id == User.id)
            .where(organization_users.c.organization_id == organization_id)
            .order_by(organization_users.c.joined_at.asc(), User.created_at.asc(), User.email.asc())
        )
        result = await self.db.execute(stmt)
        return [
            OrganizationMemberSummary(
                user_id=row.user_id,
                email=row.email,
                role=row.role,
                joined_at=row.joined_at,
                created_at=row.created_at,
            )
            for row in result
        ]

    async def create_or_add_member(
        self,
        *,
        organization_id: UUID,
        email: str,
        role: UserRole,
        acting_user_id: UUID,
        password: str | None = None,
    ) -> OrganizationMemberSummary:
        """Create a new user or attach an existing user to an organization."""
        normalized_email = email.strip().lower()

        existing_user_stmt = select(User).where(User.email == normalized_email)
        existing_user_result = await self.db.execute(existing_user_stmt)
        user = existing_user_result.scalar_one_or_none()

        if user is None:
            if not password:
                raise ValueError("password is required when creating a new user")
            user = User(
                id=uuid4(),
                email=normalized_email,
                hashed_password=self.hash_password(password),
                created_at=datetime.utcnow(),
            )
            self.db.add(user)
            await self.db.flush()

        membership_stmt = select(organization_users.c.role).where(
            organization_users.c.organization_id == organization_id,
            organization_users.c.user_id == user.id,
        )
        membership_result = await self.db.execute(membership_stmt)
        membership = membership_result.first()

        action_type = "admin.member.add"
        before_state: dict | None = None
        if membership is None:
            await self.db.execute(
                organization_users.insert().values(
                    organization_id=organization_id,
                    user_id=user.id,
                    role=role,
                    joined_at=datetime.utcnow(),
                )
            )
        elif membership.role != role:
            before_state = {"role": membership.role.value}
            action_type = "admin.member.role_update"
            await self.db.execute(
                organization_users.update()
                .where(
                    organization_users.c.organization_id == organization_id,
                    organization_users.c.user_id == user.id,
                )
                .values(role=role)
            )
        else:
            members = await self.list_organization_members(organization_id)
            existing = next((member for member in members if member.user_id == user.id), None)
            if existing is None:
                raise ValueError(
                    f"User {user.id} is not a member of organization {organization_id}"
                )
            return existing

        await self.audit.audit_log(
            org_id=organization_id,
            user_id=acting_user_id,
            action_type=action_type,
            resource_type="user",
            resource_id=user.id,
            before_state=before_state,
            after_state={"email": user.email, "role": role.value},
        )
        await self.db.commit()

        members = await self.list_organization_members(organization_id)
        created_member = next((member for member in members if member.user_id == user.id), None)
        if created_member is None:
            raise ValueError(f"User {user.id} is not a member of organization {organization_id}")
        return created_member

    async def update_member_role(
        self,
        *,
        organization_id: UUID,
        member_user_id: UUID,
        role: UserRole,
        acting_user_id: UUID,
    ) -> OrganizationMemberSummary:
        """Update one member's organization-scoped role."""
        membership_stmt = select(organization_users.c.role).where(
            organization_users.c.organization_id == organization_id,
            organization_users.c.user_id == member_user_id,
        )
        membership_result = await self.db.execute(membership_stmt)
        membership = membership_result.first()

        if membership is None:
            raise ValueError(
                f"User {member_user_id} is not a member of organization {organization_id}"
            )

        current_role = membership.role
        if current_role == role:
            members = await self.list_organization_members(organization_id)
            existing = next(
                (member for member in members if member.user_id == member_user_id), None
            )
            if existing is None:
                raise ValueError(
                    f"User {member_user_id} is not a member of organization {organization_id}"
                )
            return existing

        if current_role == UserRole.ADMIN and role != UserRole.ADMIN:
            admin_members_stmt = select(organization_users.c.user_id).where(
                organization_users.c.organization_id == organization_id,
                organization_users.c.role == UserRole.ADMIN,
            )
            admin_members_result = await self.db.execute(admin_members_stmt)
            admin_members = list(admin_members_result.scalars().all())
            if len(admin_members) <= 1:
                raise ValueError("Cannot demote the last admin in the organization")

        await self.db.execute(
            organization_users.update()
            .where(
                organization_users.c.organization_id == organization_id,
                organization_users.c.user_id == member_user_id,
            )
            .values(role=role)
        )
        await self.audit.audit_log(
            org_id=organization_id,
            user_id=acting_user_id,
            action_type="admin.member.role_update",
            resource_type="user",
            resource_id=member_user_id,
            before_state={"role": current_role.value},
            after_state={"role": role.value},
        )
        await self.db.commit()

        members = await self.list_organization_members(organization_id)
        updated_member = next(
            (member for member in members if member.user_id == member_user_id), None
        )
        if updated_member is None:
            raise ValueError(
                f"User {member_user_id} is not a member of organization {organization_id}"
            )
        return updated_member

    async def ensure_bootstrap_admin(
        self,
        *,
        email: str | None,
        organization_name: str = "Zerna",
        password: str | None = None,
    ) -> None:
        """Ensure the configured bootstrap email is an org admin when present."""
        if not email:
            return

        normalized_email = email.strip().lower()
        stmt = select(User).where(User.email == normalized_email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            if not password:
                logger.info(
                    "Bootstrap admin %s not found; skipping creation because no password was configured",
                    normalized_email,
                )
                return
            await self.register_user(
                normalized_email,
                password,
                organization_name=organization_name,
            )
            logger.info("Created bootstrap admin user %s", normalized_email)
            return

        memberships = await self.get_user_organization_memberships(user.id)
        if not memberships:
            org_stmt = (
                select(Organization)
                .where(Organization.name == organization_name)
                .order_by(Organization.created_at.asc())
            )
            org_result = await self.db.execute(org_stmt)
            organization = org_result.scalar_one_or_none()
            if organization is None:
                settings = get_settings()
                organization = Organization(
                    id=uuid4(),
                    name=organization_name,
                    storage_quota_gb=settings.default_storage_quota_gb,
                    compute_quota_runs=settings.default_compute_quota_runs,
                    created_at=datetime.utcnow(),
                )
                self.db.add(organization)
                await self.db.flush()

            await self.db.execute(
                organization_users.insert().values(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=UserRole.ADMIN,
                    joined_at=datetime.utcnow(),
                )
            )
            await self.db.commit()
            logger.info(
                "Attached bootstrap admin %s to organization %s as admin",
                normalized_email,
                organization.name,
            )
            return

        target = next(
            (
                membership
                for membership in memberships
                if membership.organization_name == organization_name
            ),
            memberships[0],
        )
        if target.role == UserRole.ADMIN:
            return

        await self.db.execute(
            organization_users.update()
            .where(
                organization_users.c.organization_id == target.organization_id,
                organization_users.c.user_id == user.id,
            )
            .values(role=UserRole.ADMIN)
        )
        await self.db.commit()
        logger.info(
            "Promoted bootstrap admin %s to admin in organization %s",
            normalized_email,
            target.organization_name,
        )

    def check_permission(self, role: UserRole, permission: Permission) -> bool:
        """Check if a role has a specific permission.

        Implements role hierarchy: admin > member > viewer
        Each role inherits permissions from roles below it.

        Args:
            role: User's role in the organization
            permission: Permission to check

        Returns:
            True if role has permission, False otherwise
        """
        # Get permissions for this role
        role_permissions = ROLE_PERMISSIONS.get(role.value, set())

        # Check if permission is in role's permission set
        return permission in role_permissions

    async def check_user_permission(
        self, user_id: UUID, organization_id: UUID, permission: Permission
    ) -> bool:
        """Check if a user has a specific permission in an organization.

        Args:
            user_id: User ID
            organization_id: Organization ID
            permission: Permission to check

        Returns:
            True if user has permission, False otherwise
        """
        # Get user's role in organization
        role = await self.get_user_role_in_organization(user_id, organization_id)

        if role is None:
            return False

        # Check if role has permission
        return self.check_permission(role, permission)

    async def require_permission(
        self, user_id: UUID, organization_id: UUID, permission: Permission
    ) -> None:
        """Require that a user has a specific permission in an organization.

        Args:
            user_id: User ID
            organization_id: Organization ID
            permission: Permission to check

        Raises:
            PermissionError: If user does not have permission
        """
        has_permission = await self.check_user_permission(user_id, organization_id, permission)

        if not has_permission:
            raise PermissionError(
                f"User {user_id} does not have permission {permission.value} "
                f"in organization {organization_id}"
            )
