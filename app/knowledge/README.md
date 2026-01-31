# Knowledge Graph System

This directory contains the knowledge graph infrastructure for CurateAI's domain knowledge representation.

## 📁 Directory Structure

```
app/knowledge/
├── graphs/                      # YAML graph definitions
│   ├── skincare.yaml           # Skincare domain graph
│   └── wellness.yaml           # Wellness domain graph
├── __init__.py                 # Public API exports
├── schemas.py                  # Pydantic validation schemas
├── graph_loader.py             # NetworkX graph loader
├── query_engine.py             # High-level query interface
├── validate.py                 # Validation utility
├── example_usage.py            # Usage examples
└── README.md                   # This file
```

## 🚀 Quick Start

### Loading a Graph

```python
from app.knowledge import get_knowledge_graph

# Load the skincare graph
graph = get_knowledge_graph('skincare')

# Find a problem by synonym
problem_id = graph.find_problem_by_synonym('dark spots')
# Returns: 'dark_spots'

# Get problem details
problem = graph.get_node(problem_id)
print(problem['display_name'])  # "Dark Spots"
```

### Using the Query Engine (Recommended)

```python
from app.knowledge import GraphQueryEngine

# Extract problem from user text
problem = GraphQueryEngine.extract_problem_from_text(
    domain='skincare',
    text='hyperpigmentation'
)
# Returns: {'id': 'dark_spots', 'display_name': 'Dark Spots', ...}

# Get interview questions
questions = GraphQueryEngine.get_interview_questions(
    domain='skincare',
    problem_id='dark_spots'
)
# Returns: [
#   {
#     'priority': 1,
#     'question': {'text': 'What is your skin type?', ...}
#   },
#   ...
# ]

# Build search query with attribute boosting
search_query = GraphQueryEngine.build_search_query(
    domain='skincare',
    problem_id='dark_spots',
    user_attributes={'skin_type': 'skin_type_oily'}
)
# Returns: {
#   'primary_ingredients': ['niacinamide', 'vitamin_c', ...],
#   'boost_scores': {'niacinamide': 0.93, ...}
# }

# Check product safety
safety = GraphQueryEngine.filter_by_constraints(
    domain='skincare',
    product_ingredients=['retinol', 'vitamin_c'],
    user_constraints={'pregnancy': True}
)
# Returns: {
#   'is_safe': False,
#   'violations': [
#     {
#       'reason': 'May cause birth defects',
#       'alternatives': ['bakuchiol', 'vitamin_c']
#     }
#   ]
# }
```

## 📝 Adding a New Domain

### 1. Create Graph YAML File

Create `app/knowledge/graphs/your_domain.yaml`:

```yaml
metadata:
  domain: your_domain
  version: 1.0.0
  created_at: "2026-01-28"
  description: "Description of your domain"

nodes:
  problems:
    - id: problem_name
      name: "problem_name"
      display_name: "Problem Name"
      synonyms: ["synonym1", "synonym2"]
      severity_levels: [mild, moderate, severe]
      description: "Detailed description"

  attributes:
    - id: attr_category_value
      category: attr_category
      value: value
      data_type: single_choice
      elicitation_priority: 1
      is_global: false

  ingredients:
    - id: ingredient_name
      name: "ingredient_name"
      display_name: "Ingredient Display Name"
      function: "primary_function"
      category: "active"
      strength_levels: ["low", "medium", "high"]

  constraints:
    - id: constraint_name
      type: "medical"
      value: "true"
      severity: "hard"

  questions:
    - id: q_question_name
      text: "Question text?"
      response_type: "single_choice"
      options: ["Option 1", "Option 2"]

edges:
  - source: problem_name
    target: attr_category_value
    relation: REQUIRES_KNOWING
    properties:
      priority: 1
      is_optional: false
      reason: "Why this is needed"

  - source: ingredient_name
    target: problem_name
    relation: TREATS
    properties:
      mechanism: "How it works"
      efficacy: 0.85
      onset_time: "2-4 weeks"
      evidence_level: "clinical_trial"
```

### 2. Validate the Graph

```bash
python3 -m app.knowledge.validate your_domain
```

### 3. Test Loading

```python
from app.knowledge import get_knowledge_graph

graph = get_knowledge_graph('your_domain')
print(f"Loaded {graph.graph.number_of_nodes()} nodes")
```

## 🔧 Updating an Existing Graph

### Adding a New Problem

1. Add the problem node:

```yaml
nodes:
  problems:
    - id: new_problem
      name: "new_problem"
      display_name: "New Problem"
      synonyms: ["synonym1", "synonym2"]
      severity_levels: [mild, moderate, severe]
      description: "What this problem is"
```

2. Add REQUIRES_KNOWING edges:

```yaml
edges:
  - source: new_problem
    target: skin_type_oily  # Reference an existing attribute
    relation: REQUIRES_KNOWING
    properties:
      priority: 1
      is_optional: false
      reason: "Why you need to know this"
```

