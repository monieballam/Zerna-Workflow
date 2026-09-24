"""Permission definitions for role-based access control."""

from enum import Enum


class ResourceType(str, Enum):
    """Types of resources that can be accessed."""

    ORGANIZATION = "organization"
    DATASET = "dataset"
    DATASET_VERSION = "dataset_version"
    RUN = "run"
    PIPELINE_TEMPLATE = "pipeline_template"
    ARTIFACT = "artifact"
    ANNOTATION = "annotation"
    KNOWLEDGE_PACK = "knowledge_pack"
    AUDIT_EVENT = "audit_event"
    USER = "user"


class Action(str, Enum):
    """Actions that can be performed on resources."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    APPROVE = "approve"


class Permission(str, Enum):
    """Specific permissions combining resource and action."""

    # Organization permissions
    ORG_READ = "organization:read"
    ORG_UPDATE = "organization:update"
    ORG_DELETE = "organization:delete"
    ORG_MANAGE_USERS = "organization:manage_users"

    # Dataset permissions
    DATASET_CREATE = "dataset:create"
    DATASET_READ = "dataset:read"
    DATASET_UPDATE = "dataset:update"
    DATASET_DELETE = "dataset:delete"

    # Run permissions
    RUN_CREATE = "run:create"
    RUN_READ = "run:read"
    RUN_CANCEL = "run:cancel"
    RUN_DELETE = "run:delete"

    # Pipeline template permissions
    TEMPLATE_CREATE = "pipeline_template:create"
    TEMPLATE_READ = "pipeline_template:read"
    TEMPLATE_UPDATE = "pipeline_template:update"
    TEMPLATE_DELETE = "pipeline_template:delete"

    # Artifact permissions
    ARTIFACT_READ = "artifact:read"
    ARTIFACT_DELETE = "artifact:delete"

    # Annotation permissions
    ANNOTATION_CREATE = "annotation:create"
    ANNOTATION_READ = "annotation:read"
    ANNOTATION_UPDATE = "annotation:update"
    ANNOTATION_APPROVE = "annotation:approve"
    ANNOTATION_DELETE = "annotation:delete"

    # Knowledge pack permissions
    KNOWLEDGE_PACK_CREATE = "knowledge_pack:create"
    KNOWLEDGE_PACK_READ = "knowledge_pack:read"
    KNOWLEDGE_PACK_UPDATE = "knowledge_pack:update"
    KNOWLEDGE_PACK_DELETE = "knowledge_pack:delete"

    # Audit event permissions
    AUDIT_READ = "audit_event:read"

    # User permissions
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"


# Role hierarchy: admin > member > viewer
# Each role inherits permissions from roles below it
ROLE_PERMISSIONS = {
    "admin": {
        # Admin has all permissions
        Permission.ORG_READ,
        Permission.ORG_UPDATE,
        Permission.ORG_DELETE,
        Permission.ORG_MANAGE_USERS,
        Permission.DATASET_CREATE,
        Permission.DATASET_READ,
        Permission.DATASET_UPDATE,
        Permission.DATASET_DELETE,
        Permission.RUN_CREATE,
        Permission.RUN_READ,
        Permission.RUN_CANCEL,
        Permission.RUN_DELETE,
        Permission.TEMPLATE_CREATE,
        Permission.TEMPLATE_READ,
        Permission.TEMPLATE_UPDATE,
        Permission.TEMPLATE_DELETE,
        Permission.ARTIFACT_READ,
        Permission.ARTIFACT_DELETE,
        Permission.ANNOTATION_CREATE,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_UPDATE,
        Permission.ANNOTATION_APPROVE,
        Permission.ANNOTATION_DELETE,
        Permission.KNOWLEDGE_PACK_CREATE,
        Permission.KNOWLEDGE_PACK_READ,
        Permission.KNOWLEDGE_PACK_UPDATE,
        Permission.KNOWLEDGE_PACK_DELETE,
        Permission.AUDIT_READ,
        Permission.USER_READ,
        Permission.USER_UPDATE,
        Permission.USER_DELETE,
    },
    "member": {
        # Member can create and manage their own resources
        Permission.ORG_READ,
        Permission.DATASET_CREATE,
        Permission.DATASET_READ,
        Permission.DATASET_UPDATE,
        Permission.DATASET_DELETE,
        Permission.RUN_CREATE,
        Permission.RUN_READ,
        Permission.RUN_CANCEL,
        Permission.TEMPLATE_CREATE,
        Permission.TEMPLATE_READ,
        Permission.TEMPLATE_UPDATE,
        Permission.ARTIFACT_READ,
        Permission.ANNOTATION_CREATE,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_UPDATE,
        Permission.KNOWLEDGE_PACK_READ,
        Permission.AUDIT_READ,
        Permission.USER_READ,
    },
    "viewer": {
        # Viewer can only read resources
        Permission.ORG_READ,
        Permission.DATASET_READ,
        Permission.RUN_READ,
        Permission.TEMPLATE_READ,
        Permission.ARTIFACT_READ,
        Permission.ANNOTATION_READ,
        Permission.KNOWLEDGE_PACK_READ,
        Permission.AUDIT_READ,
        Permission.USER_READ,
    },
}
