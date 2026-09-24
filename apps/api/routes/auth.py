"""Authentication API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_service, get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    SignupRequest,
    UserOrganizationMembership,
    UserProfile,
)
from apps.api.services.auth_service import AuthService

router = APIRouter(prefix="/v1/auth", tags=["authentication"])


async def _build_user_profile(user: User, auth_service: AuthService) -> UserProfile:
    """Build the richer auth session payload used by the web app."""
    memberships = await auth_service.get_user_organization_memberships(user.id)
    active_membership = memberships[0] if memberships else None
    return UserProfile(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
        organizations=[
            UserOrganizationMembership(
                organization_id=membership.organization_id,
                organization_name=membership.organization_name,
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for membership in memberships
        ],
        active_organization_id=active_membership.organization_id if active_membership else None,
        active_organization_name=active_membership.organization_name if active_membership else None,
        active_role=active_membership.role if active_membership else None,
    )


@router.post(
    "/signup",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create account",
    description="Create a new user account, provision a default organization, and return JWT tokens",
)
async def signup(
    request_body: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Self-service signup endpoint."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        user, _organization = await auth_service.register_user(
            request_body.email,
            request_body.password,
            organization_name=request_body.organization_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    auth_token = await auth_service.create_auth_tokens(user)

    return LoginResponse(
        access_token=auth_token.access_token,
        refresh_token=auth_token.refresh_token,
        token_type=auth_token.token_type,
        expires_in=auth_token.expires_in,
        user=await _build_user_profile(user, auth_service),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="User login",
    description="Authenticate user with email and password, returns JWT tokens",
)
async def login(
    request_body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Login endpoint.

    Authenticates user with email and password, returns access and refresh tokens.
    Includes rate limiting (5 failed attempts → 15-min lockout) and audit logging.

    Args:
        request_body: Login request with email and password
        request: FastAPI request object for IP and user agent
        db: Database session
        auth_service: Authentication service

    Returns:
        LoginResponse with tokens and user profile

    Raises:
        HTTPException: 401 if authentication fails
        HTTPException: 429 if rate limit exceeded
    """
    # Check rate limit before attempting authentication
    is_allowed, seconds_until_unlock = await auth_service.check_rate_limit(request_body.email)

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {seconds_until_unlock} seconds.",
            headers={"Retry-After": str(seconds_until_unlock)},
        )

    # Extract IP address and user agent from request
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Authenticate user with audit logging
    user = await auth_service.authenticate(
        request_body.email,
        request_body.password,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if user is None:
        # Check if user is now locked out after this failed attempt
        is_allowed, seconds_until_unlock = await auth_service.check_rate_limit(request_body.email)

        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account locked for {seconds_until_unlock} seconds.",
                headers={"Retry-After": str(seconds_until_unlock)},
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens
    auth_token = await auth_service.create_auth_tokens(user)

    # Return response with user profile
    return LoginResponse(
        access_token=auth_token.access_token,
        refresh_token=auth_token.refresh_token,
        token_type=auth_token.token_type,
        expires_in=auth_token.expires_in,
        user=await _build_user_profile(user, auth_service),
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Refresh access token using a valid refresh token",
)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> RefreshResponse:
    """Token refresh endpoint.

    Refreshes access token using a valid refresh token.

    Args:
        request: Refresh request with refresh token
        db: Database session
        auth_service: Authentication service

    Returns:
        RefreshResponse with new tokens

    Raises:
        HTTPException: 401 if refresh token is invalid or expired
    """
    # Refresh tokens
    auth_token = await auth_service.refresh_access_token(request.refresh_token)

    if auth_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Return response with new tokens
    return RefreshResponse(
        access_token=auth_token.access_token,
        refresh_token=auth_token.refresh_token,
        token_type=auth_token.token_type,
        expires_in=auth_token.expires_in,
    )


@router.get(
    "/me",
    response_model=UserProfile,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description="Return the authenticated user's profile for session validation",
)
async def me(
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    """Return the current authenticated user profile."""
    return await _build_user_profile(current_user, auth_service)