3. Add TREATS edges:

```yaml
edges:
  - source: vitamin_c  # Existing ingredient
    target: new_problem
    relation: TREATS
    properties:
      mechanism: "How it treats the problem"
      efficacy: 0.80
      onset_time: "4-6 weeks"
      evidence_level: "clinical_trial"
```

4. Validate:

```bash
python3 -m app.knowledge.validate skincare
```

### Adding a New Ingredient

1. Add the ingredient node:

```yaml
nodes:
  ingredients:
    - id: new_ingredient
      name: "new_ingredient"
      display_name: "New Ingredient"
      function: "primary_function"
      category: "active"
      strength_levels: ["5%", "10%", "15%"]
```

2. Add TREATS edges:

```yaml
edges:
  - source: new_ingredient
    target: acne  # Existing problem
    relation: TREATS
    properties:
      mechanism: "How it works"
      efficacy: 0.85
      onset_time: "2-4 weeks"
      evidence_level: "clinical_trial"
```

3. Add RECOMMENDED_FOR edges:

```yaml
edges:
  - source: new_ingredient
    target: skin_type_oily  # Existing attribute
    relation: RECOMMENDED_FOR
    properties:
      strength: 0.90
      evidence: "proven"
```

4. Add safety constraints if needed:

```yaml
edges:
  - source: new_ingredient
    target: pregnancy  # Existing constraint
    relation: CONTRAINDICATED_FOR
    properties:
      reason: "Why it's contraindicated"
      severity: "avoid"
      alternative_ingredients: ["safe_alternative"]
```

### Adding a New Attribute

1. Add all possible values for the attribute:

```yaml
nodes:
  attributes:
    - id: new_category_value1
      category: new_category
      value: value1
      data_type: single_choice
      elicitation_priority: 5
      is_global: false

    - id: new_category_value2
      category: new_category
      value: value2
      data_type: single_choice
      elicitation_priority: 5
      is_global: false
```

2. Add a question to elicit it:

```yaml
nodes:
  questions:
    - id: q_new_category
      text: "What is your {new_category}?"
      response_type: "single_choice"
      options: ["Value1", "Value2"]
```

3. Connect attribute to question:

```yaml
edges:
  - source: new_category_value1  # Reference one attribute value
    target: q_new_category
    relation: ELICITS_QUESTION
    properties:
      condition: "always"
      timing: "immediate"
```

4. Add to problem requirements:

```yaml
edges:
  - source: dark_spots  # Existing problem
    target: new_category_value1  # Reference one attribute value
    relation: REQUIRES_KNOWING
    properties:
      priority: 4
      is_optional: true
      reason: "Why this matters"
```

## 🛠️ Validation

### Validate All Graphs

```bash
python3 -m app.knowledge.validate
```

### Validate Specific Graph

```bash
python3 -m app.knowledge.validate skincare
```

### Show Graph Statistics

```bash
python3 -m app.knowledge.validate --stats
```

### Common Validation Errors

#### 1. Edge References Non-Existent Node

```
Edge 5: source node 'vitamin_d' not found
```

**Fix:** Ensure the node ID exists in the `nodes` section:

```yaml
nodes:
  ingredients:
    - id: vitamin_d  # Must match edge source exactly
      name: "vitamin_d"
      ...
```

#### 2. Duplicate Node IDs

```
Duplicate node IDs: {'skin_type_oily'}
```

**Fix:** Each node ID must be unique across all node types.

#### 3. Missing Required Properties

```
REQUIRES_KNOWING edge dark_spots -> skin_type_oily missing 'priority' property
```

**Fix:** Add the required property:

```yaml
edges:
  - source: dark_spots
    target: skin_type_oily
    relation: REQUIRES_KNOWING
    properties:
      priority: 1  # Required for REQUIRES_KNOWING
      is_optional: false
      reason: "Explanation"
```

## 🔄 Reloading Graphs in Development

Graphs are cached in memory. To reload after changes:

```python
from app.knowledge import reload_graph

# Force reload
graph = reload_graph('skincare')
```

## 📊 Graph Statistics

View graph statistics:

```python
from app.knowledge import GraphQueryEngine

stats = GraphQueryEngine.get_graph_stats('skincare')

print(stats['total_nodes'])      # 32
print(stats['total_edges'])      # 29
print(stats['nodes_by_type'])    # {'problem': 5, 'ingredient': 8, ...}
print(stats['edges_by_relation']) # {'TREATS': 8, 'REQUIRES_KNOWING': 7, ...}
```

## 🎯 Best Practices

### 1. Naming Conventions

- **Node IDs:** Use `snake_case` (e.g., `dark_spots`, `vitamin_c`)
- **Display Names:** Use title case (e.g., "Dark Spots", "Vitamin C")
- **Categories:** Use `snake_case` (e.g., `skin_type`, `age_group`)

### 2. Synonyms

Add comprehensive synonyms to improve matching:

