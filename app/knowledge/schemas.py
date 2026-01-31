"""
Pydantic schemas for knowledge graph validation.

These schemas ensure YAML files are well-formed and contain valid data.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator


class NodeType(str, Enum):
    """Valid node types in the knowledge graph"""
    PROBLEM = "problem"
    ATTRIBUTE = "attribute"
    INGREDIENT = "ingredient"
    CONSTRAINT = "constraint"
    QUESTION = "question"
    PRODUCT = "product"
    DOMAIN = "domain"
    SUBDOMAIN = "subdomain"


class RelationType(str, Enum):
    """Valid relationship types between nodes"""
    # Hierarchy
    BELONGS_TO = "BELONGS_TO"

    # Problem-solution mapping
    ADDRESSES = "ADDRESSES"
    CAUSED_BY = "CAUSED_BY"

    # Slot-filling requirements
    REQUIRES_KNOWING = "REQUIRES_KNOWING"
    ELICITS_QUESTION = "ELICITS_QUESTION"

    # Product composition
    CONTAINS = "CONTAINS"

    # Efficacy relationships
    RECOMMENDED_FOR = "RECOMMENDED_FOR"
    TREATS = "TREATS"

    # Safety constraints
    CONTRAINDICATED_FOR = "CONTRAINDICATED_FOR"
    INCOMPATIBLE_WITH = "INCOMPATIBLE_WITH"

    # Semantic relationships
    SIMILAR_TO = "SIMILAR_TO"
    OFTEN_PAIRED_WITH = "OFTEN_PAIRED_WITH"

    # Question flow
    FOLLOWS_UP = "FOLLOWS_UP"

    # Filtering logic
    EXCLUDES = "EXCLUDES"


class DataType(str, Enum):
    """Valid data types for attributes"""
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    TEXT = "text"


class ResponseType(str, Enum):
    """Valid response types for questions"""
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    FREE_TEXT = "free_text"


class ConstraintType(str, Enum):
    """Valid constraint types"""
    ALLERGY = "allergy"
    DIETARY = "dietary"
    MEDICAL = "medical"
    BUDGET = "budget"
    PREFERENCE = "preference"


class Severity(str, Enum):
    """Severity levels for constraints"""
    HARD = "hard"  # Must exclude
    SOFT = "soft"  # Prefer to avoid


class GraphMetadata(BaseModel):
    """Metadata for a knowledge graph"""
    domain: str = Field(..., description="Domain name (e.g., 'skincare', 'wellness')")
    version: str = Field(..., description="Semantic version (e.g., '1.0.0')")
    created_at: str = Field(..., description="Creation date in ISO format")
    description: str = Field(..., description="Human-readable description")
    display_name: str = Field(..., description="User-facing display name for the domain")
    persona: Optional[str] = Field(default=None, description="Agent personality/instructions for this domain")
    is_active: bool = Field(default=True, description="Whether this domain is active and available")
    parent_domain: Optional[str] = Field(default=None, description="Parent domain slug if this is a subdomain")

    class Config:
        extra = "forbid"


class ProblemNode(BaseModel):
    """Problem/concern that users want to address"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    name: str = Field(..., description="Canonical name")
    display_name: str = Field(..., description="User-facing display name")
    synonyms: List[str] = Field(default_factory=list, description="Alternative names")
    severity_levels: List[str] = Field(default_factory=list, description="Severity levels")
    description: str = Field(default="", description="Detailed description")

    class Config:
        extra = "forbid"

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError(f"ID must be snake_case alphanumeric: {v}")
        return v


class AttributeNode(BaseModel):
    """User characteristic or preference"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    category: str = Field(..., description="Attribute category (e.g., 'skin_type')")
    value: str = Field(..., description="Specific value (e.g., 'oily')")
    data_type: DataType = Field(..., description="Data type for validation")
    elicitation_priority: int = Field(..., ge=1, le=10, description="Priority (1=highest)")
    is_global: bool = Field(default=False, description="Applies across all domains")

    class Config:
        extra = "forbid"

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError(f"ID must be snake_case alphanumeric: {v}")
        return v


class IngredientNode(BaseModel):
    """Active or supporting ingredient in products"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    name: str = Field(..., description="Canonical name (snake_case)")
    display_name: str = Field(..., description="User-facing display name")
    function: str = Field(..., description="Primary function")
    category: str = Field(..., description="Category (e.g., 'active', 'carrier')")
    strength_levels: List[str] = Field(default_factory=list, description="Available strengths")

    class Config:
        extra = "forbid"

    @field_validator('id', 'name')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError(f"ID/name must be snake_case alphanumeric: {v}")
        return v