```yaml
synonyms:
  - "hyperpigmentation"  # Medical term
  - "sun damage"         # Common term
  - "age spots"          # Colloquial term
  - "melasma"            # Specific condition
  - "PIH"                # Abbreviation
```

### 3. Priorities

Lower priority = asked first:

```yaml
priority: 1  # Ask first
priority: 2  # Ask second
priority: 3  # Ask third
```

### 4. Efficacy Scores

Base efficacy on evidence:

- **0.9-1.0:** Strong clinical evidence
- **0.7-0.9:** Moderate clinical evidence
- **0.5-0.7:** Limited evidence or user reviews
- **<0.5:** Anecdotal evidence

### 5. Evidence Levels

```yaml
evidence_level: "clinical_trial"  # Gold standard
evidence_level: "user_reviews"    # Community evidence
evidence_level: "anecdotal"       # Traditional use
```

## 🔌 Integration with Agents

### Router Agent

```python
from app.knowledge import GraphQueryEngine

# Extract problem from user message
problem = GraphQueryEngine.extract_problem_from_text(
    domain='skincare',
    text=user_message
)

if problem:
    state['extracted_context']['identified_problems'] = [problem['id']]
```

### Interviewer Agent

```python
# Get questions to ask
questions = GraphQueryEngine.get_interview_questions(
    domain=state['domain_slug'],
    problem_id=state['extracted_context']['identified_problems'][0]
)

# Ask questions in priority order
for q in questions:
    if not q['is_optional'] or should_ask_optional():
        ask_user(q['question']['text'], q['question']['options'])
```

### Search Architect Agent

```python
# Build search query
search_query = GraphQueryEngine.build_search_query(
    domain=state['domain_slug'],
    problem_id=problem_id,
    user_attributes=state['extracted_context']['user_attributes']
)

# Use boosted ingredients in search
search_results = await hybrid_search(
    ingredients=search_query['primary_ingredients'],
    boost_scores=search_query['boost_scores']
)
```

### Reranker Agent

```python
# Check each product for violations
for product in search_results:
    safety = GraphQueryEngine.filter_by_constraints(
        domain=state['domain_slug'],
        product_ingredients=product.ingredients,
        user_constraints=state['extracted_context']['constraints']
    )

    if not safety['is_safe']:
        # Exclude or warn user
        product.excluded = True
        product.exclusion_reason = safety['violations'][0]['reason']
```

## 📚 Examples

See `example_usage.py` for complete examples:

```bash
python3 -m app.knowledge.example_usage
```

## 🐛 Debugging

### Enable Debug Logging

```python
import logging
logging.getLogger('app.knowledge').setLevel(logging.DEBUG)
```

### Inspect Graph Structure

```python
from app.knowledge import get_knowledge_graph

graph = get_knowledge_graph('skincare')

# List all problems
problems = graph.find_nodes_by_type('problem')
for p in problems:
    print(f"{p['id']}: {p['display_name']}")

# Inspect edges
edges = graph.get_outgoing_edges('dark_spots', relation='REQUIRES_KNOWING')
for edge in edges:
    print(f"  → {edge['target']} (priority={edge['priority']})")
```

## 🚀 Future Enhancements

### Planned Features

- [ ] Neo4j integration for production scale
- [ ] Graph versioning and migration tools
- [ ] Web UI for graph editing
- [ ] A/B testing for edge properties
- [ ] Learning from user interactions
- [ ] Multi-language support

### Migration to Neo4j

When the graph exceeds 10,000 nodes or you need real-time updates:

1. Export YAML to Neo4j Cypher
2. Set up Neo4j instance
3. Update `graph_loader.py` to use Neo4j driver
4. Maintain backward compatibility with YAML

## 📖 Additional Resources

- [GraphArch.md](../../GraphArch.md) - Complete architecture documentation
- [CLAUDE.md](../../CLAUDE.md) - Project overview
- [Database.md](../../Database.md) - Database schema

## ❓ FAQ

**Q: Can I have multiple problems in one conversation?**
A: Yes! The router can identify multiple problems and store them in `identified_problems` array.

**Q: How do I handle problem combinations (e.g., acne + dark spots)?**
A: Use the `OFTEN_PAIRED_WITH` edge to link related problems. The interviewer can ask combined questions.

**Q: Can attributes be global across domains?**
A: Yes! Set `is_global: true` for attributes like `age_group` that apply everywhere.

**Q: How do I version control graph changes?**
A: YAML files are in git. Use semantic versioning in `metadata.version` and commit with clear messages.

**Q: What if an ingredient isn't in the graph?**
A: The system gracefully handles missing ingredients. Log a warning and fall back to vector search only.

## 🤝 Contributing

When updating graphs:

1. Create a feature branch
2. Make changes to YAML
3. Validate: `python3 -m app.knowledge.validate`
4. Test integration with agents
5. Update this README if adding new patterns
6. Commit with clear message
7. Submit PR

---

**Last Updated:** 2026-01-28
**Maintainer:** CurateAI Team