class ConstraintNode(BaseModel):
    """User constraint or limitation"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    type: ConstraintType = Field(..., description="Constraint type")
    value: str = Field(..., description="Constraint value")
    severity: Severity = Field(..., description="Severity level")

    class Config:
        extra = "forbid"

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError(f"ID must be snake_case alphanumeric: {v}")
        return v


class QuestionNode(BaseModel):
    """Question template for eliciting information"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    text: str = Field(..., description="Question text (may include {placeholders})")
    response_type: ResponseType = Field(..., description="Expected response type")
    options: List[str] = Field(default_factory=list, description="Options for choice-based questions")
    validation_rules: Dict[str, Any] = Field(default_factory=dict, description="Validation rules")

    class Config:
        extra = "forbid"

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError(f"ID must be snake_case alphanumeric: {v}")
        return v


class ProductNode(BaseModel):
    """Reference to a product in the PostgreSQL database"""
    id: str = Field(..., description="Graph node ID (matches UUID from DB)")
    db_product_id: str = Field(..., description="UUID from products table")

    class Config:
        extra = "forbid"


class DomainNode(BaseModel):
    """Top-level domain"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    name: str = Field(..., description="Domain name")
    slug: str = Field(..., description="URL-friendly slug")
    persona: Optional[str] = Field(default=None, description="Agent personality/instructions")

    class Config:
        extra = "forbid"


class SubDomainNode(BaseModel):
    """Sub-domain within a parent domain"""
    id: str = Field(..., description="Unique identifier (snake_case)")
    name: str = Field(..., description="Sub-domain name")
    slug: str = Field(..., description="URL-friendly slug")
    product_category: Optional[str] = Field(default=None, description="Product category")

    class Config:
        extra = "forbid"


class GraphNodes(BaseModel):
    """All nodes in the graph, organized by type"""
    problems: List[ProblemNode] = Field(default_factory=list)
    attributes: List[AttributeNode] = Field(default_factory=list)
    ingredients: List[IngredientNode] = Field(default_factory=list)
    constraints: List[ConstraintNode] = Field(default_factory=list)
    questions: List[QuestionNode] = Field(default_factory=list)
    products: List[ProductNode] = Field(default_factory=list)
    domains: List[DomainNode] = Field(default_factory=list)
    subdomains: List[SubDomainNode] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class GraphEdge(BaseModel):
    """Edge/relationship between two nodes"""
    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    relation: RelationType = Field(..., description="Relationship type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Edge properties")

    class Config:
        extra = "forbid"


class KnowledgeGraphSchema(BaseModel):
    """Complete knowledge graph definition"""
    metadata: GraphMetadata
    nodes: GraphNodes
    edges: List[GraphEdge]

    class Config:
        extra = "forbid"

    def validate_edges(self) -> List[str]:
        """
        Validate that all edges reference existing nodes.
        Returns list of error messages.
        """
        errors = []

        # Collect all node IDs
        all_node_ids = set()
        for node_list in [
            self.nodes.problems,
            self.nodes.attributes,
            self.nodes.ingredients,
            self.nodes.constraints,
            self.nodes.questions,
            self.nodes.products,
            self.nodes.domains,
            self.nodes.subdomains,
        ]:
            all_node_ids.update(node.id for node in node_list)

        # Check each edge
        for i, edge in enumerate(self.edges):
            if edge.source not in all_node_ids:
                errors.append(f"Edge {i}: source node '{edge.source}' not found")
            if edge.target not in all_node_ids:
                errors.append(f"Edge {i}: target node '{edge.target}' not found")

        return errors
